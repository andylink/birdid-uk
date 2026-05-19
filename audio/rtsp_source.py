"""
RTSP audio capture via an FFmpeg subprocess.

Enabled by setting ``[audio] source = "rtsp"`` and configuring ``[audio.rtsp]``:

    [audio]
    source = "rtsp"

    [audio.rtsp]
    url                     = "rtsp://192.168.1.100:554/audio"
    transport               = "tcp"   # "tcp" (reliable) or "udp" (lower latency)
    reconnect_delay_seconds = 5
    ffmpeg_path             = "ffmpeg"

In multi-source mode, each ``[[audio.sources]]`` block can point at a
different RTSP stream with its own settings.

FFmpeg is launched as a subprocess on construction. It decodes the stream to
raw signed 16-bit little-endian PCM (mono, target sample rate) and writes it
to stdout. read_chunk() reads one hop's worth of bytes from that pipe.

If the stream drops, read_chunk() restarts FFmpeg automatically after
reconnect_delay_seconds and keeps retrying indefinitely.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

import numpy as np

from config import cfg

if TYPE_CHECKING:
    from config import AudioSourceConfig

logger = logging.getLogger(__name__)


class RtspSource:
    """Captures audio from an RTSP stream via FFmpeg.

    FFmpeg is started on construction and restarted automatically if the
    stream drops. read_chunk() blocks until one hop of audio is available.

    Args:
        source_config: Per-source config from a ``[[audio.sources]]`` block.
            When None (legacy mode), settings are read from cfg.audio.rtsp.
    """

    def __init__(self, source_config: AudioSourceConfig | None = None) -> None:
        self._hop_samples = cfg.audio.sample_rate * cfg.audio.hop_seconds
        self._chunk_bytes = self._hop_samples * 2   # 2 bytes per int16 sample

        if source_config is not None:
            self._url             = source_config.url
            self._transport       = source_config.transport
            self._reconnect_delay = source_config.reconnect_delay_seconds
            self._ffmpeg_path     = source_config.ffmpeg_path
            self._name            = source_config.name
        else:
            rtsp = cfg.audio.rtsp
            self._url             = rtsp.url
            self._transport       = rtsp.transport
            self._reconnect_delay = rtsp.reconnect_delay_seconds
            self._ffmpeg_path     = rtsp.ffmpeg_path
            self._name            = "rtsp"

        self._proc: subprocess.Popen | None = None
        logger.info(
            "[audio] RTSP source '%s' — url=%s transport=%s",
            self._name, self._url, self._transport,
        )
        self._launch()

    # ── Public interface ──────────────────────────────────────────────────────

    def read_chunk(self) -> np.ndarray:
        """Return one hop of audio from the stream, blocking until it arrives.

        Reconnects transparently if the stream drops.

        Returns a 1-D int16 array of exactly sample_rate * hop_seconds samples.

        Raises:
            RuntimeError: if the ffmpeg binary can't be launched at all.
        """
        while True:
            data = self._read_exact(self._chunk_bytes)
            if data is not None:
                return np.frombuffer(data, dtype=np.int16).copy()
            # Short/empty read means the stream dropped; reconnect and retry.
            self._reconnect()

    def close(self) -> None:
        """Terminate the FFmpeg subprocess and release the pipe."""
        self._kill()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_command(self) -> list[str]:
        return [
            self._ffmpeg_path,
            "-rtsp_transport", self._transport,
            # Socket-level timeout in microseconds. 10 s is long enough for
            # slow networks but prevents hanging forever on a bad address.
            "-timeout",        "10000000",
            "-i",              self._url,
            # Transcode to raw signed 16-bit PCM, mono, at the target sample rate
            "-acodec", "pcm_s16le",
            "-ar",     str(cfg.audio.sample_rate),
            "-ac",     "1",
            "-f",      "s16le",
            # Suppress informational output; only real errors reach stderr
            "-loglevel", "error",
            "pipe:1",
        ]

    def _launch(self) -> None:
        """Start the FFmpeg subprocess. Raises RuntimeError if the binary is missing."""
        cmd = self._build_command()
        logger.debug("[audio/rtsp '%s'] launching: %s", self._name, " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,   # unbuffered so we read chunks as they arrive
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"[audio/rtsp '{self._name}'] ffmpeg binary not found at "
                f"{self._ffmpeg_path!r}. "
                "Install ffmpeg or set ffmpeg_path in the [[audio.sources]] block "
                "(or [audio.rtsp] in legacy mode)."
            )

    def _kill(self) -> None:
        """Terminate the FFmpeg subprocess if it's running."""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None

    def _reconnect(self) -> None:
        """Kill the current process and relaunch after the configured delay."""
        logger.warning(
            "[audio/rtsp '%s'] stream dropped — reconnecting in %ds (url=%s)",
            self._name, self._reconnect_delay, self._url,
        )
        self._kill()
        time.sleep(self._reconnect_delay)
        self._launch()

    def _read_exact(self, n: int) -> bytes | None:
        """Read exactly n bytes from the FFmpeg stdout pipe.

        Returns the bytes on success, or None if the pipe is closed or returns
        fewer bytes than expected (which means the stream has dropped).
        """
        if self._proc is None or self._proc.stdout is None:
            return None

        buf = bytearray()
        remaining = n
        while remaining > 0:
            try:
                chunk = self._proc.stdout.read(remaining)
            except Exception:  # noqa: BLE001
                return None
            if not chunk:
                # EOF — FFmpeg exited (stream ended or connection refused)
                return None
            buf += chunk
            remaining -= len(chunk)
        return bytes(buf)
