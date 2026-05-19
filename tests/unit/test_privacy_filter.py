"""
Unit tests for filters/privacy_filter.py.

PrivacyFilter.scan() is on the critical save path and has zero coverage.

The silero-vad and torch imports inside scan() are intercepted via
sys.modules patching (monkeypatch.setitem) so these tests run without a
real VAD model and without GPU/CPU inference overhead.

Coverage:
  - voiced fraction >= min_voiced_fraction  → True  (clip dropped)
  - voiced fraction <  min_voiced_fraction  → False (clip kept)
  - zero voiced segments                   → False (clip kept)
  - filter disabled: enabled property is False
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from config import PrivacyFilterConfig
from filters.privacy_filter import PrivacyFilter, _SILERO_SR


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg(
    *,
    enabled: bool = True,
    threshold: float = 0.5,
    min_voiced_fraction: float = 0.1,
) -> PrivacyFilterConfig:
    return PrivacyFilterConfig(
        enabled=enabled,
        threshold=threshold,
        min_voiced_fraction=min_voiced_fraction,
    )


def _filter(cfg: PrivacyFilterConfig, sample_rate: int = _SILERO_SR) -> PrivacyFilter:
    """Construct a PrivacyFilter with the model pre-set to a MagicMock.

    Setting _model to a non-None sentinel before scan() is called prevents
    _ensure_model() from attempting to load the real silero-vad weights.
    """
    pf = PrivacyFilter(cfg, sample_rate=sample_rate)
    pf._model = MagicMock()          # skip lazy model load
    return pf


@pytest.fixture
def mock_torch(monkeypatch) -> MagicMock:
    """Replace the torch module in sys.modules for the duration of each test."""
    m = MagicMock()
    monkeypatch.setitem(sys.modules, "torch", m)
    return m


@pytest.fixture
def mock_silero(monkeypatch) -> MagicMock:
    """Replace the silero_vad module in sys.modules for the duration of each test."""
    m = MagicMock()
    monkeypatch.setitem(sys.modules, "silero_vad", m)
    return m


# ── enabled property ──────────────────────────────────────────────────────────

class TestEnabledProperty:
    def test_enabled_when_cfg_true(self):
        pf = PrivacyFilter(_cfg(enabled=True), sample_rate=_SILERO_SR)
        assert pf.enabled is True

    def test_disabled_when_cfg_false(self):
        pf = PrivacyFilter(_cfg(enabled=False), sample_rate=_SILERO_SR)
        assert pf.enabled is False


# ── scan() — voiced-fraction logic ───────────────────────────────────────────

class TestScan:
    """Tests use 16 kHz audio (== _SILERO_SR) to skip the resample_poly branch."""

    def test_high_voiced_fraction_returns_true(self, mock_torch, mock_silero):
        """voiced_fraction = 1.0 >= min_voiced_fraction 0.1  → drop (True)."""
        audio = np.zeros(16_000, dtype=np.float32)     # 1 s at 16 kHz

        # Entire clip is voiced
        mock_silero.get_speech_timestamps.return_value = [{"start": 0, "end": 16_000}]
        mock_torch.from_numpy.return_value = MagicMock()

        pf = _filter(_cfg(min_voiced_fraction=0.1))
        assert pf.scan(audio) is True

    def test_low_voiced_fraction_returns_false(self, mock_torch, mock_silero):
        """voiced_fraction ≈ 0.031 < 0.1  → keep (False)."""
        audio = np.zeros(16_000, dtype=np.float32)

        # 500 / 16000 = 0.031 < 0.1 threshold
        mock_silero.get_speech_timestamps.return_value = [{"start": 0, "end": 500}]
        mock_torch.from_numpy.return_value = MagicMock()

        pf = _filter(_cfg(min_voiced_fraction=0.1))
        assert pf.scan(audio) is False

    def test_no_voiced_segments_returns_false(self, mock_torch, mock_silero):
        """voiced_fraction = 0  → keep (False)."""
        audio = np.zeros(16_000, dtype=np.float32)

        mock_silero.get_speech_timestamps.return_value = []
        mock_torch.from_numpy.return_value = MagicMock()

        pf = _filter(_cfg(min_voiced_fraction=0.1))
        assert pf.scan(audio) is False

    def test_voiced_fraction_exactly_at_threshold_returns_true(
        self, mock_torch, mock_silero
    ):
        """voiced_fraction == min_voiced_fraction is >= so it returns True."""
        audio = np.zeros(10_000, dtype=np.float32)

        # 1000 / 10000 = 0.10 exactly equals threshold
        mock_silero.get_speech_timestamps.return_value = [{"start": 0, "end": 1_000}]
        mock_torch.from_numpy.return_value = MagicMock()

        pf = _filter(_cfg(min_voiced_fraction=0.10))
        assert pf.scan(audio) is True

    def test_int16_audio_is_normalised(self, mock_torch, mock_silero):
        """int16 audio is converted to float32 before running VAD; scan() does not raise."""
        audio = np.full(16_000, 8192, dtype=np.int16)

        mock_silero.get_speech_timestamps.return_value = []
        mock_torch.from_numpy.return_value = MagicMock()

        pf = _filter(_cfg())
        result = pf.scan(audio)
        assert isinstance(result, bool)
