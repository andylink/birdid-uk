"""
detector.py — microphone recording thread, classify loop, and main entry.

Per-species configuration (min_confidence, cooldown_seconds) is looked up for
every detection via ``get_species_config`` so each species can have its own
thresholds.

Dual-buffer design
------------------
The recording thread feeds two consumers in parallel:

  * ``audio_queue`` — used by :func:`_classify_loop` to maintain a sliding
    analysis window (length determined by the active inference model) that is
    passed to the classifier.
  * ``_capture_buffer`` — a large ring buffer (default 30 s) that records
    audio continuously.  When a detection fires, a *deferred save task* is
    submitted to ``_executor``; it sleeps for ``post_capture_seconds`` (so
    the full post-detection audio is captured), then reads the complete clip
    segment from the ring buffer and persists it to disk.

The benefit: saved clips are longer than the analysis window (default 15 s),
exactly mirroring BirdNET-Go's CaptureBuffer behaviour.

Inference model
---------------
The active model is selected by ``cfg.inference.model`` in ``config.toml``.
``_classify_loop`` queries ``model.window_seconds`` at startup so the rolling
buffer automatically resizes to suit the model (3 s for BirdNET, 5 s for
Perch v2).  Audio is always recorded at ``cfg.audio.sample_rate``; any
resampling needed by the model happens inside the model's
``run_inference`` method.

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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd

from audio import apply_highpass, save_clip
import birdmap
from bou_filter import build_bou_allowed_set, build_birdnet_to_bto_map
from capture_buffer import CaptureBuffer
from config import cfg, get_species_config
from cross_validate import CrossValidationResult, CrossValidator
from database import init_db, record_detection, seed_species_info
from inference import Inferencer, get_model, get_secondary_model, get_secondary_model_name
from log_setup import setup_logging
from mqtt import init_mqtt, publish_detection
from retention import start_retention_thread
from nocturnal_filter import NocturnalFilter
from seasonal_filter import SeasonalFilter, current_iso_week

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────

audio_queue:     queue.Queue         = queue.Queue()
stop_event:      threading.Event     = threading.Event()
_last_detected:  dict[str, datetime] = {}   # species → time of last saved detection

# Initialised in main() after config is loaded.
_capture_buffer:  CaptureBuffer
_executor:        ThreadPoolExecutor
_cross_validator: CrossValidator | None = None   # None when CV is disabled


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


# Keyed by BirdNET common name.  Accessed only from _classify_loop (single
# thread), so no locking is required.
_pending: dict[str, _Pending] = {}


# ── Deferred save ─────────────────────────────────────────────────────────────

def _deferred_save(
    ts:             datetime,
    species:        str,
    conf:           float,
    begin_sample:   int,
    fallback_audio: np.ndarray,
    bto_name:       str | None,
    model_name:     str,
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
        segment = _capture_buffer.read_segment(begin_sample - pre_samples, clip_samples)
        if segment is not None:
            break
        time.sleep(0.1)

    if segment is None:
        logger.warning(
            "capture buffer miss for %s at sample %d "
            "(clip_mode=%s, pre=%d samples); "
            "saving fallback clip (one analysis window)",
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

    # ── Persist ───────────────────────────────────────────────────────────────
    clip_path = save_clip(segment, ts, species)

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

    record_detection(
        ts, species, effective_conf, clip_path, [],
        bto_name, model_name,
        **cv_kwargs,
    )
    publish_detection(ts, species, effective_conf, clip_path, [])
    birdmap.post_detection(ts, species, effective_conf, clip_path)


# ── Threads ───────────────────────────────────────────────────────────────────

def _record_thread() -> None:
    """Continuously record hop-length chunks onto the audio queue and into
    the capture buffer."""
    hop_samples = cfg.audio.sample_rate * cfg.audio.hop_seconds
    while not stop_event.is_set():
        try:
            chunk = sd.rec(
                hop_samples,
                samplerate=cfg.audio.sample_rate,
                channels=1,
                dtype="int16",
                device=cfg.audio.device,
            )
            sd.wait()
        except Exception:
            logger.exception("audio recording error — retrying in 1 s")
            time.sleep(1.0)
            continue
        flat = chunk.flatten()
        _capture_buffer.write(flat)   # continuous ring — always recording
        audio_queue.put(flat)         # 3-second sliding window for inference


def _classify_loop(
    bou_allowed:    frozenset[str],
    birdnet_to_bto: dict[str, str],
    seasonal:       SeasonalFilter,
    nocturnal:      NocturnalFilter,
    model:          Inferencer,
) -> None:
    """
    Consume audio chunks, maintain a rolling window, run inference, and
    apply per-species confidence thresholds, confirmation filter, and cooldowns.

    For each window:
      1. Apply high-pass filter to a copy of the audio if enabled in config
         (the original array is kept untouched for clip saving).
      2. Run inference — returns detections above a raw floor (BirdNET: 0.01
         via analyze(); Perch: 0.01 applied in run_inference()).
      3. Drop any species on the global exclude list.
      4. Filter each detection by its per-species ``min_confidence``.
         This runs before BOU/seasonal so low-confidence hits never appear
         in the filter-suppressed log lines.
      4b. BOU allowlist filter: drop species not in the UK BOU species list.
      4c. Seasonal filter: drop species outside their expected season.
      4d. Nocturnal filter: drop nocturnal/crepuscular species detected outside
          their active time window (configurable per-species).
      5. Confirmation filter: each species accumulates hits in ``_pending``
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

    while not stop_event.is_set():
        try:
            chunk = audio_queue.get(timeout=1.0)
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
            candidates = model.run_inference(inference_audio)
        except Exception:
            logger.exception("inference error on window %d — skipping", _window_count)
            continue

        ts = datetime.now(timezone.utc)

        # ── Heartbeat: log every 60 windows (~60 s) so the loop is visible ────
        if _window_count % 60 == 0:
            if candidates:
                top_s, top_c = candidates[0]
                logger.info(
                    "[heartbeat] window=%d  top: %s %.3f",
                    _window_count, top_s, top_c,
                )
            else:
                logger.info("[heartbeat] window=%d  no candidates", _window_count)

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
        begin_sample = _capture_buffer.total_written - window_samples

        for species, conf in candidates:
            sc = get_species_config(species)
            logger.info("%-32s %.2f", species, conf)

            p = _pending.get(species)

            # Discard stale pending state if the confirmation window expired.
            if p is not None and now_mono - p.first_seen_mono > sc.confirmation_window_seconds:
                logger.debug(
                    "%-32s confirmation window expired (%d/%d hits)",
                    species, p.hit_count, sc.min_detections,
                )
                del _pending[species]
                p = None

            if p is None:
                # First hit — open a new pending window.
                _pending[species] = _Pending(
                    first_seen_mono   = now_mono,
                    best_confidence   = conf,
                    best_ts           = ts,
                    best_begin_sample = begin_sample,
                    best_fallback     = audio.copy(),
                    hit_count         = 1,
                )
                p = _pending[species]
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
            last_saved  = _last_detected.get(species, datetime.min.replace(tzinfo=timezone.utc))
            if ts - last_saved < cooldown_td:
                logger.debug("%-32s confirmed but in cooldown", species)
                del _pending[species]
                continue

            # Accept: record cooldown start and submit the deferred save.
            logger.info(
                "%-32s CONFIRMED (%d hits, best=%.2f)",
                species, p.hit_count, p.best_confidence,
            )
            _last_detected[species] = ts
            bto_name = birdnet_to_bto.get(species)
            _executor.submit(
                _deferred_save,
                p.best_ts, species, p.best_confidence,
                p.best_begin_sample, p.best_fallback,
                bto_name, cfg.inference.model,
            )
            del _pending[species]


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
    bou_allowed    = build_bou_allowed_set(label_map, exclude_status=cfg.bou_filter.exclude_status, force_include=_bou_force)
    birdnet_to_bto = build_birdnet_to_bto_map(label_map, exclude_status=cfg.bou_filter.exclude_status, force_include=_bou_force)
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
        secondary_bto_map = build_birdnet_to_bto_map(secondary_label_map, exclude_status=cfg.bou_filter.exclude_status, force_include=_bou_force)

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

    init_db()
    seed_species_info(Path(__file__).parent / "species_bto_FINAL_filtered.json")
    init_mqtt()

    start_retention_thread()

    # Initialise shared dual-buffer state.
    global _capture_buffer, _executor
    _capture_buffer = CaptureBuffer(
        max_seconds = cfg.audio.capture_buffer_seconds,
        sample_rate = cfg.audio.sample_rate,
    )
    _executor = ThreadPoolExecutor(
        max_workers       = 4,
        thread_name_prefix = "clip_saver",
    )
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

    rec = threading.Thread(target=_record_thread, daemon=True)
    rec.start()

    try:
        _classify_loop(bou_allowed, birdnet_to_bto, seasonal, nocturnal, model)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        _executor.shutdown(wait=True)

