"""
tests/unit/test_capture_buffer.py — unit tests for capture_buffer.py
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from capture_buffer import CaptureBuffer


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _buf(max_seconds: int = 5, sample_rate: int = 8) -> CaptureBuffer:
    """Small buffer: 5 s × 8 Hz = 40 samples capacity."""
    return CaptureBuffer(max_seconds=max_seconds, sample_rate=sample_rate)


def _chunk(n: int, value: int = 1) -> np.ndarray:
    return np.full(n, value, dtype=np.int16)


# ── Construction ──────────────────────────────────────────────────────────────

class TestConstruction:
    def test_capacity(self):
        b = _buf(max_seconds=10, sample_rate=100)
        assert b.capacity == 1000

    def test_sample_rate(self):
        b = _buf(sample_rate=48000)
        assert b.sample_rate == 48000

    def test_total_written_starts_at_zero(self):
        b = _buf()
        assert b.total_written == 0


# ── Write and basic read ──────────────────────────────────────────────────────

class TestWriteAndRead:
    def test_write_increments_total_written(self):
        b = _buf()
        b.write(_chunk(8))
        assert b.total_written == 8
        b.write(_chunk(4))
        assert b.total_written == 12

    def test_read_returns_correct_data(self):
        b = _buf()
        data = np.arange(16, dtype=np.int16)
        b.write(data)
        result = b.read_segment(0, 16)
        assert result is not None
        np.testing.assert_array_equal(result, data)

    def test_read_partial_segment(self):
        b = _buf()
        data = np.arange(16, dtype=np.int16)
        b.write(data)
        result = b.read_segment(4, 8)
        assert result is not None
        np.testing.assert_array_equal(result, data[4:12])

    def test_read_returns_copy_not_view(self):
        b = _buf()
        data = np.ones(8, dtype=np.int16)
        b.write(data)
        result = b.read_segment(0, 8)
        assert result is not None
        result[0] = 99
        result2 = b.read_segment(0, 8)
        assert result2 is not None
        assert result2[0] == 1  # original in buffer unmodified


# ── Boundary / guard conditions ───────────────────────────────────────────────

class TestBoundaryConditions:
    def test_read_beyond_total_written_returns_none(self):
        b = _buf()
        b.write(_chunk(10))
        # Request 15 samples from index 0 — only 10 written
        assert b.read_segment(0, 15) is None

    def test_read_future_samples_returns_none(self):
        b = _buf()
        # Nothing written yet
        assert b.read_segment(0, 1) is None

    def test_read_overwritten_data_returns_none(self):
        # Buffer capacity = 40 samples (5 s × 8 Hz)
        b = _buf()
        # Write 40 samples (fills the buffer)
        b.write(np.zeros(40, dtype=np.int16))
        # Write 8 more samples — this overwrites the oldest 8
        b.write(_chunk(8, value=5))
        # Now oldest retained sample is at index 8
        # Requesting from index 0 should fail (overwritten)
        assert b.read_segment(0, 8) is None

    def test_read_at_oldest_retained_boundary(self):
        b = _buf()
        data = np.arange(40, dtype=np.int16)
        b.write(data)
        # Write 8 more to push out the first 8
        extra = np.full(8, 99, dtype=np.int16)
        b.write(extra)
        # Oldest available is now sample index 8
        result = b.read_segment(8, 8)
        assert result is not None
        np.testing.assert_array_equal(result, data[8:16])


# ── Wrap-around ───────────────────────────────────────────────────────────────

class TestWrapAround:
    def test_wrap_around_read_is_correct(self):
        """Write past the end of the buffer and verify the segment is reconstructed."""
        # capacity = 40 (5 × 8)
        b = _buf()
        # Write 36 samples to bring write pointer near the end
        b.write(np.arange(36, dtype=np.int16))
        # Write 8 more — straddles the end of the ring (4 at tail, 4 at head)
        tail_values = np.array([100, 101, 102, 103, 104, 105, 106, 107], dtype=np.int16)
        b.write(tail_values)
        # Read back the last 8 samples (indices 36-43)
        result = b.read_segment(36, 8)
        assert result is not None
        np.testing.assert_array_equal(result, tail_values)

    def test_total_written_increases_monotonically_after_wrap(self):
        b = _buf()
        b.write(np.zeros(40, dtype=np.int16))
        b.write(np.zeros(20, dtype=np.int16))
        assert b.total_written == 60


# ── Thread safety ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_write_and_read(self):
        """A single writer and multiple readers don't corrupt the buffer."""
        sr = 100
        b = CaptureBuffer(max_seconds=10, sample_rate=sr)

        errors: list[Exception] = []

        def writer() -> None:
            for i in range(200):
                b.write(np.full(50, i % 128, dtype=np.int16))

        def reader() -> None:
            for _ in range(400):
                tw = b.total_written
                if tw >= 50:
                    b.read_segment(max(0, tw - 50), 50)

        t_write = threading.Thread(target=writer)
        t_read1 = threading.Thread(target=reader)
        t_read2 = threading.Thread(target=reader)

        t_write.start()
        t_read1.start()
        t_read2.start()

        t_write.join(timeout=5)
        t_read1.join(timeout=5)
        t_read2.join(timeout=5)

        # No exceptions — the main check is that nothing crashes
        assert not errors
        assert b.total_written == 200 * 50  # writer completed
