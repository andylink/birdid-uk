"""
filters/privacy_filter.py — clip-level human-speech privacy gate.

When enabled, :class:`PrivacyFilter` runs silero-vad against each confirmed
detection clip (inside ``_deferred_save``) and drops any clip where the
fraction of voiced frames meets or exceeds ``min_voiced_fraction``.  No
database row, FLAC clip, MQTT message, or BirdWeather upload is created for
dropped clips.

silero-vad is a small (~1.8 MB) ONNX-backed neural VAD that correctly
distinguishes human speech from environmental audio including bird song.
It does not depend on the active inference model and runs on CPU only.

Usage::

    from filters.privacy_filter import PrivacyFilter
    from config import cfg

    pf = PrivacyFilter(cfg.privacy_filter, cfg.audio.sample_rate)
    if pf.scan(audio_segment):
        return  # drop — human speech detected
"""

from __future__ import annotations

import logging
from math import gcd
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from config import PrivacyFilterConfig

logger = logging.getLogger(__name__)

_SILERO_SR = 16_000  # silero-vad only accepts 16 kHz input


class PrivacyFilter:
    """Clip-level gate that drops detections containing human speech.

    Uses silero-vad (neural VAD) to compute the fraction of voiced frames in
    the clip.  If the voiced fraction meets or exceeds *min_voiced_fraction*
    the clip is considered to contain human speech and should be dropped.

    Parameters
    ----------
    cfg:
        :class:`~config.PrivacyFilterConfig` with ``enabled``,
        ``threshold``, and ``min_voiced_fraction``.
    sample_rate:
        Native sample rate of audio passed to :meth:`scan`
        (``cfg.audio.sample_rate``).  Audio will be resampled to 16 kHz
        internally; the original array is not modified.
    """

    def __init__(
        self,
        cfg: PrivacyFilterConfig,
        sample_rate: int,
    ) -> None:
        self._cfg         = cfg
        self._sample_rate = sample_rate

        # Lazy-load silero-vad model on first use to avoid slowing startup
        # when the filter is enabled but the detector hasn't confirmed a clip yet.
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
        """True when the filter is active (mirrors ``cfg.privacy_filter.enabled``)."""
        return self._cfg.enabled

    def scan(self, audio: np.ndarray) -> bool:
        """Return ``True`` if human speech is detected above threshold.

        Resamples *audio* to 16 kHz, runs silero-vad frame-by-frame with the
        configured *threshold*, and returns whether the voiced fraction of the
        clip meets or exceeds ``cfg.min_voiced_fraction``.

        Args:
            audio: PCM float32 (or int16) array at ``sample_rate`` — typically
                the model-window slice of the assembled detection clip.

        Returns:
            ``True``  → voiced fraction ≥ min_voiced_fraction; caller should
                         drop the clip.
            ``False`` → speech below threshold; proceed normally.
        """
        import torch
        from silero_vad import get_speech_timestamps

        self._ensure_model()

        # ── Convert to float32 mono ───────────────────────────────────────────
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        else:
            audio = audio.astype(np.float32)

        # ── Resample to 16 kHz ────────────────────────────────────────────────
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
