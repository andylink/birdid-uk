"""
Defines the AudioSource protocol and the get_source() factory.

All audio backends expose the same two methods (read_chunk / close), so the
recording thread in detector.py doesn't need to know which backend it's using.

Backend selection
-----------------
Single-source: set ``[audio] source`` in config.toml:

    source = "sounddevice"   # local microphone via PortAudio (default)
    source = "rtsp"          # network camera/microphone via FFmpeg

Multi-source: use ``[[audio.sources]]`` blocks (one per microphone).
Pass the relevant AudioSourceConfig to get_source() directly; cfg.audio.source
is ignored in this mode.

Each call to get_source() returns a new instance. The caller must call close()
when done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np

from config import cfg

if TYPE_CHECKING:
    from config import AudioSourceConfig


class AudioSource(Protocol):
    """Interface that every audio capture backend must implement.

    read_chunk() blocks until one hop of audio is ready and returns it as a
    1-D int16 numpy array. Backends handle their own error recovery (e.g.
    reconnecting a dropped RTSP stream) so the recording thread stays simple.

    close() releases all resources. The source must not be used afterwards.
    """

    def read_chunk(self) -> np.ndarray:
        """Block until one hop of audio is ready; return a 1-D int16 array."""
        ...

    def close(self) -> None:
        """Release all resources held by this source."""
        ...


def get_source(source_config: AudioSourceConfig | None = None) -> AudioSource:
    """Create and return the appropriate audio backend.

    Args:
        source_config: If given, creates a backend for that specific source
            (multi-source mode). If None, reads cfg.audio.source (legacy mode).

    Raises:
        ValueError: if the backend name isn't recognised.
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
