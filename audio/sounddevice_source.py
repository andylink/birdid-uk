"""
Local microphone capture using sounddevice (PortAudio).

This is the default backend (``[audio] source = "sounddevice"``).

Device selection: set ``[audio] device`` in config.toml to the integer index
shown by ``python -m sounddevice``. Leave it unset to use the system default.

In multi-source mode, each AudioSourceConfig can specify its own device,
allowing different sources to capture from different microphones.
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
    """Records audio from a local microphone using sounddevice.

    Each read_chunk() call records one hop of audio in blocking mode and
    returns it as a 1-D int16 numpy array.

    Args:
        source_config: Per-source config from a ``[[audio.sources]]`` block.
            When None (legacy mode), device is read from cfg.audio.device.
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
        """Record one hop of audio and block until it's complete.

        Returns a 1-D int16 array of exactly sample_rate * hop_seconds samples.

        Raises:
            Exception: any PortAudio error — the caller is expected to retry.
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
        """Nothing to release — sounddevice opens and closes the device per call."""
        pass
