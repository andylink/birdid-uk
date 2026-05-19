"""
retention.py — automatic cleanup of old audio clips and spectrograms.

Two cleanup passes run for audio clips, in order:
  1. Age pass   — delete clips older than max_age_days, but always keep the
                   min_clips_per_species newest clips for each species.
  2. Usage pass — if disk usage still exceeds max_usage_percent, delete the
                   oldest clips globally (still honouring per-species minimums)
                   until usage drops below the threshold.

A third pass prunes spectrograms independently:
  3. Spectrogram age pass — delete PNG files in the spectrograms directory
                             that are older than spectrogram_max_age_days.
                             Spectrograms are intentionally kept much longer
                             than audio clips so the dashboard can display them
                             after the source clip has been removed.

All passes are skipped when enabled = false in the [retention] config section.
start_retention_thread() runs cleanup on startup and then every
run_interval_seconds seconds.

Clip filename convention (produced by audio.save_clip):
    YYYYMMDD_HHMMSS_<safe_species>.flac

The species key is extracted by splitting on '_' at most twice and taking the
third part. This groups clips by species without needing to reverse audio.safe_name.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import cfg

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _clips_by_species(detections_dir: Path) -> dict[str, list[Path]]:
    """Group all .flac clips in detections_dir by species key, sorted oldest first.

    Files that don't match the expected YYYYMMDD_HHMMSS_<species>.flac naming
    pattern are silently skipped.
    """
    groups: dict[str, list[Path]] = {}
    for p in detections_dir.glob("*.flac"):
        parts = p.stem.split("_", 2)
        if len(parts) < 3:
            continue
        species_key = parts[2]
        groups.setdefault(species_key, []).append(p)

    for clips in groups.values():
        clips.sort(key=lambda p: p.stat().st_mtime)

    return groups


def _disk_usage_percent(path: Path) -> float:
    """Return current disk usage % for the volume containing path."""
    usage = shutil.disk_usage(path)
    return usage.used / usage.total * 100.0


def _protected_set(clips: list[Path], min_keep: int) -> set[Path]:
    """Return the min_keep newest clips for a species — these must not be deleted."""
    if min_keep <= 0:
        return set()
    return set(clips[-min_keep:])


# ── Public API ────────────────────────────────────────────────────────────────

def run_spectrogram_cleanup(spectrograms_dir: Path | None = None) -> int:
    """Delete spectrogram PNGs older than cfg.retention.spectrogram_max_age_days.

    Uses cfg.paths.spectrograms_dir if spectrograms_dir is not provided.
    Returns the number of files deleted.
    """
    rc = cfg.retention
    if not rc.enabled or rc.spectrogram_max_age_days <= 0:
        return 0

    if spectrograms_dir is None:
        spectrograms_dir = cfg.paths.spectrograms_dir

    if not spectrograms_dir.is_dir():
        return 0

    age_cutoff = datetime.now() - timedelta(days=rc.spectrogram_max_age_days)
    deleted = 0

    for png in spectrograms_dir.glob("*.png"):
        try:
            mtime = datetime.fromtimestamp(png.stat().st_mtime)
        except FileNotFoundError:
            continue
        if mtime < age_cutoff:
            png.unlink(missing_ok=True)
            deleted += 1

    if deleted:
        logger.info("[retention] deleted %d spectrogram(s)", deleted)

    return deleted


def run_cleanup(detections_dir: Path | None = None) -> int:
    """Apply the retention policy and delete clips that exceed the configured limits.

    Uses cfg.paths.detections_dir if detections_dir is not provided.
    Returns the total number of clips deleted.
    """
    rc = cfg.retention
    if not rc.enabled:
        return 0

    if detections_dir is None:
        detections_dir = cfg.paths.detections_dir

    if not detections_dir.is_dir():
        return 0

    deleted = 0
    min_keep = rc.min_clips_per_species

    # ── Pass 1: delete clips older than max_age_days ──────────────────────────
    if rc.max_age_days > 0:
        age_cutoff = datetime.now() - timedelta(days=rc.max_age_days)
        groups = _clips_by_species(detections_dir)

        for clips in groups.values():
            protected = _protected_set(clips, min_keep)
            for clip in clips:
                if clip in protected:
                    continue
                try:
                    mtime = datetime.fromtimestamp(clip.stat().st_mtime)
                except FileNotFoundError:
                    continue
                if mtime < age_cutoff:
                    clip.unlink(missing_ok=True)
                    deleted += 1

    # ── Pass 2: delete oldest clips until disk usage is within the limit ──────
    if _disk_usage_percent(detections_dir) > rc.max_usage_percent:
        # Re-scan so we don't try to delete files already removed in pass 1.
        groups = _clips_by_species(detections_dir)

        # Build a flat list of deletable clips sorted oldest-first.
        candidates: list[tuple[float, Path]] = []
        for clips in groups.values():
            protected = _protected_set(clips, min_keep)
            for clip in clips:
                if clip not in protected:
                    try:
                        candidates.append((clip.stat().st_mtime, clip))
                    except FileNotFoundError:
                        pass
        candidates.sort()

        for _, clip in candidates:
            if _disk_usage_percent(detections_dir) <= rc.max_usage_percent:
                break
            clip.unlink(missing_ok=True)
            deleted += 1

    if deleted:
        logger.info("[retention] deleted %d clip(s)", deleted)

    # ── Pass 3: prune old spectrogram PNGs ────────────────────────────────────
    run_spectrogram_cleanup()

    return deleted


def start_retention_thread() -> threading.Thread:
    """Start a background thread that runs clip cleanup on a repeating schedule.

    Runs immediately on startup, then repeats every
    cfg.retention.run_interval_seconds seconds.
    """
    def _loop() -> None:
        run_cleanup()
        while True:
            time.sleep(cfg.retention.run_interval_seconds)
            run_cleanup()

    t = threading.Thread(target=_loop, name="retention", daemon=True)
    t.start()
    return t
