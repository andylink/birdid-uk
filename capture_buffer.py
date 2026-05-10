"""
capture_buffer.py — continuous ring buffer for long-clip capture.

Mirrors BirdNET-Go's CaptureBuffer design: the recording thread writes every
PCM chunk here continuously (independent of the 3-second analysis window).
When a detection fires, the classify loop notes the absolute sample offset
(``begin_sample``) and submits a deferred-save task that, after sleeping for
the required post-capture duration, reads the full clip segment in one shot.

Thread-safety contract
----------------------
- Exactly ONE thread calls :meth:`write` (the recording thread).
- Any number of threads may call :meth:`read_segment` concurrently (deferred
  save workers).
- All public methods acquire a single :class:`threading.Lock`.

Ring-buffer layout
------------------
- ``_buf``: pre-allocated ``int16`` array of ``max_seconds * sample_rate`` samples.
- ``_write_pos``: index of the *next* write (wraps modulo ``capacity``).
- ``_total_written``: monotonically increasing sample counter; used by callers
  to convert a wall-clock detection instant into an absolute sample index.
"""

from __future__ import annotations

import threading

import numpy as np


class CaptureBuffer:
    """Pre-allocated ring buffer for continuous audio capture.

    Args:
        max_seconds: Ring buffer capacity in seconds.  Should comfortably
            exceed the longest clip you intend to save (e.g. 30 s for 15 s
            clips leaves plenty of headroom).
        sample_rate: Recording sample rate in Hz (must match the microphone
            recording sample rate).
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
        """Append *chunk* (1-D int16) to the ring buffer.

        Wraps around transparently.  Older samples are silently overwritten
        once the buffer is full, which is the intended behaviour (we only care
        about the most recent ``max_seconds`` of audio).

        Args:
            chunk: 1-D ``int16`` numpy array from the recording thread.
        """
        n = len(chunk)
        with self._lock:
            end = self._write_pos + n
            if end <= self._capacity:
                # Fast path: no wrap-around needed.
                self._buf[self._write_pos:end] = chunk
            else:
                # Chunk straddles the end of the buffer — split into two copies.
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
        """Return ``length_samples`` samples starting at absolute index *begin_sample*.

        Returns ``None`` when the request cannot be satisfied:
        - **Too old**: the requested range has already been overwritten (i.e.
          the oldest sample still in the ring is *after* ``begin_sample``).
        - **Too new**: the requested end is beyond what has been written yet
          (caller should sleep longer before calling).

        Args:
            begin_sample:   Absolute sample index (matches units of
                            :attr:`total_written`).
            length_samples: Number of samples to return.

        Returns:
            A *new* 1-D ``int16`` numpy array of length *length_samples*, or
            ``None`` if the segment is unavailable.
        """
        with self._lock:
            end_sample = begin_sample + length_samples

            # Guard: requested end must not exceed what has been written.
            if end_sample > self._total_written:
                return None

            # Guard: requested begin must still be within the ring.
            oldest = self._total_written - self._capacity
            if begin_sample < oldest:
                return None

            # Map absolute indices to ring positions.
            start_pos = begin_sample % self._capacity
            end_pos   = end_sample   % self._capacity

            if start_pos < end_pos:
                # Contiguous slice — no wrap.
                return self._buf[start_pos:end_pos].copy()
            else:
                # Segment wraps around the end of the buffer.
                return np.concatenate([
                    self._buf[start_pos:],
                    self._buf[:end_pos],
                ])

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def total_written(self) -> int:
        """Total number of samples written since construction (thread-safe)."""
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
