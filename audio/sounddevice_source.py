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
"""

from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

from config import cfg

logger = logging.getLogger(__name__)


class SounddeviceSource:
    """Captures audio from a local microphone using PortAudio via sounddevice.

    Each call to ``read_chunk()`` records exactly one hop of audio in blocking
    mode and returns it as a 1-D int16 numpy array.
    """

    def __init__(self) -> None:
        self._hop_samples = cfg.audio.sample_rate * cfg.audio.hop_seconds
        device_label = cfg.audio.device if cfg.audio.device is not None else "default"
        logger.info(
            "[audio] sounddevice source — device=%s sample_rate=%d hop=%ds",
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
            device=cfg.audio.device,
        )
        sd.wait()
        return chunk.flatten()

    def close(self) -> None:
        """No persistent resources to release for the blocking sounddevice API."""
        pass
