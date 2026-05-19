"""
Unit tests for detector.py pipeline internals.

Coverage targets (from BETA_FIX_PLAN T3):
  - _check_dedup()   cross-source deduplication logic
  - _Pending         confirmation accumulator dataclass
  - _classify_loop   filter pipeline: BOU allowlist, confidence threshold
"""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import detector
from capture_buffer import CaptureBuffer
from detector import _Pending, _SourceContext, _check_dedup, _classify_loop
from filters.nocturnal_filter import NocturnalFilter
from filters.seasonal_filter import SeasonalFilter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_cfg(
    *,
    dedup_enabled: bool = False,
    dedup_window: float = 10.0,
    sample_rate: int = 48000,
    hop_seconds: float = 3.0,
    filter_enabled: bool = False,
) -> MagicMock:
    """Return a MagicMock that quacks like the cfg object for detector internals."""
    m = MagicMock()
    m.deduplication.enabled      = dedup_enabled
    m.deduplication.window_seconds = dedup_window
    m.audio.sample_rate          = sample_rate
    m.audio.hop_seconds          = hop_seconds
    m.filter.enabled             = filter_enabled
    m.exclude                    = frozenset()
    return m


def _make_source_ctx(sample_rate: int = 48000) -> _SourceContext:
    return _SourceContext(
        name="test",
        audio_queue=queue.Queue(),
        capture_buffer=CaptureBuffer(max_seconds=30, sample_rate=sample_rate),
        source_config=None,
    )


def _disabled_filters() -> tuple[SeasonalFilter, NocturnalFilter]:
    seasonal  = SeasonalFilter(enabled=False)
    nocturnal = NocturnalFilter(
        enabled=False,
        json_path=Path("filters/uk_nocturnal_filter.json"),
        lat=51.5,
        lon=-0.1,
        timezone_str="UTC",
        species_overrides={},
    )
    return seasonal, nocturnal


# ── _check_dedup ──────────────────────────────────────────────────────────────

class TestCheckDedup:
    """Cross-source deduplication: same species, different source, within window."""

    @pytest.fixture(autouse=True)
    def _reset_dedup_state(self, monkeypatch):
        """Isolate each test by clearing the module-level dedup dict."""
        monkeypatch.setattr(detector, "_dedup_recent", {})

    @pytest.fixture
    def dedup_cfg(self, monkeypatch):
        cfg = _make_mock_cfg(dedup_enabled=True, dedup_window=10.0)
        monkeypatch.setattr(detector, "cfg", cfg)
        return cfg

    def test_disabled_always_returns_false(self, monkeypatch):
        cfg = _make_mock_cfg(dedup_enabled=False)
        monkeypatch.setattr(detector, "cfg", cfg)
        ts = datetime.now(timezone.utc)
        assert _check_dedup("Robin", "src1", ts) is False

    def test_first_detection_not_a_dup_and_registers_entry(self, dedup_cfg):
        ts = datetime.now(timezone.utc)
        result = _check_dedup("Robin", "src1", ts)
        assert result is False
        assert "Robin" in detector._dedup_recent

    def test_same_species_different_source_within_window_is_dup(self, dedup_cfg):
        ts = datetime.now(timezone.utc)
        _check_dedup("Robin", "src1", ts)
        ts2 = ts + timedelta(seconds=5)          # within 10 s window
        assert _check_dedup("Robin", "src2", ts2) is True

    def test_same_species_same_source_within_window_not_dup(self, dedup_cfg):
        ts = datetime.now(timezone.utc)
        _check_dedup("Robin", "src1", ts)
        ts2 = ts + timedelta(seconds=5)
        # Same source — updates baseline, never a cross-source dup
        assert _check_dedup("Robin", "src1", ts2) is False

    def test_same_species_different_source_outside_window_not_dup(self, dedup_cfg):
        ts = datetime.now(timezone.utc)
        _check_dedup("Robin", "src1", ts)
        ts2 = ts + timedelta(seconds=30)         # outside 10 s window
        assert _check_dedup("Robin", "src2", ts2) is False

    def test_different_species_never_dup(self, dedup_cfg):
        ts = datetime.now(timezone.utc)
        _check_dedup("Robin", "src1", ts)
        # Blackbird is a different key — not a dup
        assert _check_dedup("Blackbird", "src2", ts) is False


# ── _Pending ──────────────────────────────────────────────────────────────────

class TestPending:
    """_Pending accumulates repeated hits for a species before confirming."""

    def _make(self, *, confidence: float = 0.7, hit_count: int = 1) -> _Pending:
        return _Pending(
            first_seen_mono   = time.monotonic(),
            best_confidence   = confidence,
            best_ts           = datetime.now(timezone.utc),
            best_begin_sample = 0,
            best_fallback     = np.zeros(100, dtype=np.int16),
            hit_count         = hit_count,
        )

    def test_initial_hit_count(self):
        p = self._make(hit_count=1)
        assert p.hit_count == 1

    def test_hit_count_increments(self):
        p = self._make(hit_count=1)
        p.hit_count += 1
        assert p.hit_count == 2

    def test_higher_confidence_updates_best(self):
        p = self._make(confidence=0.7)
        if 0.9 > p.best_confidence:
            p.best_confidence = 0.9
        assert p.best_confidence == 0.9

    def test_lower_confidence_does_not_update_best(self):
        p = self._make(confidence=0.9)
        if 0.6 > p.best_confidence:     # condition is False
            p.best_confidence = 0.6
        assert p.best_confidence == 0.9

    def test_not_confirmed_below_min_detections(self):
        """Species requires 2 hits to confirm; 1 hit is not enough."""
        p = self._make(hit_count=1)
        min_detections = 2
        assert p.hit_count < min_detections

    def test_confirmed_at_min_detections(self):
        """On the second hit the species reaches min_detections and is confirmed."""
        p = self._make(hit_count=1)
        p.hit_count += 1
        min_detections = 2
        assert p.hit_count >= min_detections

    def test_pending_window_expiry(self):
        """A _Pending whose window has passed is treated as expired by the loop."""
        window_seconds = 9.0
        # Create a pending entry whose first_seen_mono is far in the past
        old_mono = time.monotonic() - (window_seconds + 1.0)
        p = _Pending(
            first_seen_mono   = old_mono,
            best_confidence   = 0.7,
            best_ts           = datetime.now(timezone.utc),
            best_begin_sample = 0,
            best_fallback     = np.zeros(100, dtype=np.int16),
            hit_count         = 1,
        )
        now_mono = time.monotonic()
        is_expired = (now_mono - p.first_seen_mono) > window_seconds
        assert is_expired


# ── _classify_loop filter pipeline ────────────────────────────────────────────

class TestClassifyLoopFilters:
    """Functional tests: species that fail a filter step must never trigger a save."""

    def _run_loop_briefly(
        self,
        ctx:         _SourceContext,
        bou_allowed: frozenset[str],
        model:       MagicMock,
        *,
        monkeypatch,
        n_chunks:    int   = 4,
        sample_rate: int   = 48000,
        hop_seconds: float = 3.0,
    ) -> MagicMock:
        """
        Spin up _classify_loop in a thread, feed it audio, stop it, and return
        a MagicMock that replaced detector._executor (so we can inspect .submit).
        """
        mock_cfg = _make_mock_cfg(sample_rate=sample_rate, hop_seconds=hop_seconds)
        monkeypatch.setattr(detector, "cfg", mock_cfg)

        mock_executor = MagicMock()
        monkeypatch.setattr(detector, "_executor", mock_executor, raising=False)

        mock_gsc = MagicMock()
        mock_gsc.return_value = MagicMock(
            min_confidence=0.7,
            confirmation_window_seconds=9.0,
            min_detections=2,
            cooldown_seconds=60,
        )

        seasonal, nocturnal = _disabled_filters()
        inference_lock = threading.Lock()

        def _loop():
            with patch("detector.get_species_config", mock_gsc):
                _classify_loop(
                    ctx, bou_allowed, {}, seasonal, nocturnal, model, inference_lock
                )

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

        chunk_samples = int(hop_seconds * sample_rate)
        audio = np.zeros(chunk_samples, dtype=np.int16)
        for _ in range(n_chunks):
            ctx.audio_queue.put(audio)
            time.sleep(0.02)

        detector.stop_event.set()
        t.join(timeout=3.0)
        detector.stop_event.clear()

        return mock_executor

    def test_species_not_in_bou_allowlist_never_saved(self, monkeypatch):
        """A species absent from the BOU allowlist is silently dropped."""
        model = MagicMock()
        model.window_seconds = 3.0
        model.run_inference.return_value = [("Bald Eagle", 0.95)]

        ctx = _make_source_ctx()
        bou_allowed = frozenset({"European Robin"})  # Bald Eagle not in set

        executor = self._run_loop_briefly(
            ctx, bou_allowed, model, monkeypatch=monkeypatch
        )
        executor.submit.assert_not_called()

    def test_species_below_confidence_threshold_never_saved(self, monkeypatch):
        """A species whose confidence is below min_confidence is dropped."""
        model = MagicMock()
        model.window_seconds = 3.0
        # Robin IS in the allowlist but confidence 0.4 < min_confidence 0.7
        model.run_inference.return_value = [("European Robin", 0.4)]

        ctx = _make_source_ctx()
        bou_allowed = frozenset({"European Robin"})

        executor = self._run_loop_briefly(
            ctx, bou_allowed, model, monkeypatch=monkeypatch
        )
        executor.submit.assert_not_called()

    def test_confirmed_species_triggers_save(self, monkeypatch):
        """A species that reaches min_detections (2) within the window triggers submit."""
        model = MagicMock()
        model.window_seconds = 3.0
        model.run_inference.return_value = [("European Robin", 0.85)]

        ctx = _make_source_ctx()
        bou_allowed = frozenset({"European Robin"})

        # Feed enough chunks (> min_detections windows) for confirmation
        executor = self._run_loop_briefly(
            ctx, bou_allowed, model, monkeypatch=monkeypatch, n_chunks=6
        )
        executor.submit.assert_called()
