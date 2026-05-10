"""
retention.py — clip retention and disk cleanup for data/detections/.

Policy (applied in two passes):
  1. Age pass   — delete clips older than ``max_age_days``, but always keep the
                  ``min_clips_per_species`` newest clips for each species.
  2. Usage pass — if disk usage still exceeds ``max_usage_percent``, delete the
                  globally oldest clips (still honouring per-species minimums)
                  until usage falls below the threshold.

Both passes are skipped when ``enabled = false`` in the ``[retention]`` config
section.  The thread started by ``start_retention_thread()`` runs the policy on
startup and then every ``run_interval_seconds`` seconds.

Filename convention (produced by audio.save_clip):
    YYYYMMDD_HHMMSS_<safe_species>.flac

The species key is extracted by splitting on ``_`` at most twice, taking the
third part.  This groups clips by species without needing to reverse
``audio.safe_name``.
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
    """
    Return ``{species_key: [path, ...]}`` for every ``*.flac`` in
    *detections_dir*, sorted oldest-first within each species group.

    Files whose names don't match the expected ``YYYYMMDD_HHMMSS_<species>.flac``
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
    """Return current disk usage % for the volume containing *path*."""
    usage = shutil.disk_usage(path)
    return usage.used / usage.total * 100.0


def _protected_set(clips: list[Path], min_keep: int) -> set[Path]:
    """Return the set of *min_keep* newest clips that must not be deleted."""
    if min_keep <= 0:
        return set()
    return set(clips[-min_keep:])


# ── Public API ────────────────────────────────────────────────────────────────

def run_cleanup(detections_dir: Path | None = None) -> int:
    """
    Apply the retention policy to *detections_dir* (defaults to
    ``cfg.paths.detections_dir``).

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

    # ── Pass 1: age-based deletion ────────────────────────────────────────────
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

    # ── Pass 2: disk-usage-based deletion ────────────────────────────────────
    if _disk_usage_percent(detections_dir) > rc.max_usage_percent:
        # Re-scan so we don't try to delete already-removed files.
        groups = _clips_by_species(detections_dir)

        # Flat list of deletable clips sorted oldest-first.
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

    return deleted


def start_retention_thread() -> threading.Thread:
    """
    Start and return a daemon thread that runs ``run_cleanup()`` immediately on
    startup, then repeats every ``cfg.retention.run_interval_seconds`` seconds.
    """
    def _loop() -> None:
        run_cleanup()
        while True:
            time.sleep(cfg.retention.run_interval_seconds)
            run_cleanup()

    t = threading.Thread(target=_loop, name="retention", daemon=True)
    t.start()
    return t
