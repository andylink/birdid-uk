"""
Unit tests for audio.py.

audio/utils.py imports `cfg` at module level, so we monkeypatch
`audio.utils.cfg` in each test that exercises config-dependent code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import audio
import audio.utils
from audio import apply_highpass, safe_name, save_flac, save_clip


# ── safe_name ─────────────────────────────────────────────────────────────────

class TestSafeName:
    def test_alphanumeric_unchanged(self):
        assert safe_name("Robin123") == "Robin123"

    def test_spaces_replaced(self):
        assert safe_name("European Robin") == "European_Robin"

    def test_apostrophe_replaced(self):
        assert safe_name("Rüppell's Vulture") == "R_ppell_s_Vulture"

    def test_slash_replaced(self):
        assert safe_name("a/b") == "a_b"

    def test_hyphen_preserved(self):
        assert safe_name("blue-tit") == "blue-tit"

    def test_underscore_preserved(self):
        assert safe_name("a_b") == "a_b"

    def test_dot_replaced(self):
        assert safe_name("file.flac") == "file_flac"

    def test_empty_string(self):
        assert safe_name("") == ""


# ── apply_highpass ────────────────────────────────────────────────────────────

class TestApplyHighpass:
    def test_returns_int16_array(self, sample_audio):
        result = apply_highpass(sample_audio, 48000, cutoff_hz=150.0, order=5)
        assert result.dtype == np.int16

    def test_output_same_length_as_input(self, sample_audio):
        result = apply_highpass(sample_audio, 48000, cutoff_hz=150.0, order=5)
        assert len(result) == len(sample_audio)

    def test_input_not_modified(self, sample_audio):
        original = sample_audio.copy()
        apply_highpass(sample_audio, 48000, cutoff_hz=150.0, order=5)
        np.testing.assert_array_equal(sample_audio, original)

    def test_values_clipped_to_int16_range(self, sample_audio):
        result = apply_highpass(sample_audio, 48000, cutoff_hz=150.0, order=5)
        assert result.min() >= -32768
        assert result.max() <= 32767

    def test_high_frequency_preserved(self):
        """A 1 kHz tone (well above the 150 Hz cutoff) should retain substantial energy."""
        sr = 48000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        high = (np.sin(2 * np.pi * 1000 * t) * 8000).astype(np.int16)
        filtered = apply_highpass(high, sr, cutoff_hz=150.0, order=5)
        assert np.abs(filtered).max() > 1000

    def test_low_frequency_attenuated(self):
        """A 10 Hz tone (well below the 150 Hz cutoff) should be heavily attenuated."""
        sr = 48000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        low = (np.sin(2 * np.pi * 10 * t) * 16000).astype(np.int16)
        filtered = apply_highpass(low, sr, cutoff_hz=150.0, order=5)
        # Filtered mean amplitude should be less than 10% of the original
        original_peak = np.abs(low.astype(np.float32)).mean()
        filtered_peak = np.abs(filtered.astype(np.float32)).mean()
        assert filtered_peak < original_peak * 0.1


# ── save_flac ─────────────────────────────────────────────────────────────────

class TestSaveFlac:
    def test_creates_readable_flac_file(self, sample_audio, tmp_path, test_cfg, monkeypatch):
        monkeypatch.setattr(audio.utils, "cfg", test_cfg)
        out_path = tmp_path / "test.flac"
        save_flac(sample_audio, out_path)
        assert out_path.exists()
        data, sr = sf.read(str(out_path), dtype="int16")
        assert sr == test_cfg.audio.sample_rate
        assert len(data) == len(sample_audio)

    def test_flac_data_matches_input(self, sample_audio, tmp_path, test_cfg, monkeypatch):
        monkeypatch.setattr(audio.utils, "cfg", test_cfg)
        out_path = tmp_path / "test.flac"
        save_flac(sample_audio, out_path)
        data, _ = sf.read(str(out_path), dtype="int16")
        np.testing.assert_array_equal(data, sample_audio)


# ── save_clip ─────────────────────────────────────────────────────────────────

class TestSaveClip:
    @pytest.fixture(autouse=True)
    def patch_cfg(self, test_cfg, monkeypatch):
        monkeypatch.setattr(audio.utils, "cfg", test_cfg)

    def test_returns_path_object(self, sample_audio, test_cfg):
        ts = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        p = save_clip(sample_audio, ts, "European Robin")
        assert isinstance(p, Path)

    def test_file_is_created(self, sample_audio, test_cfg):
        ts = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        p = save_clip(sample_audio, ts, "European Robin")
        assert p.exists()

    def test_filename_includes_timestamp_and_species(self, sample_audio, test_cfg):
        ts = datetime(2026, 5, 13, 12, 30, 45, tzinfo=timezone.utc)
        p = save_clip(sample_audio, ts, "European Robin")
        assert "20260513_123045" in p.name
        assert "European_Robin" in p.name
        assert p.suffix == ".flac"

    def test_normalisation_scales_to_peak_32767(self, test_cfg):
        """save_clip should normalise audio to full int16 range before saving."""
        low_signal = np.full(48000, 100, dtype=np.int16)
        ts = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        p = save_clip(low_signal, ts, "TestBird")
        data, _ = sf.read(str(p), dtype="int16")
        assert np.abs(data).max() == 32767

    def test_silent_clip_handled_without_error(self, test_cfg):
        """All-zeros (silent) audio should not cause a ZeroDivisionError."""
        silent = np.zeros(48000, dtype=np.int16)
        ts = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        p = save_clip(silent, ts, "SilentBird")
        assert p.exists()

    def test_detections_dir_created_if_missing(self, test_cfg, tmp_path, monkeypatch):
        """save_clip should create the detections directory if it doesn't exist yet."""
        import dataclasses
        from config import PathsConfig

        new_dir = tmp_path / "new_detections"
        assert not new_dir.exists()

        new_paths = dataclasses.replace(
            test_cfg.paths,
            detections_dir=new_dir,
        )
        new_cfg = dataclasses.replace(test_cfg, paths=new_paths)
        monkeypatch.setattr(audio.utils, "cfg", new_cfg)
        ts = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        save_clip(np.zeros(48000, dtype=np.int16), ts, "Placeholder")
        assert new_dir.exists()
