"""
tests/conftest.py — shared pytest fixtures for the bird-detector test suite.

All fixtures here are available to every test file under tests/.

Config patching strategy
------------------------
Several production modules hold a module-level reference to the ``cfg``
singleton (imported as ``from config import cfg``).  Because the reference is
bound at import time, patching ``config.cfg`` alone won't affect those modules.
Tests that need to override config values must patch the reference in each
module they exercise, e.g.::

    monkeypatch.setattr(audio, "cfg", test_cfg)
    monkeypatch.setattr(retention, "cfg", test_cfg)

The ``test_cfg`` fixture below provides a fully-populated Config object backed
by temporary directories so tests don't touch the real data/ tree.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from config import (
    AudioConfig,
    AudioRtspConfig,
    BirdmapConfig,
    BirdweatherConfig,
    SpeciesFilterConfig,
    Config,
    CrossValidationConfig,
    DatabaseConfig,
    FilterConfig,
    GeneralConfig,
    InferenceConfig,
    LocationConfig,
    LogConfig,
    MqttConfig,
    NocturnalFilterConfig,
    PathsConfig,
    RetentionConfig,
    SeasonalFilterConfig,
    SpeciesConfig,
    WeatherConfig,
    WeatherPwsMeteobridgeConfig,
    WeatherPwsTempestConfig,
)


# ── Minimal Config fixture ────────────────────────────────────────────────────

@pytest.fixture
def test_cfg(tmp_path: Path) -> Config:
    """A fully-populated Config backed by *tmp_path* so no real files are touched."""
    detections_dir = tmp_path / "detections"
    detections_dir.mkdir()
    db_path = tmp_path / "test.db"

    return Config(
        paths=PathsConfig(
            detections_dir=detections_dir,
            db_path=db_path,
        ),
        audio=AudioConfig(
            sample_rate=48000,
            hop_seconds=1,
            device=None,
            source="sounddevice",
            rtsp=AudioRtspConfig(
                url="rtsp://localhost:554/test",
                transport="tcp",
                reconnect_delay_seconds=5,
                ffmpeg_path="ffmpeg",
            ),
            clip_seconds=15,
            pre_capture_seconds=0,
            capture_buffer_seconds=30,
            clip_mode="window",
            window_pad_seconds=0.5,
        ),
        inference=InferenceConfig(model="birdnet"),
        cross_validation=CrossValidationConfig(
            enabled=False,
            skip_threshold=0.90,
            on_disagree="drop",
            cv_min_confidence=0.01,
        ),
        filter=FilterConfig(enabled=False, cutoff_hz=150.0, order=5),
        retention=RetentionConfig(
            enabled=True,
            max_age_days=30,
            max_usage_percent=90.0,
            min_clips_per_species=5,
            run_interval_seconds=3600,
        ),
        log=LogConfig(
            enabled=False,
            path=tmp_path / "test.log",
            rotation="daily",
            max_size_bytes=10 * 1024 * 1024,
            backup_count=7,
            level="INFO",
        ),
        database=DatabaseConfig(
            type="sqlite",
            host="localhost",
            port=5432,
            name="birds",
            username="",
            password="",
            timescaledb=False,
        ),
        mqtt=MqttConfig(
            enabled=False,
            broker="localhost",
            port=1883,
            topic="birds/detections",
            username="",
            password="",
            retain=False,
        ),
        birdmap=BirdmapConfig(
            enabled=False,
            api_url="",
            api_key="",
            station_id=0,
            upload_audio=False,
        ),
        birdweather=BirdweatherConfig(
            enabled=False,
            token="",
            upload_audio=False,
        ),
        seasonal_filter=SeasonalFilterConfig(
            enabled=False,
            filter_json=Path("filters/uk_seasonal_filter.json"),
        ),
        nocturnal_filter=NocturnalFilterConfig(
            enabled=False,
            filter_json=Path("filters/uk_nocturnal_filter.json"),
        ),
        species_filter=SpeciesFilterConfig(exclude_status=()),
        defaults=SpeciesConfig(
            min_confidence=0.7,
            cooldown_seconds=60,
            min_detections=3,
            confirmation_window_seconds=9.0,
        ),
        general=GeneralConfig(timezone="UTC", station_name="Test Station"),
        location=LocationConfig(lat=51.5074, lon=-0.1278),  # London
        exclude=frozenset(),
        _species_overrides={},
        weather=WeatherConfig(
            enabled=False,
            provider="open_meteo",
            api_key="",
            cache_seconds=300,
            pws_plugin="",
            pws_meteobridge=WeatherPwsMeteobridgeConfig(
                host="",
                port=80,
                username="",
                password="",
                template="",
                wind_speed_unit="ms",
            ),
            pws_tempest=WeatherPwsTempestConfig(
                station_id=0,
                token="",
            ),
        ),
    )


# ── Audio fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_audio() -> np.ndarray:
    """3-second 48 kHz mono sine wave at 440 Hz, int16."""
    sr = 48000
    duration = 3.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    wave = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    return wave


# ── Mock Inferencer fixture ───────────────────────────────────────────────────

class MockInferencer:
    """Lightweight stand-in for a real Inferencer (BirdNET / Perch).

    Set ``.results`` before calling ``run_inference()`` to control what
    the mock returns.
    """

    window_seconds: float = 3.0

    def __init__(self, results: list[tuple[str, float]] | None = None) -> None:
        self.results: list[tuple[str, float]] = results or [("European Robin", 0.85)]

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        return list(self.results)

    def load_label_map(self) -> dict[str, str]:
        return {
            "European Robin": "Erithacus rubecula_European Robin",
            "Common Blackbird": "Turdus merula_Common Blackbird",
        }


@pytest.fixture
def mock_inferencer() -> MockInferencer:
    """Return a fresh MockInferencer with default results."""
    return MockInferencer()
