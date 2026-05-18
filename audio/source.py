"""
audio/source.py — AudioSource protocol and factory.

All audio capture backends implement the same two-method protocol so the
recording thread in detector.py is source-agnostic.

Selecting a backend
-------------------
**Legacy single-source** — set ``[audio] source`` in config.toml::

    source = "sounddevice"   # default — local USB/built-in microphone via PortAudio
    source = "rtsp"          # IP camera / network microphone via FFmpeg subprocess

**Multi-source** — use ``[[audio.sources]]`` blocks instead (one per microphone).
In this mode, ``get_source()`` is called with an explicit
:class:`~config.AudioSourceConfig`; the legacy ``cfg.audio.source`` is ignored.

The factory ``get_source()`` reads ``cfg.audio.source`` (legacy) or the supplied
*source_config* (multi-source) and returns the appropriate backend instance.
Each call returns a *new* instance; the caller is responsible for calling
``close()`` when done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np

from config import cfg

if TYPE_CHECKING:
    from config import AudioSourceConfig


class AudioSource(Protocol):
    """Minimal interface every audio capture backend must satisfy.

    ``read_chunk()`` is the hot-path method: it blocks until exactly
    ``cfg.audio.hop_seconds * cfg.audio.sample_rate`` int16 samples are
    available, then returns them as a 1-D numpy array.  Implementations must
    handle their own error recovery internally (e.g. reconnecting a dropped
    RTSP stream) so the recording thread never needs to know which backend is
    in use.

    ``close()`` releases all resources (file descriptors, subprocess handles,
    PortAudio streams).  After calling ``close()``, the source must not be used.
    """

    def read_chunk(self) -> np.ndarray:
        """Block until one hop of audio is ready; return 1-D int16 ndarray."""
        ...

    def close(self) -> None:
        """Release all resources held by this source."""
        ...


def get_source(source_config: AudioSourceConfig | None = None) -> AudioSource:
    """Return a new AudioSource instance.

    Args:
        source_config: When provided (multi-source mode), creates a backend
            for this specific source config.  When ``None`` (legacy mode),
            reads ``cfg.audio.source`` to determine the backend type.

    Raises:
        ValueError: if the backend name is not recognised.
    """
    if source_config is not None:
        src_type = source_config.type.strip().lower()
        if src_type == "sounddevice":
            from audio.sounddevice_source import SounddeviceSource
            return SounddeviceSource(source_config)
        if src_type == "rtsp":
            from audio.rtsp_source import RtspSource
            return RtspSource(source_config)
        raise ValueError(
            f"[audio.sources] type = {source_config.type!r} is not recognised. "
            "Valid options: 'sounddevice', 'rtsp'."
        )

    # Legacy single-source path: read from cfg.audio.source.
    source = cfg.audio.source.strip().lower()

    if source == "sounddevice":
        from audio.sounddevice_source import SounddeviceSource
        return SounddeviceSource()

    if source == "rtsp":
        from audio.rtsp_source import RtspSource
        return RtspSource()

    raise ValueError(
        f"[audio] source = {cfg.audio.source!r} is not recognised. "
        "Valid options: 'sounddevice', 'rtsp'."
    )
