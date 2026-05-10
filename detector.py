"""
detector.py — microphone recording thread, classify loop, and main entry.

Per-species configuration (min_confidence, cooldown_seconds) is looked up for
every detection via ``get_species_config`` so each species can have its own
thresholds.

Dual-buffer design
------------------
The recording thread feeds two consumers in parallel:

  * ``audio_queue`` — used by :func:`_classify_loop` to maintain the 3-second
    sliding analysis window that is passed to the BirdNET classifier.
  * ``_capture_buffer`` — a large ring buffer (default 30 s) that records
    audio continuously.  When a detection fires, a *deferred save task* is
    submitted to ``_executor``; it sleeps for ``post_capture_seconds`` (so
    the full post-detection audio is captured), then reads the complete clip
    segment from the ring buffer and persists it to disk.

The benefit: saved clips are longer than the 3-second analysis window
(default 15 s), exactly mirroring BirdNET-Go's CaptureBuffer behaviour.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd

from audio import apply_highpass, save_clip
import birdmap
from bou_filter import build_bou_allowed_set, build_birdnet_to_bto_map
from capture_buffer import CaptureBuffer
from config import cfg, get_species_config
from database import init_db, record_detection, seed_species_info
from inference import load_label_map, run_inference
from log_setup import setup_logging
from mqtt import init_mqtt, publish_detection
from retention import start_retention_thread

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────

audio_queue:     queue.Queue         = queue.Queue()
stop_event:      threading.Event     = threading.Event()
_last_detected:  dict[str, datetime] = {}   # species → time of last saved detection

# Initialised in main() after config is loaded.
_capture_buffer: CaptureBuffer
_executor:       ThreadPoolExecutor


# ── Deferred save ─────────────────────────────────────────────────────────────

def _deferred_save(
    ts:             datetime,
    top_species:    str,
    top_conf:       float,
    new_detections: list[tuple[str, float]],
    begin_sample:   int,
    fallback_audio: np.ndarray,
    label_map:      dict[str, str],
    birdnet_to_bto: dict[str, str],
) -> None:
    """Sleep for the post-capture period, read the full clip, then persist.

    Runs on a worker thread from ``_executor``.  All downstream writes
    (clip file, database row, MQTT publish, Birdmap POST) happen here so
    that the classify loop is never blocked waiting for I/O.

    If the ring buffer read fails (e.g. the segment was overwritten because
    the executor backlog was unusually deep), the function falls back to
    saving the 3-second analysis window that was captured at detection time.

    Args:
        ts:             Wall-clock timestamp of the detection.
        top_species:    Highest-confidence non-cooldown species.
        top_conf:       Confidence of *top_species*.
        new_detections: All non-cooldown (species, conf) pairs from this window.
        begin_sample:   Absolute sample index where the analysis window started
                        (= ``_capture_buffer.total_written - window_samples`` at
                        detection time).
        fallback_audio: The 3-second raw PCM array; used if the ring read fails.
        label_map:      Classifier label map (not needed here, passed through
                        for symmetry; pending clips are saved synchronously).
        birdnet_to_bto: Mapping of BirdNET common name → BTO British name,
                        used to populate ``bto_name`` on the detection row.
    """
    post_capture = cfg.audio.post_capture_seconds
    if post_capture > 0:
        time.sleep(post_capture)

    pre_samples  = cfg.audio.pre_capture_seconds * cfg.audio.sample_rate
    clip_samples = cfg.audio.clip_seconds        * cfg.audio.sample_rate

    # The recording thread writes in 1-second chunks, so after sleeping exactly
    # post_capture_seconds the final samples may not have been committed yet.
    # Retry up to 10 times (≤1 s total) before falling back to the 3-second clip.
    segment: np.ndarray | None = None
    for _attempt in range(10):
        segment = _capture_buffer.read_segment(begin_sample - pre_samples, clip_samples)
        if segment is not None:
            break
        time.sleep(0.1)

    if segment is None:
        logger.warning(
            "capture buffer miss for %s at sample %d (post_capture=%ds); "
            "saving 3-second fallback clip",
            top_species, begin_sample, post_capture,
        )
        segment = fallback_audio

    clip_path = save_clip(segment, ts, top_species)
    bto_name  = birdnet_to_bto.get(top_species)
    record_detection(ts, top_species, top_conf, clip_path, new_detections[1:], bto_name)
    publish_detection(ts, top_species, top_conf, clip_path, new_detections[1:])
    birdmap.post_detection(ts, top_species, top_conf, clip_path)


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
    label_map:      dict[str, str],
    bou_allowed:    frozenset[str] | None,
    birdnet_to_bto: dict[str, str],
) -> None:
    """
    Consume audio chunks, maintain a rolling window, run inference, and
    apply per-species confidence thresholds and cooldowns.

    For each window:
      1. Apply high-pass filter to a copy of the audio if enabled in config
         (the original array is kept untouched for clip saving).
      2. Run inference — returns all detections above a raw 0.01 floor.
      3. Drop any species on the global exclude list.
      3b. If the BOU filter is enabled, drop species not in the BOU allowlist.
      4. Filter each detection by its per-species ``min_confidence``.
      5. Cap the candidate list at the global ``top_n`` setting.
      6. Skip detections still within their per-species ``cooldown_seconds``.
      7. Submit a deferred-save task for the first (highest-confidence)
         non-cooldown detection; the task sleeps for ``post_capture_seconds``
         before reading the full clip from the capture buffer.
    """
    buffer: list[np.ndarray] = []
    window_blocks  = cfg.audio.window_seconds // cfg.audio.hop_seconds
    window_samples = cfg.audio.window_seconds  * cfg.audio.sample_rate
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
            candidates = run_inference(inference_audio)
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

        # ── Step 3b: BOU allowlist filter ─────────────────────────────────────
        if bou_allowed is not None:
            candidates = [
                (species, conf)
                for species, conf in candidates
                if species in bou_allowed
            ]

        if not candidates:
            continue

        # ── Step 4: per-species confidence filter ─────────────────────────────
        passing = [
            (species, conf)
            for species, conf in candidates
            if conf >= get_species_config(species).min_confidence
        ]

        if not passing:
            continue

        # ── Step 5: cap to global top_n ───────────────────────────────────────
        passing = passing[: cfg.defaults.top_n]

        # ── Steps 6 & 7: cooldown check + deferred save ───────────────────────
        new_detections: list[tuple[str, float]] = []
        for species, conf in passing:
            sc        = get_species_config(species)
            cooldown  = timedelta(seconds=sc.cooldown_seconds)
            in_cooldown = (
                ts - _last_detected.get(species, datetime.min.replace(tzinfo=timezone.utc)) < cooldown
            )
            tag = "  [cooldown]" if in_cooldown else ""
            logger.info("%-32s %.2f%s", species, conf, tag)
            if not in_cooldown:
                new_detections.append((species, conf))

        if not new_detections:
            continue

        # Mark all non-cooldown species as detected now (before the deferred
        # save fires) so the cooldown clock starts immediately.
        for species, _ in new_detections:
            _last_detected[species] = ts

        # Submit deferred save for the highest-confidence detection.
        # begin_sample points to where the analysis window started in the ring.
        top_species, top_conf = new_detections[0]
        begin_sample = _capture_buffer.total_written - window_samples
        _executor.submit(
            _deferred_save,
            ts, top_species, top_conf, new_detections,
            begin_sample, audio.copy(),  # copy: buffer list may mutate next hop
            label_map, birdnet_to_bto,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    setup_logging()

    label_map = load_label_map()

    # Build the BOU allowed set and BirdNET→BTO name map if the filter is enabled.
    bou_allowed:    frozenset[str] | None = None
    birdnet_to_bto: dict[str, str]        = {}
    if cfg.bou_filter.enabled:
        bou_allowed    = build_bou_allowed_set(label_map)
        birdnet_to_bto = build_birdnet_to_bto_map(label_map)
        logger.info("BOU filter enabled — non-BOU detections will be suppressed")
    else:
        logger.info("BOU filter disabled")

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
    logger.info(
        "Capture buffer: %d s ring  |  clip: %d s  (pre=%d s, post=%d s)",
        cfg.audio.capture_buffer_seconds,
        cfg.audio.clip_seconds,
        cfg.audio.pre_capture_seconds,
        cfg.audio.post_capture_seconds,
    )

    rec = threading.Thread(target=_record_thread, daemon=True)
    rec.start()

    try:
        _classify_loop(label_map, bou_allowed, birdnet_to_bto)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        _executor.shutdown(wait=True)
