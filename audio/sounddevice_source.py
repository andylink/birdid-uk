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
import queue
import threading
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

from config import cfg

if TYPE_CHECKING:
    from config import AudioSourceConfig

logger = logging.getLogger(__name__)


class SounddeviceSource:
    """Records audio from a local microphone using sounddevice.

    Uses a persistent ``sd.InputStream`` with a callback so that the recording
    thread stays responsive to the ``stop_event`` even if the audio device is
    removed mid-session.  ``sd.rec()`` / ``sd.wait()`` would block indefinitely
    on device removal, making a clean shutdown impossible.

    Each ``read_chunk()`` call blocks until one hop of audio is available in the
    internal queue and returns it as a 1-D int16 numpy array.

    Args:
        source_config: Per-source config from a ``[[audio.sources]]`` block.
            When None (legacy mode), device is read from cfg.audio.device.
    """

    def __init__(self, source_config: AudioSourceConfig | None = None) -> None:
        self._hop_samples = cfg.audio.sample_rate * cfg.audio.hop_seconds
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)

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

        self._stream = sd.InputStream(
            samplerate=cfg.audio.sample_rate,
            channels=1,
            dtype="int16",
            device=self._device,
            blocksize=self._hop_samples,
            callback=self._callback,
        )
        self._stream.start()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """PortAudio callback — called from the sounddevice audio thread."""
        if status:
            logger.warning("[audio/sounddevice] stream status: %s", status)
        try:
            # Copy is required; indata is only valid for the duration of the callback.
            self._queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            # Classifier is falling behind — drop the oldest chunk and continue.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(indata[:, 0].copy())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_chunk(self) -> np.ndarray:
        """Block until one hop of audio is available and return it.

        Returns a 1-D int16 array of exactly sample_rate * hop_seconds samples.

        Raises:
            Exception: any PortAudio error propagated through the stream's
                finished_callback, or an sd.PortAudioError if the device
                is removed. The caller is expected to retry.
        """
        # Use a short timeout so the capture thread remains interruptible.
        while True:
            try:
                return self._queue.get(timeout=0.5)
            except queue.Empty:
                # No audio yet — check if the stream is still alive.
                if not self._stream.active:
                    raise RuntimeError(
                        "[audio/sounddevice] stream stopped unexpectedly — "
                        "device may have been removed"
                    )

    def close(self) -> None:
        """Stop and close the PortAudio stream."""
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass
