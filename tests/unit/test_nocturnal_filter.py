"""
tests/unit/test_nocturnal_filter.py — unit tests for nocturnal_filter.py

Fixed-window logic is tested deterministically.  The sunset_sunrise window
type is tested with real astral calculations at a known location and a
manually-chosen datetime that is unambiguously daytime or night-time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nocturnal_filter import NocturnalFilter


# ── Helpers ───────────────────────────────────────────────────────────────────

_LONDON_LAT = 51.5074
_LONDON_LON = -0.1278
_LONDON_TZ  = "Europe/London"


def _make_filter_json(tmp_path: Path, species_data: dict) -> Path:
    p = tmp_path / "nocturnal.json"
    p.write_text(json.dumps({"species": species_data}), encoding="utf-8")
    return p


def _make_filter(tmp_path: Path, species_data: dict, **kwargs) -> NocturnalFilter:
    """Build a NocturnalFilter with test data."""
    json_path = _make_filter_json(tmp_path, species_data)
    return NocturnalFilter(
        enabled=True,
        json_path=json_path,
        lat=kwargs.get("lat", _LONDON_LAT),
        lon=kwargs.get("lon", _LONDON_LON),
        timezone_str=kwargs.get("timezone_str", _LONDON_TZ),
        species_overrides=kwargs.get("species_overrides", {}),
    )


# ── Disabled filter ───────────────────────────────────────────────────────────

class TestNocturnalFilterDisabled:
    def test_always_allows_when_disabled(self, tmp_path):
        json_path = _make_filter_json(
            tmp_path,
            {"Tawny Owl": {"type": "fixed", "start": "22:00", "end": "04:00"}},
        )
        nf = NocturnalFilter(
            enabled=False,
            json_path=json_path,
            lat=_LONDON_LAT,
            lon=_LONDON_LON,
            timezone_str=_LONDON_TZ,
            species_overrides={},
        )
        ts = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert nf.check("Tawny Owl", ts) is True

    def test_disabled_when_json_missing(self, tmp_path):
        nf = NocturnalFilter(
            enabled=True,
            json_path=tmp_path / "missing.json",
            lat=_LONDON_LAT,
            lon=_LONDON_LON,
            timezone_str=_LONDON_TZ,
            species_overrides={},
        )
        assert nf.enabled is False


# ── Unrestricted species ──────────────────────────────────────────────────────

class TestUnrestrictedSpecies:
    def test_species_not_in_json_always_allowed(self, tmp_path):
        nf = _make_filter(tmp_path, {})
        ts = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert nf.check("European Robin", ts) is True


# ── Fixed window ──────────────────────────────────────────────────────────────

class TestFixedWindow:
    @pytest.fixture
    def nf_overnight(self, tmp_path):
        """Tawny Owl active 22:00–04:00 (overnight, start > end)."""
        return _make_filter(
            tmp_path,
            {"Tawny Owl": {"type": "fixed", "start": "22:00", "end": "04:00"}},
            timezone_str="UTC",
        )

    @pytest.fixture
    def nf_sameday(self, tmp_path):
        """Swift active 06:00–20:00 (same-day window, start < end)."""
        return _make_filter(
            tmp_path,
            {"Common Swift": {"type": "fixed", "start": "06:00", "end": "20:00"}},
            timezone_str="UTC",
        )

    # ── Overnight window ──────────────────────────────────────────────────────

    def test_overnight_allowed_after_start(self, nf_overnight):
        # 23:00 UTC — within [22:00, 04:00] window
        ts = datetime(2026, 6, 15, 23, 0, tzinfo=timezone.utc)
        assert nf_overnight.check("Tawny Owl", ts) is True

    def test_overnight_allowed_before_end(self, nf_overnight):
        # 02:00 UTC — within [22:00, 04:00] window
        ts = datetime(2026, 6, 15, 2, 0, tzinfo=timezone.utc)
        assert nf_overnight.check("Tawny Owl", ts) is True

    def test_overnight_allowed_at_midnight(self, nf_overnight):
        # 00:00 — within overnight window
        ts = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
        assert nf_overnight.check("Tawny Owl", ts) is True

    def test_overnight_blocked_during_day(self, nf_overnight):
        # 12:00 UTC — clearly daytime, outside the window
        ts = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert nf_overnight.check("Tawny Owl", ts) is False

    def test_overnight_blocked_just_before_start(self, nf_overnight):
        # 21:59 UTC — one minute before window starts
        ts = datetime(2026, 6, 15, 21, 59, tzinfo=timezone.utc)
        assert nf_overnight.check("Tawny Owl", ts) is False

    def test_overnight_blocked_just_after_end(self, nf_overnight):
        # 04:01 UTC — one minute after window ends
        ts = datetime(2026, 6, 15, 4, 1, tzinfo=timezone.utc)
        assert nf_overnight.check("Tawny Owl", ts) is False

    # ── Same-day window ───────────────────────────────────────────────────────

    def test_sameday_allowed_within_window(self, nf_sameday):
        ts = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert nf_sameday.check("Common Swift", ts) is True

    def test_sameday_blocked_outside_window(self, nf_sameday):
        ts = datetime(2026, 6, 15, 21, 0, tzinfo=timezone.utc)
        assert nf_sameday.check("Common Swift", ts) is False

    def test_sameday_allowed_at_start_boundary(self, nf_sameday):
        ts = datetime(2026, 6, 15, 6, 0, tzinfo=timezone.utc)
        assert nf_sameday.check("Common Swift", ts) is True

    def test_sameday_allowed_at_end_boundary(self, nf_sameday):
        ts = datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc)
        assert nf_sameday.check("Common Swift", ts) is True


# ── Sunset/sunrise window ─────────────────────────────────────────────────────

class TestSunsetSunriseWindow:
    """
    Use London coordinates on a mid-summer day where we know the rough
    sunrise (~04:30 BST / 03:30 UTC) and sunset (~21:15 BST / 20:15 UTC).
    2026-06-21 (summer solstice).
    """

    @pytest.fixture
    def nf_sunset_sunrise(self, tmp_path):
        """Tawny Owl active outside daytime (sunset_sunrise, no offsets)."""
        return _make_filter(
            tmp_path,
            {"Tawny Owl": {"type": "sunset_sunrise",
                           "sunset_offset_minutes": 0,
                           "sunrise_offset_minutes": 0}},
            timezone_str=_LONDON_TZ,
        )

    def test_blocked_during_midday(self, nf_sunset_sunrise):
        # 12:00 BST = 11:00 UTC — well within daytime
        ts = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
        assert nf_sunset_sunrise.check("Tawny Owl", ts) is False

    def test_allowed_at_midnight(self, nf_sunset_sunrise):
        # 00:00 BST = 23:00 UTC on the previous day — well outside daytime
        ts = datetime(2026, 6, 20, 23, 0, tzinfo=timezone.utc)
        assert nf_sunset_sunrise.check("Tawny Owl", ts) is True


# ── Config override takes priority ────────────────────────────────────────────

class TestConfigOverride:
    def test_config_override_replaces_json_window(self, tmp_path):
        """A per-species config override supersedes the JSON data file."""
        # JSON says Tawny Owl is active 22:00-04:00
        json_path = _make_filter_json(
            tmp_path,
            {"Tawny Owl": {"type": "fixed", "start": "22:00", "end": "04:00"}},
        )
        # Config override changes Tawny Owl to active 06:00-12:00 (same-day)
        nf = NocturnalFilter(
            enabled=True,
            json_path=json_path,
            lat=_LONDON_LAT,
            lon=_LONDON_LON,
            timezone_str="UTC",
            species_overrides={
                "Tawny Owl": {"active_hours": {"type": "fixed", "start": "06:00", "end": "12:00"}}
            },
        )

        # 09:00 UTC — inside override window → allowed
        ts_inside = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        assert nf.check("Tawny Owl", ts_inside) is True

        # 23:00 UTC — inside original JSON window but NOT override → blocked
        ts_night = datetime(2026, 6, 15, 23, 0, tzinfo=timezone.utc)
        assert nf.check("Tawny Owl", ts_night) is False

    def test_config_override_adds_new_species(self, tmp_path):
        """A config override can restrict a species not in the JSON at all."""
        nf = _make_filter(
            tmp_path,
            {},  # empty JSON
            timezone_str="UTC",
            species_overrides={
                "Robin": {"active_hours": {"type": "fixed", "start": "06:00", "end": "22:00"}}
            },
        )
        # Midnight → outside window → blocked
        ts_midnight = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
        assert nf.check("Robin", ts_midnight) is False

        # 10:00 → inside window → allowed
        ts_day = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
        assert nf.check("Robin", ts_day) is True


# ── Case-insensitive species lookup ──────────────────────────────────────────

class TestCaseInsensitiveLookup:
    def test_lookup_is_case_insensitive(self, tmp_path):
        nf = _make_filter(
            tmp_path,
            # JSON key uses title case
            {"Tawny Owl": {"type": "fixed", "start": "22:00", "end": "04:00"}},
            timezone_str="UTC",
        )
        # Queried with lower case — should still find the window
        ts_day = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert nf.check("tawny owl", ts_day) is False  # daytime → blocked
