"""
audio/rtsp_source.py — RTSP audio capture via FFmpeg subprocess.

Enabled by setting ``[audio] source = "rtsp"`` in config.toml and configuring
the ``[audio.rtsp]`` subsection::

    [audio]
    source = "rtsp"

    [audio.rtsp]
    url                     = "rtsp://192.168.1.100:554/audio"
    transport               = "tcp"   # "tcp" (reliable) or "udp" (lower latency)
    reconnect_delay_seconds = 5
    ffmpeg_path             = "ffmpeg"

Multi-source usage
------------------
When instantiated with an :class:`~config.AudioSourceConfig` (multi-source mode),
the RTSP settings (url, transport, reconnect_delay_seconds, ffmpeg_path) are
taken from that config rather than from ``[audio.rtsp]``, allowing each source
to point at a different network stream.

How it works
------------
``RtspSource.__init__()`` immediately launches an ``ffmpeg`` subprocess that:

* Opens the RTSP stream using the configured transport (``-rtsp_transport``).
* Decodes/transcodes the audio to raw signed 16-bit little-endian PCM
  (``-acodec pcm_s16le``), mono (``-ac 1``), at the configured sample rate
  (``-ar <rate>``).
* Writes the raw PCM bytes to stdout (``-f s16le pipe:1``).

``read_chunk()`` reads exactly ``hop_samples * 2`` bytes (2 bytes per int16
sample) from that pipe per call, mirroring the cadence of the sounddevice
backend.

Reconnection
------------
If ``read_chunk()`` receives a short read (stream dropped / server restarted),
it terminates the ffmpeg process, waits ``reconnect_delay_seconds``, then
relaunches it — indefinitely, matching the ``sounddevice`` backend's retry
loop in ``_record_thread()``.  The recording thread's outer try/except handles
any unexpected exceptions and also retries, so reconnection is doubly resilient.

FFmpeg stderr is suppressed (``-loglevel error``) and redirected to
``/dev/null`` to avoid polluting the terminal; only genuine error messages
reach the system stderr.
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
    """Captures audio from an RTSP stream via an FFmpeg subprocess.

    The subprocess is started on construction and restarted automatically
    whenever the stream drops.  ``read_chunk()`` blocks until one hop of
    PCM audio has been received from the pipe.

    Args:
        source_config: Per-source config from a ``[[audio.sources]]`` block.
            When ``None`` (legacy mode), RTSP settings are read from
            ``cfg.audio.rtsp``.
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
        """Block until one hop of PCM audio arrives from the RTSP stream.

        Handles reconnection transparently: if the stream drops, this method
        waits ``reconnect_delay_seconds`` and relaunches FFmpeg, then retries.

        Returns a 1-D int16 numpy array of exactly
        ``sample_rate * hop_seconds`` samples.

        Raises:
            RuntimeError: only if FFmpeg cannot be launched at all (e.g.
                ``ffmpeg`` binary not found).  In normal operation all errors
                are handled internally.
        """
        while True:
            data = self._read_exact(self._chunk_bytes)
            if data is not None:
                return np.frombuffer(data, dtype=np.int16).copy()
            # Short/empty read — stream dropped; reconnect.
            self._reconnect()

    def close(self) -> None:
        """Terminate the FFmpeg subprocess and release the pipe."""
        self._kill()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_command(self) -> list[str]:
        return [
            self._ffmpeg_path,
            # Input / transport
            "-rtsp_transport", self._transport,
            # Socket-level timeout (microseconds): fail fast if the host is
            # silently unreachable instead of blocking forever.  10 s gives
            # enough time for slow/congested networks while preventing the
            # recording thread from hanging indefinitely on a bad IP/port.
            "-timeout",        "10000000",
            "-i",              self._url,
            # Output: raw signed 16-bit LE PCM, mono, target sample rate
            "-acodec", "pcm_s16le",
            "-ar",     str(cfg.audio.sample_rate),
            "-ac",     "1",
            "-f",      "s16le",
            # Silence all non-error output so the terminal stays clean
            "-loglevel", "error",
            # Write to stdout
            "pipe:1",
        ]

    def _launch(self) -> None:
        """Start the FFmpeg subprocess.  Raises RuntimeError if the binary is missing."""
        cmd = self._build_command()
        logger.debug("[audio/rtsp '%s'] launching: %s", self._name, " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,   # unbuffered — we manage our own chunked reads
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"[audio/rtsp '{self._name}'] ffmpeg binary not found at "
                f"{self._ffmpeg_path!r}. "
                "Install ffmpeg or set ffmpeg_path in the [[audio.sources]] block "
                "(or [audio.rtsp] in legacy mode)."
            )

    def _kill(self) -> None:
        """Terminate the FFmpeg subprocess if it is running."""
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
        """Tear down the current process and relaunch after a short delay."""
        logger.warning(
            "[audio/rtsp '%s'] stream dropped — reconnecting in %ds (url=%s)",
            self._name, self._reconnect_delay, self._url,
        )
        self._kill()
        time.sleep(self._reconnect_delay)
        self._launch()

    def _read_exact(self, n: int) -> bytes | None:
        """Read exactly *n* bytes from the FFmpeg stdout pipe.

        Returns the bytes on success, or ``None`` if the pipe returns EOF or
        fewer bytes than requested (indicating the stream has dropped).
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
