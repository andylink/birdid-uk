"""
filters/privacy_filter.py — drops detection clips that contain human speech.

When enabled, PrivacyFilter runs silero-vad against each confirmed detection
clip (inside _deferred_save) and drops any clip where the fraction of voiced
frames meets or exceeds min_voiced_fraction. Dropped clips produce no database
row, FLAC file, MQTT message, or BirdWeather upload.

silero-vad is a small (~1.8 MB) ONNX-backed neural VAD that reliably
distinguishes human speech from bird song and other environmental audio.
It runs on CPU and is independent of the BirdNET inference model.

Usage:
    from filters.privacy_filter import PrivacyFilter
    from config import cfg

    pf = PrivacyFilter(cfg.privacy_filter, cfg.audio.sample_rate)
    if pf.scan(audio_segment):
        return  # human speech detected — drop this clip
"""

from __future__ import annotations

import logging
from math import gcd
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from config import PrivacyFilterConfig

logger = logging.getLogger(__name__)

_SILERO_SR = 16_000  # silero-vad requires 16 kHz input


class PrivacyFilter:
    """Drops detection clips that contain human speech above a configurable threshold.

    Uses silero-vad to compute the fraction of voiced frames in a clip.
    If that fraction meets or exceeds min_voiced_fraction, the clip is
    considered to contain human speech and the caller should discard it.

    Parameters
    ----------
    cfg:
        PrivacyFilterConfig with enabled, threshold, and min_voiced_fraction.
    sample_rate:
        Sample rate of audio passed to scan() (cfg.audio.sample_rate).
        Audio is resampled to 16 kHz internally; the original array is not modified.
    """

    def __init__(
        self,
        cfg: PrivacyFilterConfig,
        sample_rate: int,
    ) -> None:
        self._cfg         = cfg
        self._sample_rate = sample_rate

        # Model is loaded on first use to avoid slowing startup
        self._model = None

        logger.info(
            "Privacy filter: threshold=%.2f  min_voiced_fraction=%.2f",
            cfg.threshold,
            cfg.min_voiced_fraction,
        )

    def _ensure_model(self) -> None:
        if self._model is None:
            from silero_vad import load_silero_vad
            self._model = load_silero_vad()
            logger.debug("silero-vad model loaded")

    @property
    def enabled(self) -> bool:
        """True when the filter is active."""
        return self._cfg.enabled

    def scan(self, audio: np.ndarray) -> bool:
        """Return True if human speech is detected above threshold.

        Resamples to 16 kHz, runs silero-vad, and returns True if the voiced
        fraction of the clip meets or exceeds min_voiced_fraction.

        Args:
            audio: PCM float32 (or int16) array at the configured sample_rate —
                typically the model-window slice of the assembled detection clip.

        Returns:
            True  → voiced fraction ≥ min_voiced_fraction; caller should drop the clip.
            False → below threshold; proceed normally.
        """
        import torch
        from silero_vad import get_speech_timestamps

        self._ensure_model()

        # Convert to float32 mono
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        else:
            audio = audio.astype(np.float32)

        # Resample to 16 kHz if needed
        if self._sample_rate != _SILERO_SR:
            from scipy.signal import resample_poly
            g    = gcd(self._sample_rate, _SILERO_SR)
            up   = _SILERO_SR // g
            down = self._sample_rate // g
            audio = resample_poly(audio, up, down).astype(np.float32)

        t = torch.from_numpy(audio)
        segments = get_speech_timestamps(
            t,
            self._model,
            sampling_rate=_SILERO_SR,
            threshold=self._cfg.threshold,
            return_seconds=False,
        )
        voiced_samples = sum(s["end"] - s["start"] for s in segments)
        voiced_fraction = voiced_samples / len(audio) if len(audio) > 0 else 0.0

        drop = voiced_fraction >= self._cfg.min_voiced_fraction
        logger.debug(
            "privacy scan: voiced_fraction=%.4f  min_voiced_fraction=%.4f  drop=%s",
            voiced_fraction, self._cfg.min_voiced_fraction, drop,
        )
        return drop
