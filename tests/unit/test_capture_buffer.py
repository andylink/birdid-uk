"""
Unit tests for capture_buffer.py.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from capture_buffer import CaptureBuffer


# ── Helpers ───────────────────────────────────────────────────────────────────

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
        """Modifying the returned array should not affect data still in the buffer."""
        b = _buf()
        data = np.ones(8, dtype=np.int16)
        b.write(data)
        result = b.read_segment(0, 8)
        assert result is not None
        result[0] = 99
        result2 = b.read_segment(0, 8)
        assert result2 is not None
        assert result2[0] == 1


# ── Boundary / guard conditions ───────────────────────────────────────────────

class TestBoundaryConditions:
    def test_read_beyond_total_written_returns_none(self):
        b = _buf()
        b.write(_chunk(10))
        # 15 samples requested but only 10 written
        assert b.read_segment(0, 15) is None

    def test_read_future_samples_returns_none(self):
        b = _buf()
        assert b.read_segment(0, 1) is None

    def test_read_overwritten_data_returns_none(self):
        """Once data has been overwritten by the ring buffer, it can no longer be read."""
        b = _buf()  # capacity = 40
        b.write(np.zeros(40, dtype=np.int16))
        b.write(_chunk(8, value=5))  # overwrites first 8 samples
        assert b.read_segment(0, 8) is None

    def test_read_at_oldest_retained_boundary(self):
        b = _buf()
        data = np.arange(40, dtype=np.int16)
        b.write(data)
        extra = np.full(8, 99, dtype=np.int16)
        b.write(extra)
        # First 8 samples are gone; index 8 is now the oldest available
        result = b.read_segment(8, 8)
        assert result is not None
        np.testing.assert_array_equal(result, data[8:16])


# ── Wrap-around ───────────────────────────────────────────────────────────────

class TestWrapAround:
    def test_wrap_around_read_is_correct(self):
        """Data written across the ring boundary should be reconstructed correctly."""
        b = _buf()  # capacity = 40
        b.write(np.arange(36, dtype=np.int16))
        # Next write straddles the end (4 samples at tail, 4 at head)
        tail_values = np.array([100, 101, 102, 103, 104, 105, 106, 107], dtype=np.int16)
        b.write(tail_values)
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
        """One writer and two concurrent readers should not corrupt the buffer or crash."""
        sr = 100
        b = CaptureBuffer(max_seconds=10, sample_rate=sr)

        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(200):
                    b.write(np.full(50, i % 128, dtype=np.int16))
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(400):
                    tw = b.total_written
                    if tw >= 50:
                        b.read_segment(max(0, tw - 50), 50)
            except Exception as e:
                errors.append(e)

        t_write = threading.Thread(target=writer)
        t_read1 = threading.Thread(target=reader)
        t_read2 = threading.Thread(target=reader)

        t_write.start()
        t_read1.start()
        t_read2.start()

        t_write.join(timeout=5)
        t_read1.join(timeout=5)
        t_read2.join(timeout=5)

        assert not errors
        assert b.total_written == 200 * 50
