"""
detector.py — recording threads, classification loop, and main entry point.

Each audio source is recorded continuously into a ring buffer. A paired
classify loop pulls audio from a queue, runs inference in a sliding window,
and saves clips to disk when a species is confirmed.

Dual-buffer design
------------------
Each recording thread feeds two consumers in parallel:

  * ``ctx.audio_queue`` — consumed by the paired :func:`_classify_loop` to
    build a sliding window for inference.
  * ``ctx.capture_buffer`` — a ring buffer (default 30 s) that records audio
    continuously. When a detection is confirmed, a deferred save task sleeps
    for the post-capture period, then reads the full clip from the ring buffer
    and writes it to disk.

This means saved clips are longer than the inference window, mirroring
BirdNET-Go's CaptureBuffer behaviour.

Multi-source mode
-----------------
When ``[[audio.sources]]`` blocks are present in config.toml, each source gets
its own :class:`_SourceContext` with independent queues, ring buffer, pending
detection state, and cooldown tracking. A recording thread and a classify loop
are started per source. All classify loops share one model via
``_inference_lock`` so inference is serialised (one model at a time) while
recording runs in parallel.

Inference model
---------------
The active model is selected by ``cfg.inference.model`` in ``config.toml``.
:func:`_classify_loop` reads ``model.window_seconds`` at startup so the rolling
buffer adapts to the model (3 s for BirdNET, 5 s for Perch v2). Audio is
recorded at ``cfg.audio.sample_rate``; any resampling happens inside the
model's ``run_inference`` method.

Cross-validation
----------------
When ``cfg.cross_validation.enabled`` is ``True``, a
:class:`~cross_validate.CrossValidator` is created in :func:`main` and stored
as ``_cross_validator``. Each deferred-save task runs the secondary model on
the same clip before writing to disk — if the two models disagree, the
detection can be dropped or flagged depending on config.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from audio import apply_highpass, save_clip
from audio.source import get_source
from publishers import birdmap, birdweather
import weather
from filters.species_filter import build_bou_allowed_set, build_birdnet_to_bto_map
from capture_buffer import CaptureBuffer
from config import cfg, get_species_config
from cross_validate import CrossValidationResult, CrossValidator
from database import init_db, record_detection, seed_species_info
from inference import Inferencer, get_model, get_secondary_model, get_secondary_model_name
from log_setup import setup_logging
from publishers.mqtt import init_mqtt, publish_detection
from retention import start_retention_thread
from spectrogram import save_spectrogram
from filters.nocturnal_filter import NocturnalFilter
from filters.seasonal_filter import SeasonalFilter, current_iso_week
from filters.privacy_filter import PrivacyFilter

if TYPE_CHECKING:
    from config import AudioSourceConfig

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
# stop_event, _executor, _cross_validator, and _privacy_filter are global.
# All per-source state (queues, ring buffers, pending detections, cooldowns)
# lives in _SourceContext objects created in main().

stop_event:      threading.Event     = threading.Event()

# Initialised in main() after config is loaded.
_executor:        ThreadPoolExecutor
_cross_validator: CrossValidator | None = None   # None when CV is disabled
_privacy_filter:  PrivacyFilter  | None = None   # None when privacy filter is disabled

# ── Cross-source deduplication ────────────────────────────────────────────────
# Tracks the most recent confirmed detection per species across all sources.
# Used to spot when a second microphone hears the same bird within a short window.
#
# Protected by _dedup_lock because deferred-save workers run concurrently.
# Keyed by species (BirdNET common name); value is (source_name, timestamp).
_dedup_lock:   threading.Lock = threading.Lock()
_dedup_recent: dict[str, tuple[str, datetime]] = {}


@dataclass
class _Pending:
    """Accumulates repeated inference hits for one species within a time window.

    A new entry is created on the first hit above the confidence threshold.
    Subsequent hits within ``confirmation_window_seconds`` increment ``hit_count``
    and update the best-confidence snapshot. When ``hit_count`` reaches
    ``min_detections`` the detection is confirmed and a deferred save is
    submitted; the entry is then removed. If the window expires before enough
    hits accumulate, the entry is silently discarded (false positive suppressed).
    """
    first_seen_mono:   float         # time.monotonic() at the first hit
    best_confidence:   float
    best_ts:           datetime
    best_begin_sample: int           # ring-buffer position at the best hit
    best_fallback:     np.ndarray    # raw PCM from the best hit (one analysis window)
    hit_count:         int


@dataclass
class _SourceContext:
    """Holds all pipeline state for a single audio source.

    In single-source mode there is exactly one context with
    ``source_config = None``. In multi-source mode there is one per
    ``[[audio.sources]]`` block.

    Each context owns its queue, ring buffer, pending-detection state, and
    cooldown tracker — none of these are shared across sources, so no locking
    is needed within a source's own threads.
    """
    name:           str                 # display name for logs and clip filenames
    audio_queue:    queue.Queue         # type: ignore[type-arg]
    capture_buffer: CaptureBuffer
    source_config:  AudioSourceConfig | None = None   # None = legacy single-source
    # Accessed only by the paired classify thread — no locking needed.
    pending:        dict[str, _Pending]    = field(default_factory=dict)
    last_detected:  dict[str, datetime]    = field(default_factory=dict)


# ── Deferred save ─────────────────────────────────────────────────────────────

def _check_dedup(species: str, source_name: str, ts: datetime) -> bool:
    """Return True if this detection is a duplicate from another source.

    A duplicate means the same species was already confirmed by a different
    source within the configured deduplication window. If so, we skip or flag
    rather than saving a second identical detection.

    Side effect: when not a duplicate, records this detection so future calls
    from other sources can detect it as a duplicate.

    Args:
        species:     BirdNET common name of the confirmed species.
        source_name: Name of the source that confirmed it.
        ts:          UTC timestamp of the best-confidence hit.

    Returns:
        True if this detection should be treated as a duplicate; False otherwise.
    """
    if not cfg.deduplication.enabled:
        return False

    window = timedelta(seconds=cfg.deduplication.window_seconds)

    with _dedup_lock:
        if species in _dedup_recent:
            prev_source, prev_ts = _dedup_recent[species]
            if prev_source != source_name and abs(ts - prev_ts) <= window:
                # Different source heard the same species within the window.
                # Keep the original entry so a third source is also caught.
                return True
        # Not a duplicate — register this detection as the new baseline.
        _dedup_recent[species] = (source_name, ts)
        return False

def _deferred_save(
    ts:             datetime,
    species:        str,
    conf:           float,
    begin_sample:   int,
    fallback_audio: np.ndarray,
    bto_name:       str | None,
    model_name:     str,
    capture_buffer: CaptureBuffer,
    source_name:    str | None,
    last_detected:  dict,
) -> None:
    """Sleep for the post-capture period, optionally cross-validate, then save the clip.

    Runs on a worker thread from ``_executor``. The general flow is:
      1. Wait for post-capture audio to be recorded (full-clip mode only).
      2. Read the clip segment from the ring buffer; fall back to the
         analysis window if the buffer no longer holds that segment.
      3. Run cross-validation — drop or flag if models disagree.
      4. Run privacy filter — drop if human speech is detected.
      5. Check cross-source deduplication — skip or flag if another source
         already saved this species recently.
      6. Save the clip, write to DB, and publish.

    Args:
        ts:             Wall-clock timestamp of the best-confidence hit.
        species:        Primary model species name.
        conf:           Confidence of the best hit (primary model).
        begin_sample:   Sample index where the analysis window started in the ring buffer.
        fallback_audio: Raw PCM from the best hit, used if the ring buffer misses.
        bto_name:       BTO British name for the DB row (may be None).
        model_name:     Inference backend that produced this detection.
        capture_buffer: Ring buffer for this source.
        source_name:    Source identifier; None in legacy single-source mode.
        last_detected:  Per-species cooldown timestamp dict from the source context.
                        Stamped with *ts* only when the clip is actually saved so that
                        CV-dropped, privacy-filtered, or dedup-skipped detections do
                        not consume the cooldown window.
    """
    try:
        window_samples = int(get_model().window_seconds) * cfg.audio.sample_rate
    
        if cfg.audio.clip_mode == "window":
            # Save only the model window plus a short leading pad — no sleep needed
            # because the detection window is already in the buffer.
            pre_samples  = int(cfg.audio.window_pad_seconds * cfg.audio.sample_rate)
            clip_samples = window_samples + pre_samples
        else:
            # Full-clip mode: wait for post-capture audio to be recorded.
            post_capture = (
                cfg.audio.clip_seconds
                - int(get_model().window_seconds)
                - cfg.audio.pre_capture_seconds
            )
            if post_capture > 0:
                time.sleep(post_capture)
            pre_samples  = cfg.audio.pre_capture_seconds * cfg.audio.sample_rate
            clip_samples = cfg.audio.clip_seconds        * cfg.audio.sample_rate
    
        # The recording thread writes in 1-second chunks, so the last few samples
        # may not be committed yet. Retry briefly before falling back to the
        # analysis-window clip.
        segment: np.ndarray | None = None
        for _attempt in range(10):
            segment = capture_buffer.read_segment(begin_sample - pre_samples, clip_samples)
            if segment is not None:
                break
            time.sleep(0.1)
    
        if segment is None:
            logger.warning(
                "[%s] capture buffer miss for %s at sample %d "
                "(clip_mode=%s, pre=%d samples); "
                "saving fallback clip (one analysis window)",
                source_name or "default",
                species, begin_sample, cfg.audio.clip_mode, pre_samples,
            )
            segment = fallback_audio
    
        # ── Cross-validation ──────────────────────────────────────────────────────
        cv_result: CrossValidationResult | None = None
        effective_conf = conf   # may be updated by CV result (always primary conf)
    
        if _cross_validator is not None:
            sample_rate   = cfg.audio.sample_rate
            cv_win_samp   = int(_cross_validator.window_seconds * sample_rate)
            cv_start      = pre_samples
    
            if len(segment) >= cv_start + cv_win_samp:
                cv_audio = segment[cv_start : cv_start + cv_win_samp]
            else:
                # Segment is shorter than expected — pass the full segment and let
                # the secondary model handle it.
                logger.debug(
                    "CV: audio segment shorter than secondary window "
                    "(%d < %d samples); using full segment",
                    len(segment), cv_start + cv_win_samp,
                )
                cv_audio = segment
    
            # Apply the same high-pass filter used for primary inference so both
            # models see consistent audio.
            if cfg.filter.enabled:
                try:
                    cv_audio = apply_highpass(
                        cv_audio,
                        sample_rate,
                        cfg.filter.cutoff_hz,
                        cfg.filter.order,
                    )
                except Exception:
                    logger.warning(
                        "high-pass filter failed for CV audio on %s — "
                        "using raw audio for secondary model",
                        species,
                    )
    
            cv_result = _cross_validator.validate(
                audio            = cv_audio,
                primary_species  = species,
                primary_bto_name = bto_name,
                primary_conf     = conf,
                species_name     = species,
            )
    
            if cv_result.action == "drop":
                logger.info(
                    "%-32s CV DROP   primary_bto=%-20s  secondary=%s (%.2f)",
                    species,
                    bto_name or "?",
                    cv_result.secondary_bto_name or cv_result.secondary_species or "none",
                    cv_result.secondary_confidence or 0.0,
                )
                return   # models disagree — discard, no clip saved, no DB row
    
            if cv_result.action == "flag":
                logger.info(
                    "%-32s CV FLAG   primary_bto=%-20s  secondary=%s (%.2f)",
                    species,
                    bto_name or "?",
                    cv_result.secondary_bto_name or cv_result.secondary_species or "none",
                    cv_result.secondary_confidence or 0.0,
                )
            else:
                # Both models agree — log for monitoring.
                if cv_result.performed and cv_result.agree:
                    logger.info(
                        "%-32s CV AGREE  primary_bto=%-20s  secondary=%s "
                        "(mean_conf=%.2f)",
                        species,
                        bto_name or "?",
                        cv_result.secondary_bto_name or cv_result.secondary_species or "?",
                        cv_result.final_confidence,
                    )
    
            effective_conf = cv_result.final_confidence
    
        # ── Privacy filter ────────────────────────────────────────────────────────
        # Scan the clip for human sounds after CV, so we only pay the cost for
        # clips that would otherwise be saved.
        if _privacy_filter is not None:
            # Use one model window starting at pre_samples — same slice CV uses.
            # Fall back to the full segment if the clip is shorter than expected.
            privacy_audio = segment[pre_samples : pre_samples + window_samples]
            if len(privacy_audio) < window_samples:
                privacy_audio = segment
            if _privacy_filter.scan(privacy_audio):
                logger.info(
                    "%-32s PRIVACY DROP — human sound detected in clip",
                    species,
                )
                return   # discard — no clip saved, no DB row, no publish
    
        # ── Cross-source deduplication ────────────────────────────────────────────
        # Only active in multi-source mode (source_name is not None).
        _deduplicated: bool | None = None
        if source_name is not None and _check_dedup(species, source_name, ts):
            if cfg.deduplication.on_duplicate == "skip":
                logger.info(
                    "%-32s DEDUP SKIP  source=%s — same species heard by another "
                    "source within %ds window",
                    species, source_name, cfg.deduplication.window_seconds,
                )
                return  # discard — no clip saved, no DB row
            else:  # "flag"
                logger.info(
                    "%-32s DEDUP FLAG  source=%s — saved with deduplicated=true",
                    species, source_name,
                )
                _deduplicated = True
    
        # ── Persist ───────────────────────────────────────────────────────────────
        # Stamp the cooldown timestamp now — after all filters have passed — so that
        # CV-dropped, privacy-filtered, or dedup-skipped detections do not block the
        # cooldown window for genuine future detections.
        last_detected[species] = ts
        clip_path = save_clip(segment, ts, species, source_name=source_name)
    
        # Pre-render and save the spectrogram PNG so it survives audio clip deletion.
        save_spectrogram(clip_path, cfg.paths.spectrograms_dir)
    
        # Build CV keyword args only when CV actually ran.
        is_flagged: bool = cv_result is not None and cv_result.action == "flag"
        cv_kwargs: dict = {}
        if cv_result is not None:
            cv_kwargs = dict(
                primary_confidence  = conf,
                cross_validated     = cv_result.performed,
                cv_secondary_model  = cv_result.secondary_model_name,
                cv_species          = cv_result.secondary_species,
                cv_bto_name         = cv_result.secondary_bto_name,
                cv_confidence       = cv_result.secondary_confidence,
                cv_agree            = cv_result.agree,
            )
    
        # Attach weather snapshot if available (cached; returns None when disabled).
        _wx = weather.get_weather(ts)
        weather_kwargs: dict = {}
        if _wx is not None:
            weather_kwargs = dict(
                weather_temp           = _wx.temperature,
                weather_humidity       = _wx.humidity,
                weather_wind_speed     = _wx.wind_speed,
                weather_wind_direction = _wx.wind_direction,
                weather_pressure       = _wx.pressure,
                weather_condition      = _wx.condition,
                weather_precipitation  = _wx.precipitation,
                weather_provider       = _wx.provider,
            )
    
        record_detection(
            ts, species, effective_conf, clip_path, [],
            bto_name, model_name,
            source_name  = source_name,
            deduplicated = _deduplicated,
            flagged      = is_flagged,
            **cv_kwargs,
            **weather_kwargs,
        )
        publish_detection(ts, species, effective_conf, clip_path, [],
                          bto_name=bto_name, source_name=source_name)
        birdmap.post_detection(ts, species, effective_conf, clip_path)
        birdweather.post_detection(ts, species, effective_conf, clip_path)
    except Exception:
        logger.exception(
            "Unhandled error in _deferred_save for %s (source=%s) "
            "— detection lost",
            species, source_name,
        )


# ── Threads ───────────────────────────────────────────────────────────────────

def _record_thread(ctx: _SourceContext) -> None:
    """Read audio chunks continuously and feed both the inference queue and ring buffer.

    The audio source (sounddevice or RTSP) is created here and lives for the
    lifetime of the thread. The source handles its own reconnection logic;
    this loop catches any unexpected error and retries after a short pause.
    """
    source = get_source(ctx.source_config)
    _src_prefix = f"[{ctx.name}]" if ctx.source_config is not None else ""
    try:
        while not stop_event.is_set():
            try:
                flat = source.read_chunk()
            except Exception:
                logger.exception(
                    "%s[audio error] retrying in 1 s", _src_prefix
                )
                time.sleep(1.0)
                continue
            ctx.capture_buffer.write(flat)   # continuous ring — always recording
            ctx.audio_queue.put(flat)        # sliding window for inference
    finally:
        source.close()


def _classify_loop(
    ctx:            _SourceContext,
    bou_allowed:    frozenset[str],
    birdnet_to_bto: dict[str, str],
    seasonal:       SeasonalFilter,
    nocturnal:      NocturnalFilter,
    model:          Inferencer,
    inference_lock: threading.Lock,
) -> None:
    """
    Main detection pipeline: consume audio, run inference, confirm species, save clips.

    For each sliding window of audio:
      1. Optionally apply high-pass filter before inference (raw audio is kept
         for clip saving).
      2. Run inference under ``inference_lock`` — one model at a time across sources.
      3. Drop species on the global exclude list.
      4. Apply per-species minimum confidence threshold.
      4b. Drop species not in the UK BOU list.
      4c. Drop species outside their expected season.
      4d. Drop nocturnal/crepuscular species outside their active hours.
      5. Confirmation filter: accumulate hits in ``ctx.pending`` until
         ``min_detections`` is reached within ``confirmation_window_seconds``.
         The highest-confidence hit's audio and timestamp are used for the clip.
      6. Cooldown check: skip if this species was saved too recently.
      7. Submit a deferred-save task for each confirmed species.
    """
    buffer: list[np.ndarray] = []
    window_blocks  = int(model.window_seconds) // cfg.audio.hop_seconds
    window_samples = int(model.window_seconds)  * cfg.audio.sample_rate
    _window_count  = 0
    # Only include source name in log prefix in multi-source mode.
    _src_prefix = f"[{ctx.name}]" if ctx.source_config is not None else ""

    while not stop_event.is_set():
        try:
            chunk = ctx.audio_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        buffer.append(chunk)
        if len(buffer) > window_blocks:
            buffer.pop(0)

        if len(buffer) < window_blocks:
            continue  # still filling the initial window

        audio = np.concatenate(buffer)
        _window_count += 1

        # ── Step 1: optional high-pass filter (inference only) ────────────────
        # Filter a copy so save_clip always writes unmodified audio.
        if cfg.filter.enabled:
            inference_audio = apply_highpass(
                audio,
                cfg.audio.sample_rate,
                cfg.filter.cutoff_hz,
                cfg.filter.order,
            )
        else:
            inference_audio = audio

        try:
            with inference_lock:
                candidates = model.run_inference(inference_audio)
        except Exception:
            logger.exception(
                "%s[inference error] window %d — skipping",
                _src_prefix, _window_count,
            )
            continue

        ts = datetime.now(timezone.utc)

        # Log a heartbeat every ~60 windows so the loop is visible in logs.
        if _window_count % 60 == 0:
            if candidates:
                top_s, top_c = candidates[0]
                logger.info(
                    "%s[heartbeat] window=%d  top: %s %.3f",
                    _src_prefix, _window_count, top_s, top_c,
                )
            else:
                logger.info(
                    "%s[heartbeat] window=%d  no candidates",
                    _src_prefix, _window_count,
                )

        if not candidates:
            continue

        # ── Step 3: exclude list ──────────────────────────────────────────────
        if cfg.exclude:
            candidates = [
                (species, conf)
                for species, conf in candidates
                if species.lower() not in cfg.exclude
            ]

        if not candidates:
            continue

        # ── Step 4: per-species confidence threshold ──────────────────────────
        # Filter early so low-confidence hits never reach the BOU/seasonal steps.
        # This matters especially for Perch, which returns 14k+ softmax classes.
        candidates = [
            (species, conf)
            for species, conf in candidates
            if conf >= get_species_config(species).min_confidence
        ]

        if not candidates:
            continue

        # ── Step 4b: BOU allowlist — UK species only ──────────────────────────
        filtered = [
            (species, conf)
            for species, conf in candidates
            if species in bou_allowed
        ]
        if len(filtered) < len(candidates):
            for species, conf in candidates:
                if species not in bou_allowed:
                    logger.debug(
                        "%-32s not in BOU allowlist — suppressed",
                        species,
                    )
        candidates = filtered

        if not candidates:
            continue

        # ── Step 4c: seasonal presence filter ────────────────────────────────
        if seasonal.enabled:
            week = current_iso_week(ts)
            filtered = [
                (species, conf)
                for species, conf in candidates
                if seasonal.check(species, week)
            ]
            if len(filtered) < len(candidates):
                for species, conf in candidates:
                    if not seasonal.check(species, week):
                        logger.debug(
                            "%-32s out of season (week %d) — suppressed",
                            species, week,
                        )
            candidates = filtered

        if not candidates:
            continue

        # ── Step 4d: nocturnal/crepuscular time-of-day filter ─────────────────
        if nocturnal.enabled:
            filtered = [
                (species, conf)
                for species, conf in candidates
                if nocturnal.check(species, ts)
            ]
            if len(filtered) < len(candidates):
                for species, conf in candidates:
                    if not nocturnal.check(species, ts):
                        logger.debug(
                            "%-32s outside active hours — suppressed",
                            species,
                        )
            candidates = filtered

        if not candidates:
            continue

        # ── Steps 5–7: confirmation filter + cooldown + deferred save ─────────
        now_mono     = time.monotonic()
        begin_sample = max(0, ctx.capture_buffer.total_written - window_samples)

        for species, conf in candidates:
            sc = get_species_config(species)
            logger.info("%-32s %.2f", species, conf)

            p = ctx.pending.get(species)

            # Discard stale pending state if the confirmation window has expired.
            if p is not None and now_mono - p.first_seen_mono > sc.confirmation_window_seconds:
                logger.debug(
                    "%-32s confirmation window expired (%d/%d hits)",
                    species, p.hit_count, sc.min_detections,
                )
                del ctx.pending[species]
                p = None

            if p is None:
                # First hit — start tracking this species.
                ctx.pending[species] = _Pending(
                    first_seen_mono   = now_mono,
                    best_confidence   = conf,
                    best_ts           = ts,
                    best_begin_sample = begin_sample,
                    best_fallback     = audio.copy(),
                    hit_count         = 1,
                )
                p = ctx.pending[species]
            else:
                # Another hit within the window — keep the best-confidence snapshot.
                p.hit_count += 1
                if conf > p.best_confidence:
                    p.best_confidence   = conf
                    p.best_ts           = ts
                    p.best_begin_sample = begin_sample
                    p.best_fallback     = audio.copy()

            if p.hit_count < sc.min_detections:
                logger.debug("%-32s pending %d/%d", species, p.hit_count, sc.min_detections)
                continue

            # Confirmed — check cooldown before saving.
            cooldown_td = timedelta(seconds=sc.cooldown_seconds)
            last_saved  = ctx.last_detected.get(
                species, datetime.min.replace(tzinfo=timezone.utc)
            )
            if ts - last_saved < cooldown_td:
                logger.debug("%-32s confirmed but in cooldown", species)
                del ctx.pending[species]
                continue

            # Confirmed and not in cooldown — submit save task.
            logger.info(
                "%-32s CONFIRMED (%d hits, best=%.2f)",
                species, p.hit_count, p.best_confidence,
            )
            bto_name = birdnet_to_bto.get(species)
            # In legacy single-source mode pass source_name=None so clip filenames
            # and DB rows stay in the pre-multi-source format.
            _save_source_name = ctx.name if ctx.source_config is not None else None
            _executor.submit(
                _deferred_save,
                p.best_ts, species, p.best_confidence,
                p.best_begin_sample, p.best_fallback,
                bto_name, cfg.inference.model,
                ctx.capture_buffer, _save_source_name,
                ctx.last_detected,
            )
            del ctx.pending[species]


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    setup_logging()

    model     = get_model()
    label_map = model.load_label_map()
    logger.info(
        "Inference model: %s  (window: %.0f s)",
        cfg.inference.model, model.window_seconds,
    )

    # Validate clip geometry now that the model window length is known.
    _model_window = int(model.window_seconds)
    _post_capture = 0  # only meaningful when clip_mode = "full"
    if cfg.audio.clip_mode == "full":
        _post_capture = cfg.audio.clip_seconds - _model_window - cfg.audio.pre_capture_seconds
        if _post_capture < 0:
            raise ValueError(
                f"[audio] clip_seconds ({cfg.audio.clip_seconds}) must be >= "
                f"model window ({_model_window} s) + pre_capture_seconds "
                f"({cfg.audio.pre_capture_seconds} s); "
                f"got post_capture_seconds = {_post_capture}"
            )

    # Build the BOU allowed set and BirdNET→BTO name map.
    # The BOU filter is always active — this detector is UK-specific.
    _bou_force     = cfg.bou_override_species()
    bou_allowed    = build_bou_allowed_set(label_map, exclude_status=cfg.species_filter.exclude_status, force_include=_bou_force)
    birdnet_to_bto = build_birdnet_to_bto_map(label_map, exclude_status=cfg.species_filter.exclude_status, force_include=_bou_force)
    logger.info("BOU filter active — non-BOU species will be suppressed")

    seasonal = SeasonalFilter(
        enabled   = cfg.seasonal_filter.enabled,
        json_path = cfg.seasonal_filter.filter_json,
    )
    if cfg.seasonal_filter.enabled:
        logger.info("Seasonal filter enabled — out-of-season detections will be suppressed")
    else:
        logger.info("Seasonal filter disabled")

    nocturnal = NocturnalFilter(
        enabled           = cfg.nocturnal_filter.enabled,
        json_path         = cfg.nocturnal_filter.filter_json,
        lat               = cfg.location.lat,
        lon               = cfg.location.lon,
        timezone_str      = cfg.general.timezone,
        species_overrides = cfg._species_overrides,
    )
    if cfg.nocturnal_filter.enabled:
        logger.info("Nocturnal filter enabled — out-of-hours detections will be suppressed")
    else:
        logger.info("Nocturnal filter disabled")

    # ── Cross-validation setup ────────────────────────────────────────────────
    global _cross_validator
    if cfg.cross_validation.enabled:
        secondary_name  = get_secondary_model_name()
        secondary_model = get_secondary_model()
        secondary_label_map = secondary_model.load_label_map()

        # Build a BTO map for the secondary model so species names can be matched
        # across label namespaces (BirdNET uses IOC names, Perch uses eBird).
        secondary_bto_map = build_birdnet_to_bto_map(secondary_label_map, exclude_status=cfg.species_filter.exclude_status, force_include=_bou_force)

        _cross_validator = CrossValidator(
            secondary_model      = secondary_model,
            secondary_bto_map    = secondary_bto_map,
            secondary_model_name = secondary_name,
            min_conf_threshold   = cfg.cross_validation.cv_min_confidence,
        )
        logger.info(
            "Cross-validation enabled — secondary model: %s (window: %.0f s)  "
            "skip_threshold=%.2f  on_disagree=%s  cv_min_confidence=%.3f",
            secondary_name, secondary_model.window_seconds,
            cfg.cross_validation.skip_threshold, cfg.cross_validation.on_disagree,
            cfg.cross_validation.cv_min_confidence,
        )

        # Pre-warm the secondary model so the first live CV call doesn't stall
        # a save worker. run_inference() loads the TF graph on first call;
        # doing it here moves that cost to startup.
        logger.info("Pre-warming secondary model (%s) — loading TF graph…", secondary_name)
        _warmup_samples = int(secondary_model.window_seconds * cfg.audio.sample_rate)
        secondary_model.run_inference(np.zeros(_warmup_samples, dtype=np.float32))
        logger.info("Secondary model (%s) pre-warm complete.", secondary_name)
    else:
        logger.info("Cross-validation disabled")

    # ── Privacy filter setup ──────────────────────────────────────────────────
    global _privacy_filter
    if cfg.privacy_filter.enabled:
        _privacy_filter = PrivacyFilter(cfg.privacy_filter, cfg.audio.sample_rate)
        logger.info(
            "Privacy filter enabled — clips with human speech will be dropped "
            "(threshold=%.2f  min_voiced_fraction=%.2f)",
            cfg.privacy_filter.threshold,
            cfg.privacy_filter.min_voiced_fraction,
        )
    else:
        logger.info("Privacy filter disabled")

    if cfg.deduplication.enabled:
        logger.info(
            "Deduplication enabled — window=%ds  on_duplicate=%s",
            cfg.deduplication.window_seconds, cfg.deduplication.on_duplicate,
        )
    else:
        logger.info("Deduplication disabled")

    init_db()
    seed_species_info(Path(__file__).parent / "filters" / "uk_species_filter.json")
    init_mqtt()
    weather.init_weather()

    start_retention_thread()

    # ── Build per-source contexts ─────────────────────────────────────────────
    if cfg.audio.sources is not None:
        # Multi-source mode: one context per [[audio.sources]] block.
        contexts = [
            _SourceContext(
                name           = src.name,
                audio_queue    = queue.Queue(),
                capture_buffer = CaptureBuffer(
                    max_seconds = cfg.audio.capture_buffer_seconds,
                    sample_rate = cfg.audio.sample_rate,
                ),
                source_config  = src,
            )
            for src in cfg.audio.sources
        ]
        logger.info(
            "Multi-source mode: %d source(s) — %s",
            len(contexts),
            ", ".join(f"'{c.name}' ({c.source_config.type})" for c in contexts),  # type: ignore[union-attr]
        )
    else:
        # Legacy single-source mode.
        contexts = [
            _SourceContext(
                name           = "default",
                audio_queue    = queue.Queue(),
                capture_buffer = CaptureBuffer(
                    max_seconds = cfg.audio.capture_buffer_seconds,
                    sample_rate = cfg.audio.sample_rate,
                ),
                source_config  = None,
            )
        ]

    # ── Initialise shared executor and inference lock ─────────────────────────
    global _executor
    n_sources = len(contexts)
    # Scale worker threads with source count; minimum 4 for single-source mode.
    _executor = ThreadPoolExecutor(
        max_workers        = max(4, n_sources * 2),
        thread_name_prefix = "clip_saver",
    )
    # Shared lock ensures inference runs one-at-a-time across all sources,
    # preventing race conditions on the model's internal state.
    inference_lock = threading.Lock()

    if cfg.audio.clip_mode == "window":
        _clip_total = cfg.audio.window_pad_seconds + _model_window
        logger.info(
            "Capture buffer: %d s ring  |  clip mode: window  "
            "(%.1f s pad + %d s model window = %.1f s total)",
            cfg.audio.capture_buffer_seconds,
            cfg.audio.window_pad_seconds,
            _model_window,
            _clip_total,
        )
    else:
        logger.info(
            "Capture buffer: %d s ring  |  clip: %d s  (pre=%d s, post=%d s)",
            cfg.audio.capture_buffer_seconds,
            cfg.audio.clip_seconds,
            cfg.audio.pre_capture_seconds,
            _post_capture,
        )

    # ── Start recording threads (one per source, all daemon) ─────────────────
    for ctx in contexts:
        t = threading.Thread(
            target=_record_thread,
            args=(ctx,),
            daemon=True,
            name=f"record-{ctx.name}",
        )
        t.start()

    # ── Start classify loop threads ───────────────────────────────────────────
    # Run N-1 classify loops in daemon threads; the last one runs on the main
    # thread so KeyboardInterrupt is caught naturally.
    classify_args = (bou_allowed, birdnet_to_bto, seasonal, nocturnal, model, inference_lock)
    for ctx in contexts[:-1]:
        t = threading.Thread(
            target=_classify_loop,
            args=(ctx, *classify_args),
            daemon=True,
            name=f"classify-{ctx.name}",
        )
        t.start()

    try:
        _classify_loop(contexts[-1], *classify_args)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        _executor.shutdown(wait=True)
