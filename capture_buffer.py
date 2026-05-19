"""
capture_buffer.py — ring buffer for continuous audio capture.

The recording thread writes every PCM chunk here continuously, independent of
the 3-second analysis window. When a detection fires, the classifier notes the
current sample offset (begin_sample) and hands off a deferred-save task. That
task sleeps for the required post-capture duration, then reads the full clip
from this buffer in one shot.

Thread-safety:
- Exactly one thread calls write() (the recording thread).
- Any number of threads may call read_segment() concurrently (save workers).
- All public methods hold a single threading.Lock.

Buffer layout:
- _buf: pre-allocated int16 array of max_seconds * sample_rate samples.
- _write_pos: index of the next write slot (wraps at capacity).
- _total_written: total samples written since construction; callers use this
  to convert a detection timestamp into an absolute sample index.
"""

from __future__ import annotations

import threading

import numpy as np


class CaptureBuffer:
    """Pre-allocated ring buffer for continuous audio capture.

    Args:
        max_seconds: Buffer size in seconds. Should be comfortably larger than
            the longest clip you need to save (e.g. 30 s for 15 s clips).
        sample_rate: Recording sample rate in Hz — must match the microphone.
    """

    def __init__(self, max_seconds: int, sample_rate: int) -> None:
        self._sample_rate  = sample_rate
        self._capacity     = max_seconds * sample_rate
        self._buf          = np.zeros(self._capacity, dtype=np.int16)
        self._write_pos    = 0    # index of next write slot
        self._total_written = 0  # monotonically increasing sample count
        self._lock         = threading.Lock()

    # ── Write ─────────────────────────────────────────────────────────────────

    def write(self, chunk: np.ndarray) -> None:
        """Append a chunk of audio samples to the ring buffer.

        Wraps around transparently. Once the buffer is full, the oldest samples
        are overwritten — we only need the most recent max_seconds of audio.

        Args:
            chunk: 1-D int16 numpy array from the recording thread.
        """
        n = len(chunk)
        with self._lock:
            end = self._write_pos + n
            if end <= self._capacity:
                # Fast path: chunk fits without wrapping.
                self._buf[self._write_pos:end] = chunk
            else:
                # Chunk straddles the end of the buffer — split into two writes.
                first  = self._capacity - self._write_pos
                self._buf[self._write_pos:] = chunk[:first]
                self._buf[:n - first]       = chunk[first:]

            self._write_pos   = end % self._capacity
            self._total_written += n

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_segment(
        self,
        begin_sample: int,
        length_samples: int,
    ) -> np.ndarray | None:
        """Return a contiguous slice of recorded audio starting at begin_sample.

        Returns None when the request can't be satisfied:
        - Too old: the requested range has already been overwritten.
        - Too new: the requested end hasn't been written yet (caller should
          sleep longer before retrying).

        Args:
            begin_sample:   Absolute sample index (same units as total_written).
            length_samples: Number of samples to return.

        Returns:
            A new 1-D int16 numpy array of length length_samples, or None.
        """
        with self._lock:
            end_sample = begin_sample + length_samples

            # Requested end must not be ahead of what's been written yet.
            if end_sample > self._total_written:
                return None

            # Requested start must still be within the ring (not overwritten).
            oldest = self._total_written - self._capacity
            if begin_sample < oldest:
                return None

            # Map absolute indices to positions in the ring array.
            start_pos = begin_sample % self._capacity
            end_pos   = end_sample   % self._capacity

            if start_pos < end_pos:
                # Contiguous slice — no wrap needed.
                return self._buf[start_pos:end_pos].copy()
            else:
                # Segment wraps around the end of the buffer — stitch two slices.
                return np.concatenate([
                    self._buf[start_pos:],
                    self._buf[:end_pos],
                ])

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def total_written(self) -> int:
        """Total samples written since construction (thread-safe)."""
        with self._lock:
            return self._total_written

    @property
    def sample_rate(self) -> int:
        """Sample rate this buffer was created with."""
        return self._sample_rate

    @property
    def capacity(self) -> int:
        """Ring buffer capacity in samples."""
        return self._capacity
