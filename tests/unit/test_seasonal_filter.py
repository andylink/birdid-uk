"""
tests/unit/test_seasonal_filter.py — unit tests for seasonal_filter.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from filters.seasonal_filter import SeasonalFilter, current_iso_week


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_filter_json(tmp_path: Path, species_data: dict[str, list[int]]) -> Path:
    """Write a minimal uk_seasonal_filter.json to *tmp_path* and return its path."""
    payload = {
        "_metadata": {"week_scale": "ISO 8601 (1-52)"},
        "species": species_data,
    }
    p = tmp_path / "seasonal.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ── current_iso_week ──────────────────────────────────────────────────────────

class TestCurrentIsoWeek:
    def test_returns_int_in_range(self):
        week = current_iso_week()
        assert 1 <= week <= 52

    def test_week_53_clamped_to_52(self):
        # 2020-12-31 is in ISO week 53 of the year 2020
        ts = datetime(2020, 12, 31, tzinfo=timezone.utc)
        assert current_iso_week(ts) == 52

    def test_week_1_passed_through(self):
        # 2026-01-05 is week 2 of 2026; 2026-01-01 is week 1
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert current_iso_week(ts) == 1

    def test_normal_week_unchanged(self):
        # 2026-05-13 is week 20
        ts = datetime(2026, 5, 13, tzinfo=timezone.utc)
        week = current_iso_week(ts)
        assert week == ts.isocalendar()[1]  # 20, which is < 53


# ── SeasonalFilter ────────────────────────────────────────────────────────────

class TestSeasonalFilterDisabled:
    def test_check_always_true_when_disabled(self, tmp_path):
        sf = SeasonalFilter(enabled=False)
        # Even if the species would normally be restricted, disabled filter passes all
        assert sf.check("Osprey", 1) is True
        assert sf.check("Osprey", 52) is True

    def test_enabled_attribute_is_false(self, tmp_path):
        sf = SeasonalFilter(enabled=False)
        assert sf.enabled is False


class TestSeasonalFilterMissingJson:
    def test_disables_gracefully_when_json_missing(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        sf = SeasonalFilter(enabled=True, json_path=missing)
        # Should degrade gracefully — enabled becomes False
        assert sf.enabled is False
        # And check() passes everything through
        assert sf.check("Osprey", 20) is True


class TestSeasonalFilterLogic:
    @pytest.fixture
    def sf(self, tmp_path):
        """SeasonalFilter with 'Osprey' restricted to weeks 20-35."""
        json_path = _make_filter_json(tmp_path, {"Osprey": list(range(20, 36))})
        return SeasonalFilter(enabled=True, json_path=json_path)

    def test_species_in_season_allowed(self, sf):
        assert sf.check("Osprey", 20) is True
        assert sf.check("Osprey", 27) is True
        assert sf.check("Osprey", 35) is True

    def test_species_out_of_season_blocked(self, sf):
        assert sf.check("Osprey", 1) is False
        assert sf.check("Osprey", 19) is False
        assert sf.check("Osprey", 36) is False
        assert sf.check("Osprey", 52) is False

    def test_unrestricted_species_always_allowed(self, sf):
        """Species absent from JSON have no restriction → always True."""
        assert sf.check("European Robin", 1) is True
        assert sf.check("European Robin", 52) is True

    def test_week_boundary_inclusive(self, sf):
        """Week 20 and 35 are the inclusive bounds."""
        assert sf.check("Osprey", 20) is True
        assert sf.check("Osprey", 35) is True
        assert sf.check("Osprey", 19) is False
        assert sf.check("Osprey", 36) is False

    def test_multiple_species(self, tmp_path):
        """Two species with different seasons don't interfere."""
        json_path = _make_filter_json(tmp_path, {
            "Osprey": list(range(20, 36)),
            "Fieldfare": list(range(1, 16)) + list(range(40, 53)),
        })
        sf = SeasonalFilter(enabled=True, json_path=json_path)

        assert sf.check("Osprey", 25) is True
        assert sf.check("Fieldfare", 25) is False  # 25 is summer, not in Fieldfare's range
        assert sf.check("Fieldfare", 10) is True
        assert sf.check("Fieldfare", 45) is True

    def test_week_53_handling(self, tmp_path):
        """Week values > 52 are outside valid range — clamping happens at caller level."""
        json_path = _make_filter_json(tmp_path, {"Osprey": [52]})
        sf = SeasonalFilter(enabled=True, json_path=json_path)
        # clamped week 53 → 52: check with week=52 should pass
        assert sf.check("Osprey", 52) is True
        assert sf.check("Osprey", 51) is False
