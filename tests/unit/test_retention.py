"""
tests/unit/test_retention.py — unit tests for retention.run_cleanup().

Strategy
--------
* Each test creates real .flac files with known mtimes inside a tmp dir.
* `retention.cfg` is monkeypatched so tests don't touch the real data/ tree.
* `retention._disk_usage_percent` is monkeypatched to return controlled values
  so the usage-based pass can be exercised independently of actual disk state.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

import pytest

import retention
from retention import run_cleanup
from config import RetentionConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_flac(dirpath: Path, name: str, age_days: float = 0.0) -> Path:
    """Create a dummy .flac file whose mtime is *age_days* in the past."""
    p = dirpath / name
    p.write_bytes(b"fLaC")
    if age_days:
        mtime = time.time() - age_days * 86400.0
        os.utime(p, (mtime, mtime))
    return p


def _retention_cfg(test_cfg, **kwargs) -> object:
    """Return a copy of test_cfg with RetentionConfig fields overridden."""
    base = dict(
        enabled=True,
        max_age_days=30,
        max_usage_percent=100.0,  # disable usage pass by default
        min_clips_per_species=0,
        run_interval_seconds=3600,
    )
    base.update(kwargs)
    new_ret = RetentionConfig(**base)
    return dataclasses.replace(test_cfg, retention=new_ret)


# ── Module-level patches ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_retention(monkeypatch, test_cfg):
    """Patch retention.cfg and disable the usage pass for all tests by default."""
    monkeypatch.setattr(retention, "cfg", test_cfg)
    # Default: usage never triggers (100 % threshold)
    monkeypatch.setattr(retention, "_disk_usage_percent", lambda _p: 0.0)


@pytest.fixture
def det_dir(test_cfg) -> Path:
    return test_cfg.paths.detections_dir


# ── Disabled ──────────────────────────────────────────────────────────────────

class TestDisabled:
    def test_returns_zero_when_disabled(self, monkeypatch, test_cfg, det_dir):
        cfg = _retention_cfg(test_cfg, enabled=False)
        monkeypatch.setattr(retention, "cfg", cfg)

        assert run_cleanup(det_dir) == 0

    def test_no_files_deleted_when_disabled(self, monkeypatch, test_cfg, det_dir):
        _make_flac(det_dir, "20200101_000000_robin.flac", age_days=1000)
        cfg = _retention_cfg(test_cfg, enabled=False)
        monkeypatch.setattr(retention, "cfg", cfg)

        run_cleanup(det_dir)

        assert list(det_dir.glob("*.flac")) != []


# ── Age-based pass ────────────────────────────────────────────────────────────

class TestAgeBased:
    def test_old_clip_deleted(self, monkeypatch, test_cfg, det_dir):
        """File older than max_age_days is removed."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=0)
        monkeypatch.setattr(retention, "cfg", cfg)

        old = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=31)

        assert run_cleanup(det_dir) == 1
        assert not old.exists()

    def test_recent_clip_kept(self, monkeypatch, test_cfg, det_dir):
        """File newer than max_age_days is left untouched."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=0)
        monkeypatch.setattr(retention, "cfg", cfg)

        recent = _make_flac(det_dir, "20260101_000000_robin.flac", age_days=5)

        assert run_cleanup(det_dir) == 0
        assert recent.exists()

    def test_max_age_zero_skips_age_pass(self, monkeypatch, test_cfg, det_dir):
        """max_age_days=0 disables age-based deletion entirely."""
        cfg = _retention_cfg(test_cfg, max_age_days=0, min_clips_per_species=0)
        monkeypatch.setattr(retention, "cfg", cfg)

        very_old = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=3000)

        assert run_cleanup(det_dir) == 0
        assert very_old.exists()

    def test_min_clips_protects_newest(self, monkeypatch, test_cfg, det_dir):
        """min_clips_per_species=2 keeps the 2 newest; the oldest old clip is deleted."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=2)
        monkeypatch.setattr(retention, "cfg", cfg)

        clip1 = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=33)
        clip2 = _make_flac(det_dir, "20200102_000000_robin.flac", age_days=32)
        clip3 = _make_flac(det_dir, "20200103_000000_robin.flac", age_days=31)

        assert run_cleanup(det_dir) == 1   # only clip1 deleted
        assert not clip1.exists()
        assert clip2.exists()
        assert clip3.exists()

    def test_min_clips_keeps_all_when_count_at_minimum(self, monkeypatch, test_cfg, det_dir):
        """If species has exactly min_clips_per_species old clips, nothing is deleted."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=3)
        monkeypatch.setattr(retention, "cfg", cfg)

        c1 = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=35)
        c2 = _make_flac(det_dir, "20200102_000000_robin.flac", age_days=34)
        c3 = _make_flac(det_dir, "20200103_000000_robin.flac", age_days=33)

        assert run_cleanup(det_dir) == 0
        assert c1.exists() and c2.exists() and c3.exists()

    def test_multiple_species_independent(self, monkeypatch, test_cfg, det_dir):
        """min_keep is applied independently per species."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=1)
        monkeypatch.setattr(retention, "cfg", cfg)

        robin_old = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=40)
        robin_new = _make_flac(det_dir, "20200201_000000_robin.flac", age_days=32)
        bbird_old = _make_flac(det_dir, "20200101_000000_blackbird.flac", age_days=40)
        bbird_new = _make_flac(det_dir, "20200201_000000_blackbird.flac", age_days=32)

        count = run_cleanup(det_dir)
        # Each species: 2 old clips, min_keep=1 → oldest deleted per species
        assert count == 2
        assert not robin_old.exists()
        assert robin_new.exists()
        assert not bbird_old.exists()
        assert bbird_new.exists()

    def test_non_flac_files_ignored(self, monkeypatch, test_cfg, det_dir):
        """Files without .flac suffix are not considered for deletion."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=0)
        monkeypatch.setattr(retention, "cfg", cfg)

        wav = det_dir / "20200101_000000_robin.wav"
        wav.write_bytes(b"RIFF")
        mtime = time.time() - 40 * 86400
        os.utime(wav, (mtime, mtime))

        assert run_cleanup(det_dir) == 0
        assert wav.exists()

    def test_malformed_filenames_skipped(self, monkeypatch, test_cfg, det_dir):
        """FLAC files whose stem has fewer than 3 underscore-parts are silently ignored."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=0)
        monkeypatch.setattr(retention, "cfg", cfg)

        bad = det_dir / "robin.flac"
        bad.write_bytes(b"fLaC")
        mtime = time.time() - 40 * 86400
        os.utime(bad, (mtime, mtime))

        assert run_cleanup(det_dir) == 0
        assert bad.exists()


# ── Usage-based pass ──────────────────────────────────────────────────────────

class TestUsageBased:
    def test_no_deletion_when_below_threshold(self, monkeypatch, test_cfg, det_dir):
        """Usage below max_usage_percent → pass 2 not triggered."""
        cfg = _retention_cfg(test_cfg, max_age_days=0, max_usage_percent=80.0)
        monkeypatch.setattr(retention, "cfg", cfg)
        monkeypatch.setattr(retention, "_disk_usage_percent", lambda _p: 50.0)

        clip = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=5)
        assert run_cleanup(det_dir) == 0
        assert clip.exists()

    def test_deletes_oldest_until_below_threshold(self, monkeypatch, test_cfg, det_dir):
        """Clips are deleted oldest-first until usage drops below threshold."""
        cfg = _retention_cfg(
            test_cfg, max_age_days=0, max_usage_percent=80.0, min_clips_per_species=0
        )
        monkeypatch.setattr(retention, "cfg", cfg)

        # Usage: 95% on first 2 calls (guard + pre-delete check), then 70%
        calls: list[float] = [95.0, 95.0, 70.0]

        def _mock_usage(_p: Path) -> float:
            return calls.pop(0) if calls else 70.0

        monkeypatch.setattr(retention, "_disk_usage_percent", _mock_usage)

        clip1 = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=5)
        clip2 = _make_flac(det_dir, "20200102_000000_robin.flac", age_days=3)

        deleted = run_cleanup(det_dir)
        assert deleted == 1
        assert not clip1.exists()   # oldest deleted
        assert clip2.exists()

    def test_usage_pass_respects_min_clips(self, monkeypatch, test_cfg, det_dir):
        """min_clips_per_species protects newest clips even under disk pressure."""
        cfg = _retention_cfg(
            test_cfg, max_age_days=0, max_usage_percent=80.0, min_clips_per_species=2
        )
        monkeypatch.setattr(retention, "cfg", cfg)
        monkeypatch.setattr(retention, "_disk_usage_percent", lambda _p: 95.0)

        _make_flac(det_dir, "20200101_000000_robin.flac", age_days=5)
        _make_flac(det_dir, "20200102_000000_robin.flac", age_days=3)

        # Both clips are in the protected set (min_keep=2) → nothing eligible
        assert run_cleanup(det_dir) == 0

    def test_usage_deletes_across_species(self, monkeypatch, test_cfg, det_dir):
        """Usage pass builds a flat candidate list across all species."""
        cfg = _retention_cfg(
            test_cfg, max_age_days=0, max_usage_percent=80.0, min_clips_per_species=0
        )
        monkeypatch.setattr(retention, "cfg", cfg)

        # Always 95% → keep deleting until candidates exhausted
        monkeypatch.setattr(retention, "_disk_usage_percent", lambda _p: 95.0)

        _make_flac(det_dir, "20200101_000000_robin.flac", age_days=10)
        _make_flac(det_dir, "20200101_000000_blackbird.flac", age_days=8)

        deleted = run_cleanup(det_dir)
        assert deleted == 2


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_nonexistent_dir_returns_zero(self, test_cfg):
        """A detections_dir that doesn't exist returns 0 without raising."""
        assert run_cleanup(Path("/tmp/no_such_bird_dir_xyz_abc")) == 0

    def test_empty_dir_returns_zero(self, test_cfg, det_dir):
        """An empty detections_dir returns 0."""
        assert run_cleanup(det_dir) == 0

    def test_default_dir_uses_cfg_paths(self, monkeypatch, test_cfg, det_dir):
        """Calling run_cleanup() with no arg uses cfg.paths.detections_dir."""
        cfg = _retention_cfg(test_cfg, max_age_days=30, min_clips_per_species=0)
        monkeypatch.setattr(retention, "cfg", cfg)

        old = _make_flac(det_dir, "20200101_000000_robin.flac", age_days=35)

        result = run_cleanup()   # no argument — falls back to cfg.paths.detections_dir
        assert result == 1
        assert not old.exists()
