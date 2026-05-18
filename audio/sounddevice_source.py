"""
audio/sounddevice_source.py — local microphone capture via PortAudio/sounddevice.

This is the default audio source (``[audio] source = "sounddevice"``).  It
wraps the existing ``sounddevice.rec()`` / ``sd.wait()`` blocking capture that
was previously inlined in ``detector._record_thread()``.

Device selection
----------------
Set ``[audio] device`` in config.toml to the integer index shown by::

    python -m sounddevice

Leave it unset (or ``device = 0``) to use the system default input device.

Multi-source usage
------------------
When instantiated with an :class:`~config.AudioSourceConfig` (multi-source mode),
the ``device`` field of that config overrides the global ``[audio] device``
setting, allowing each source to capture from a different microphone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

from config import cfg

if TYPE_CHECKING:
    from config import AudioSourceConfig

logger = logging.getLogger(__name__)


class SounddeviceSource:
    """Captures audio from a local microphone using PortAudio via sounddevice.

    Each call to ``read_chunk()`` records exactly one hop of audio in blocking
    mode and returns it as a 1-D int16 numpy array.

    Args:
        source_config: Per-source config from a ``[[audio.sources]]`` block.
            When ``None`` (legacy mode), device is read from ``cfg.audio.device``.
    """

    def __init__(self, source_config: AudioSourceConfig | None = None) -> None:
        self._hop_samples = cfg.audio.sample_rate * cfg.audio.hop_seconds

        if source_config is not None:
            self._device = source_config.device
            _label       = source_config.name
        else:
            self._device = cfg.audio.device
            _label       = "default"

        device_label = self._device if self._device is not None else "default"
        logger.info(
            "[audio] sounddevice source '%s' — device=%s sample_rate=%d hop=%ds",
            _label,
            device_label,
            cfg.audio.sample_rate,
            cfg.audio.hop_seconds,
        )

    def read_chunk(self) -> np.ndarray:
        """Record one hop of audio; block until complete.

        Returns a 1-D int16 numpy array of exactly
        ``sample_rate * hop_seconds`` samples.

        Raises:
            Exception: any sounddevice / PortAudio error (caller retries).
        """
        chunk = sd.rec(
            self._hop_samples,
            samplerate=cfg.audio.sample_rate,
            channels=1,
            dtype="int16",
            device=self._device,
        )
        sd.wait()
        return chunk.flatten()

    def close(self) -> None:
        """No persistent resources to release for the blocking sounddevice API."""
        pass
