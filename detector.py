"""
detector.py — microphone recording thread, classify loop, and main entry.

Per-species configuration (min_confidence, cooldown_seconds) is looked up for
every detection via ``get_species_config`` so each species can have its own
thresholds.

Dual-buffer design
------------------
Each recording thread feeds two consumers in parallel:

  * ``ctx.audio_queue`` — used by the paired :func:`_classify_loop` to maintain
    a sliding analysis window that is passed to the classifier.
  * ``ctx.capture_buffer`` — a large ring buffer (default 30 s) that records
    audio continuously.  When a detection fires, a *deferred save task* is
    submitted to ``_executor``; it sleeps for ``post_capture_seconds`` (so the
    full post-detection audio is captured), then reads the complete clip segment
    from the ring buffer and persists it to disk.

The benefit: saved clips are longer than the analysis window (default 15 s),
exactly mirroring BirdNET-Go's CaptureBuffer behaviour.

Multi-source mode
-----------------
When ``[[audio.sources]]`` blocks are present in config.toml, each source gets
its own :class:`_SourceContext` holding independent queues, ring buffer, pending
accumulation state, and cooldown tracking.  A recording thread and a classify
loop thread are started for every source.  All classify loops share one model
instance via ``_inference_lock`` so inference is serialised (avoids race
conditions on the model's internal state) while recording continues in parallel.

Inference model
---------------
The active model is selected by ``cfg.inference.model`` in ``config.toml``.
:func:`_classify_loop` queries ``model.window_seconds`` at startup so the
rolling buffer automatically resizes to suit the model (3 s for BirdNET, 5 s
for Perch v2).  Audio is always recorded at ``cfg.audio.sample_rate``; any
resampling needed by the model happens inside the model's ``run_inference``
method.

Cross-validation
----------------
When ``cfg.cross_validation.enabled`` is ``True``, a
:class:`~cross_validate.CrossValidator` is initialised in :func:`main` and
stored as the module-level ``_cross_validator`` variable.  Each deferred-save
task invokes the validator before writing to disk so that the audio clip and
database row are only created if the secondary model agrees (or the primary
confidence clears the skip threshold).
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
from filters.nocturnal_filter import NocturnalFilter
from filters.seasonal_filter import SeasonalFilter, current_iso_week
from filters.privacy_filter import PrivacyFilter

if TYPE_CHECKING:
    from config import AudioSourceConfig

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
# stop_event, _executor, _cross_validator, _privacy_filter are global.
# All audio queue / capture buffer / pending / cooldown state is per-source,
# held in _SourceContext objects created in main().

stop_event:      threading.Event     = threading.Event()

# Initialised in main() after config is loaded.
_executor:        ThreadPoolExecutor
_cross_validator: CrossValidator | None = None   # None when CV is disabled
_privacy_filter:  PrivacyFilter  | None = None   # None when privacy filter is disabled

# ── Cross-source deduplication state ─────────────────────────────────────────
# Tracks the most recent confirmed detection per species across all sources so
# that a second source confirming the same bird within the deduplication window
# can be identified as a duplicate.
#
# Protected by _dedup_lock because deferred-save workers run concurrently.
# Keyed by species (BirdNET common name); value is (source_name, timestamp).
_dedup_lock:   threading.Lock = threading.Lock()
_dedup_recent: dict[str, tuple[str, datetime]] = {}


@dataclass
class _Pending:
    """Accumulates repeated inference hits for one species within a time window.

    A new entry is created on the first hit that clears the confidence
    threshold.  Subsequent hits within ``confirmation_window_seconds``
    increment ``hit_count`` and update the best-confidence snapshot.
    When ``hit_count`` reaches ``min_detections`` the detection is confirmed
    and a deferred save is submitted; the entry is then removed.
    If the window expires before enough hits accumulate the entry is discarded
    silently (false positive suppressed).
    """
    first_seen_mono:   float         # time.monotonic() at the first hit
    best_confidence:   float
    best_ts:           datetime
    best_begin_sample: int           # ring-buffer cursor at the best hit
    best_fallback:     np.ndarray    # raw PCM copy (one analysis window) from the best hit
    hit_count:         int


@dataclass
class _SourceContext:
    """Per-source pipeline state: one instance per audio source.

    In legacy single-source mode there is exactly one context with
    ``source_config = None``.  In multi-source mode there is one context per
    ``[[audio.sources]]`` block.

    Each context owns its audio queue, ring buffer, pending-detection
    accumulator, and cooldown tracker.  These are never shared across sources
    so no locking is required to access them — each is only touched by its
    paired recording thread and classify-loop thread.
    """
    name:           str                 # display name for logging and clip filenames
    audio_queue:    queue.Queue         # type: ignore[type-arg]
    capture_buffer: CaptureBuffer
    source_config:  AudioSourceConfig | None = None   # None = legacy single-source
    # Per-source state; each is only accessed from its paired classify thread.
    pending:        dict[str, _Pending]    = field(default_factory=dict)
    last_detected:  dict[str, datetime]    = field(default_factory=dict)


# ── Deferred save ─────────────────────────────────────────────────────────────

def _check_dedup(species: str, source_name: str, ts: datetime) -> bool:
    """Return ``True`` if *species* from *source_name* at *ts* is a duplicate.

    A detection is a duplicate when all three conditions hold:

    1. ``[deduplication] enabled = true``
    2. The same species was recently confirmed from a **different** source.
    3. The gap between the two detections is ≤ ``window_seconds``.

    Thread-safe — protected by :data:`_dedup_lock`.

    Side effect: when the detection is *not* a duplicate the entry in
    :data:`_dedup_recent` is updated so future calls from other sources can
    detect duplicates of this detection.

    Args:
        species:     BirdNET common name of the confirmed species.
        source_name: Name of the source that confirmed it (from
                     ``[[audio.sources]] name``).  Must be non-None (callers
                     skip this check in single-source mode).
        ts:          UTC timestamp of the best-confidence hit.

    Returns:
        ``True`` if this detection should be treated as a duplicate;
        ``False`` otherwise.
    """
    if not cfg.deduplication.enabled:
        return False

    window = timedelta(seconds=cfg.deduplication.window_seconds)

    with _dedup_lock:
        if species in _dedup_recent:
            prev_source, prev_ts = _dedup_recent[species]
            if prev_source != source_name and abs(ts - prev_ts) <= window:
                # Same species, different source, within the window.
                # Don't overwrite _dedup_recent — keep the original entry so
                # a third source in the same window is also caught.
                return True
        # Not a duplicate (or same source, or outside window); register as
        # the current baseline so later sources can detect a duplicate of this.
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
) -> None:
    """Sleep for the post-capture period, cross-validate, then persist.

    Runs on a worker thread from ``_executor``.  If cross-validation is
    enabled and the two models disagree, the detection may be dropped or
    flagged according to config before any I/O is attempted.

    ``begin_sample`` points to the start of the best-confidence inference
    window in the ring buffer.  In ``"window"`` clip mode the saved clip is
    ``window_pad_seconds`` before that point and exactly ``model.window_seconds``
    long.  In ``"full"`` clip mode it extends ``pre_capture_seconds`` before
    the window and ``post_capture_seconds`` after.

    If the ring buffer read fails (e.g. the segment was overwritten because
    the executor backlog was unusually deep), the function falls back to
    saving the analysis window that was captured at detection time.

    Args:
        ts:             Wall-clock timestamp of the best-confidence hit.
        species:        Primary model common name of the confirmed species.
        conf:           Confidence of the best hit (primary model).
        begin_sample:   Absolute sample index where the analysis window started.
        fallback_audio: Raw PCM array from the best hit (one analysis window).
        bto_name:       BTO British name for the database row (may be None).
        model_name:     Inference backend that produced this detection.
        capture_buffer: The ring buffer for this source (per-source in multi-source).
        source_name:    Source identifier for clip filenames and DB rows; ``None``
                        in legacy single-source mode.
    """
    window_samples = int(get_model().window_seconds) * cfg.audio.sample_rate

    if cfg.audio.clip_mode == "window":
        # Save only the model analysis window plus a short leading pad.
        # No post-capture sleep is needed — the detection window is already
        # fully in the capture buffer by the time this task runs.
        pre_samples  = int(cfg.audio.window_pad_seconds * cfg.audio.sample_rate)
        clip_samples = window_samples + pre_samples
    else:
        # Legacy "full" mode: pre_capture + model window + post_capture.
        post_capture = (
            cfg.audio.clip_seconds
            - int(get_model().window_seconds)
            - cfg.audio.pre_capture_seconds
        )
        if post_capture > 0:
            time.sleep(post_capture)
        pre_samples  = cfg.audio.pre_capture_seconds * cfg.audio.sample_rate
        clip_samples = cfg.audio.clip_seconds        * cfg.audio.sample_rate

    # The recording thread writes in 1-second chunks, so after sleeping exactly
    # post_capture_seconds the final samples may not have been committed yet.
    # Retry up to 10 times (≤1 s total) before falling back to the analysis clip.
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
            # Segment shorter than required — use the whole segment and let
            # the secondary model handle variable-length input gracefully.
            logger.debug(
                "CV: audio segment shorter than secondary window "
                "(%d < %d samples); using full segment",
                len(segment), cv_start + cv_win_samp,
            )
            cv_audio = segment

        # Apply the same high-pass filter that was used for primary inference
        # so both models see the same pre-processed audio.
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
            return   # discard — no clip saved, no DB row

        if cv_result.action == "flag":
            logger.info(
                "%-32s CV FLAG   primary_bto=%-20s  secondary=%s (%.2f)",
                species,
                bto_name or "?",
                cv_result.secondary_bto_name or cv_result.secondary_species or "none",
                cv_result.secondary_confidence or 0.0,
            )
        else:
            # "save" — log agreement for monitoring
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
    # Re-run the primary model on the analysis window to check for human sounds.
    # Inserted after CV so that CV drops are already handled and we only pay the
    # scan cost for clips that would otherwise be saved.
    if _privacy_filter is not None:
        # Extract one model-window worth of audio starting at pre_samples (the
        # same slice CV uses for the secondary model).  Fall back to the full
        # segment when it is shorter than expected (e.g. a buffer miss that
        # returned the fallback clip).
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
    # Only active in multi-source mode (source_name is not None) and when
    # cfg.deduplication.enabled is true.  In single-source mode source_name is
    # None so the check is skipped entirely.
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
    clip_path = save_clip(segment, ts, species, source_name=source_name)

    # Build cross-validation keyword args for record_detection only when CV ran.
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
            flagged             = (cv_result.action == "flag") or None,
        )
        # Store None instead of False for flagged when it's not actually flagged,
        # keeping the column sparse for normal (non-flagged) rows.
        if cv_kwargs["flagged"] is False:
            cv_kwargs["flagged"] = None

    # Fetch weather snapshot (uses cached data if within cfg.weather.cache_seconds;
    # returns None silently when weather is disabled or the provider is unavailable).
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
        **cv_kwargs,
        **weather_kwargs,
    )
    publish_detection(ts, species, effective_conf, clip_path, [],
                      bto_name=bto_name, source_name=source_name)
    birdmap.post_detection(ts, species, effective_conf, clip_path)
    birdweather.post_detection(ts, species, effective_conf, clip_path)


# ── Threads ───────────────────────────────────────────────────────────────────

def _record_thread(ctx: _SourceContext) -> None:
    """Continuously record hop-length chunks onto the audio queue and into
    the capture buffer.

    The active audio source (sounddevice or RTSP) is created here and lives
    for the lifetime of the thread.  Each source handles its own internal
    error recovery (e.g. RTSP reconnection); the outer try/except catches any
    unexpected exception and retries after a 1-second pause.
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
    Consume audio chunks, maintain a rolling window, run inference, and
    apply per-species confidence thresholds, confirmation filter, and cooldowns.

    For each window:
      1. Apply high-pass filter to a copy of the audio if enabled in config
         (the original array is kept untouched for clip saving).
      2. Run inference under ``inference_lock`` — returns detections above a raw
         floor (BirdNET: 0.01 via analyze(); Perch: 0.01 applied in
         run_inference()).
      3. Drop any species on the global exclude list.
      4. Filter each detection by its per-species ``min_confidence``.
         This runs before BOU/seasonal so low-confidence hits never appear
         in the filter-suppressed log lines.
      4b. BOU allowlist filter: drop species not in the UK BOU species list.
      4c. Seasonal filter: drop species outside their expected season.
      4d. Nocturnal filter: drop nocturnal/crepuscular species detected outside
          their active time window (configurable per-species).
      5. Confirmation filter: each species accumulates hits in ``ctx.pending``
         until it reaches ``min_detections`` within ``confirmation_window_seconds``.
         Only confirmed species proceed; the highest-confidence hit's audio
         and timestamp are used for the saved clip.
      6. Cooldown check (at confirmation time): skip if the species was saved
         too recently.  Cooldown clock starts when the save is submitted.
      7. Submit a deferred-save task for each confirmed species.
    """
    buffer: list[np.ndarray] = []
    window_blocks  = int(model.window_seconds) // cfg.audio.hop_seconds
    window_samples = int(model.window_seconds)  * cfg.audio.sample_rate
    _window_count  = 0
    # Include source name in log prefix only when running in multi-source mode;
    # in legacy single-source mode ctx.source_config is None, so we omit the
    # prefix to keep the terminal output identical to the pre-multi-source format.
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
        # Apply to a separate array so save_clip always writes the raw audio.
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

        # ── Heartbeat: log every 60 windows (~60 s) so the loop is visible ────
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

        # ── Step 4: per-species confidence filter ─────────────────────────────
        # Applied before BOU/seasonal so that low-confidence hits never reach
        # the filter logging paths.  This is particularly important for Perch,
        # which returns all 14 k+ softmax classes; applying the floor early
        # keeps the BOU/seasonal stages to a manageable candidate set.
        candidates = [
            (species, conf)
            for species, conf in candidates
            if conf >= get_species_config(species).min_confidence
        ]

        if not candidates:
            continue

        # ── Step 4b: BOU allowlist filter ─────────────────────────────────────
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
        begin_sample = ctx.capture_buffer.total_written - window_samples

        for species, conf in candidates:
            sc = get_species_config(species)
            logger.info("%-32s %.2f", species, conf)

            p = ctx.pending.get(species)

            # Discard stale pending state if the confirmation window expired.
            if p is not None and now_mono - p.first_seen_mono > sc.confirmation_window_seconds:
                logger.debug(
                    "%-32s confirmation window expired (%d/%d hits)",
                    species, p.hit_count, sc.min_detections,
                )
                del ctx.pending[species]
                p = None

            if p is None:
                # First hit — open a new pending window.
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
                # Subsequent hit within the window — accumulate.
                p.hit_count += 1
                if conf > p.best_confidence:
                    p.best_confidence   = conf
                    p.best_ts           = ts
                    p.best_begin_sample = begin_sample
                    p.best_fallback     = audio.copy()

            if p.hit_count < sc.min_detections:
                logger.debug("%-32s pending %d/%d", species, p.hit_count, sc.min_detections)
                continue

            # Confirmed — check cooldown at confirmation time.
            cooldown_td = timedelta(seconds=sc.cooldown_seconds)
            last_saved  = ctx.last_detected.get(
                species, datetime.min.replace(tzinfo=timezone.utc)
            )
            if ts - last_saved < cooldown_td:
                logger.debug("%-32s confirmed but in cooldown", species)
                del ctx.pending[species]
                continue

            # Accept: record cooldown start and submit the deferred save.
            logger.info(
                "%-32s CONFIRMED (%d hits, best=%.2f)",
                species, p.hit_count, p.best_confidence,
            )
            ctx.last_detected[species] = ts
            bto_name = birdnet_to_bto.get(species)
            # In legacy single-source mode source_config is None → source_name=None
            # so clip filenames and DB rows are unchanged from the pre-multi-source format.
            _save_source_name = ctx.name if ctx.source_config is not None else None
            _executor.submit(
                _deferred_save,
                p.best_ts, species, p.best_confidence,
                p.best_begin_sample, p.best_fallback,
                bto_name, cfg.inference.model,
                ctx.capture_buffer, _save_source_name,
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

    # Build the seasonal presence filter.
    seasonal = SeasonalFilter(
        enabled   = cfg.seasonal_filter.enabled,
        json_path = cfg.seasonal_filter.filter_json,
    )
    if cfg.seasonal_filter.enabled:
        logger.info("Seasonal filter enabled — out-of-season detections will be suppressed")
    else:
        logger.info("Seasonal filter disabled")

    # Build the nocturnal/crepuscular time-of-day filter.
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

        # Build a BTO map for the secondary model so CV name-matching bridges
        # the label-namespace difference between BirdNET (IOC) and Perch (eBird).
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

        # Eagerly load the secondary model's TF graph now so the first live CV
        # call doesn't stall a deferred-save worker thread.  run_inference()
        # triggers _ensure_model() on first call; calling it here with a silent
        # dummy array moves that startup cost to before the classify loop begins.
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
        # Legacy single-source mode: one context, source_config=None.
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
    # All classify loops share one lock so inference is serialised across sources.
    # This avoids race conditions on the model's internal state while allowing
    # recording threads to continue filling their queues unimpeded.
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
