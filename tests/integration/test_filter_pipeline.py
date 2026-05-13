"""
tests/integration/test_filter_pipeline.py — integration tests for the filter
pipeline as a whole.

Rather than exercising the full detector thread (which requires audio hardware,
sounddevice, etc.), these tests instantiate each filter component with
controlled state and verify how they interact when applied in sequence —
mirroring the order used in `detector._classify_loop`:

    exclude list → min_confidence → BOU allowlist → seasonal → nocturnal

The confirmation and cooldown stages are covered by the detector unit tests and
are not tested here.
"""

from __future__ import annotations

import json
import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import species_filter
from species_filter import build_bou_allowed_set, build_birdnet_to_bto_map
from seasonal_filter import SeasonalFilter, current_iso_week
from nocturnal_filter import NocturnalFilter
from config import SpeciesFilterConfig, SpeciesConfig


# ── Shared label map used across all tests ───────────────────────────────────
#
# Keys are "scientific_name_Common name" strings (BirdNET label format).
# Values are the BirdNET common names (the part after "_").

_LABEL_MAP: dict[str, str] = {
    "European Robin":   "Erithacus rubecula_European Robin",
    "Common Blackbird": "Turdus merula_Common Blackbird",
    "Eurasian Curlew":  "Numenius arquata_Eurasian Curlew",
    "Common Cuckoo":    "Cuculus canorus_Common Cuckoo",
    "Barn Owl":         "Tyto alba_Barn Owl",
}


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _write_bou_json(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps(entries), encoding="utf-8")


def _write_seasonal_json(path: Path, species_weeks: dict[str, list[int]]) -> None:
    data = {"species": species_weeks, "_metadata": {"week_scale": "1-52"}}
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_nocturnal_json(path: Path, species_windows: dict[str, dict]) -> None:
    data = {"species": species_windows}
    path.write_text(json.dumps(data), encoding="utf-8")


# ── BOU allowlist ─────────────────────────────────────────────────────────────

class TestBouAllowlistIntegration:
    """Test BOU allowlist + BTO name map together."""

    @pytest.fixture(autouse=True)
    def _patch_bou_json(self, monkeypatch, tmp_path):
        json_path = tmp_path / "species.json"
        _write_bou_json(json_path, [
            {
                "name": "Robin",
                "scientific_name": "Erithacus rubecula",
                "international_english_name": "European Robin",
                "british_list_status": "Common",
                "uk_bocc": "Green",
            },
            {
                "name": "Blackbird",
                "scientific_name": "Turdus merula",
                "international_english_name": None,
                "british_list_status": "Common",
                "uk_bocc": "Green",
            },
            {
                "name": "Curlew",
                "scientific_name": "Numenius arquata",
                "international_english_name": None,
                "british_list_status": "Accidental",
                "uk_bocc": "Red",
            },
        ])
        monkeypatch.setattr(species_filter, "_BOU_JSON", json_path)

    def test_allowed_species_in_set(self):
        allowed = build_bou_allowed_set(_LABEL_MAP)
        assert "European Robin" in allowed
        assert "Common Blackbird" in allowed

    def test_excluded_status_not_in_set(self):
        allowed = build_bou_allowed_set(_LABEL_MAP, exclude_status=["Accidental"])
        assert "Eurasian Curlew" not in allowed

    def test_non_bou_species_not_in_set(self):
        allowed = build_bou_allowed_set(_LABEL_MAP)
        assert "Common Cuckoo" not in allowed

    def test_bto_map_translates_common_names(self):
        bto_map = build_birdnet_to_bto_map(_LABEL_MAP)
        assert bto_map.get("European Robin") == "Robin"
        assert bto_map.get("Common Blackbird") == "Blackbird"

    def test_pipeline_filters_out_unlisted(self):
        """Simulates the BOU filter step in _classify_loop."""
        allowed = build_bou_allowed_set(_LABEL_MAP)
        candidates = [
            ("European Robin",  0.85),
            ("Common Blackbird", 0.91),
            ("Common Cuckoo",    0.72),   # not in BOU JSON
        ]
        filtered = [(s, c) for s, c in candidates if s in allowed]
        assert len(filtered) == 2
        species_out = {s for s, _ in filtered}
        assert "Common Cuckoo" not in species_out

    def test_force_include_overrides_exclusion(self):
        """force_include admits a species regardless of its status.
        The value must match the BTO 'name' field (not the BirdNET common name).
        """
        allowed = build_bou_allowed_set(
            _LABEL_MAP,
            exclude_status=["Accidental"],
            force_include=frozenset({"Curlew"}),  # BTO name, not BirdNET label
        )
        assert "Eurasian Curlew" in allowed


# ── Seasonal filter integration ───────────────────────────────────────────────

class TestSeasonalFilterIntegration:
    @pytest.fixture
    def seasonal_json(self, tmp_path) -> Path:
        path = tmp_path / "seasonal.json"
        _write_seasonal_json(path, {
            "Common Cuckoo": list(range(17, 31)),    # weeks 17–30 (Apr–Jul approx)
            "Barn Owl":      list(range(1, 53)),     # year-round in JSON
        })
        return path

    def test_in_season_species_passes(self, seasonal_json):
        sf = SeasonalFilter(enabled=True, json_path=seasonal_json)
        # Week 20 is in Cuckoo's allowed range
        assert sf.check("Common Cuckoo", 20) is True

    def test_out_of_season_blocked(self, seasonal_json):
        sf = SeasonalFilter(enabled=True, json_path=seasonal_json)
        # Week 5 is not in Cuckoo's range
        assert sf.check("Common Cuckoo", 5) is False

    def test_unrestricted_species_always_passes(self, seasonal_json):
        """Species not in the JSON → no restriction."""
        sf = SeasonalFilter(enabled=True, json_path=seasonal_json)
        assert sf.check("European Robin", 5) is True

    def test_disabled_filter_always_passes(self, seasonal_json):
        sf = SeasonalFilter(enabled=False, json_path=seasonal_json)
        assert sf.check("Common Cuckoo", 5) is True

    def test_pipeline_filters_out_of_season(self, seasonal_json):
        """Simulates seasonal step in _classify_loop."""
        sf = SeasonalFilter(enabled=True, json_path=seasonal_json)
        week = 5  # winter → Cuckoo out of season

        candidates = [
            ("European Robin", 0.85),   # unrestricted
            ("Common Cuckoo",  0.72),   # out of season
        ]
        filtered = [(s, c) for s, c in candidates if sf.check(s, week)]
        assert len(filtered) == 1
        assert filtered[0][0] == "European Robin"


# ── Nocturnal filter integration ──────────────────────────────────────────────

class TestNocturnalFilterIntegration:
    @pytest.fixture
    def nocturnal_json(self, tmp_path) -> Path:
        path = tmp_path / "nocturnal.json"
        _write_nocturnal_json(path, {
            "Barn Owl": {"type": "fixed", "start": "21:00", "end": "06:00"},
        })
        return path

    def test_nocturnal_species_blocked_during_day(self, nocturnal_json):
        """Barn Owl at noon should be blocked."""
        nf = NocturnalFilter(
            enabled=True, json_path=nocturnal_json,
            lat=51.5, lon=-0.1, timezone_str="UTC", species_overrides={},
        )
        midday = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        assert nf.check("Barn Owl", midday) is False

    def test_nocturnal_species_allowed_at_night(self, nocturnal_json):
        """Barn Owl at 22:00 UTC should pass."""
        nf = NocturnalFilter(
            enabled=True, json_path=nocturnal_json,
            lat=51.5, lon=-0.1, timezone_str="UTC", species_overrides={},
        )
        night = datetime(2026, 5, 13, 22, 0, 0, tzinfo=timezone.utc)
        assert nf.check("Barn Owl", night) is True

    def test_non_nocturnal_always_passes(self, nocturnal_json):
        """European Robin is not in nocturnal JSON → always allowed."""
        nf = NocturnalFilter(
            enabled=True, json_path=nocturnal_json,
            lat=51.5, lon=-0.1, timezone_str="UTC", species_overrides={},
        )
        midday = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        assert nf.check("European Robin", midday) is True

    def test_disabled_filter_always_passes(self, nocturnal_json):
        nf = NocturnalFilter(
            enabled=False, json_path=nocturnal_json,
            lat=51.5, lon=-0.1, timezone_str="UTC", species_overrides={},
        )
        midday = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        assert nf.check("Barn Owl", midday) is True

    def test_pipeline_filters_nocturnal_during_day(self, nocturnal_json):
        """Simulates nocturnal step in _classify_loop."""
        nf = NocturnalFilter(
            enabled=True, json_path=nocturnal_json,
            lat=51.5, lon=-0.1, timezone_str="UTC", species_overrides={},
        )
        midday = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)

        candidates = [
            ("European Robin", 0.85),   # not nocturnal
            ("Barn Owl",       0.73),   # nocturnal → blocked at noon
        ]
        filtered = [(s, c) for s, c in candidates if nf.check(s, midday)]
        assert len(filtered) == 1
        assert filtered[0][0] == "European Robin"


# ── Full pipeline integration ─────────────────────────────────────────────────

class TestFullPipelineIntegration:
    """Simulate all filter stages running in sequence on a candidate list."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        # BOU allowlist JSON
        bou_json = tmp_path / "bou.json"
        _write_bou_json(bou_json, [
            {
                "name": "Robin",
                "scientific_name": "Erithacus rubecula",
                "international_english_name": "European Robin",
                "british_list_status": "Common",
            },
            {
                "name": "Blackbird",
                "scientific_name": "Turdus merula",
                "international_english_name": None,
                "british_list_status": "Accidental",   # will be excluded
            },
        ])
        monkeypatch.setattr(species_filter, "_BOU_JSON", bou_json)

        # Seasonal filter JSON
        seasonal_json = tmp_path / "seasonal.json"
        _write_seasonal_json(seasonal_json, {
            "European Robin": list(range(40, 53)) + list(range(1, 10)),  # autumn/winter
        })
        self.sf = SeasonalFilter(enabled=True, json_path=seasonal_json)

        # Nocturnal filter JSON
        nocturnal_json = tmp_path / "nocturnal.json"
        _write_nocturnal_json(nocturnal_json, {})  # no nocturnal species
        self.nf = NocturnalFilter(
            enabled=True, json_path=nocturnal_json,
            lat=51.5, lon=-0.1, timezone_str="UTC", species_overrides={},
        )

        # Build BOU structures using the patched JSON
        self.bou_allowed = build_bou_allowed_set(_LABEL_MAP, exclude_status=["Accidental"])

    def _apply_pipeline(
        self,
        candidates: list[tuple[str, float]],
        ts: datetime,
        week: int,
        exclude: frozenset[str] = frozenset(),
        min_confidence: float = 0.7,
    ) -> list[tuple[str, float]]:
        """Apply all filter stages in sequence and return surviving candidates."""
        # 1. Exclude list
        if exclude:
            candidates = [(s, c) for s, c in candidates if s.lower() not in exclude]

        # 2. Per-species min_confidence
        candidates = [(s, c) for s, c in candidates if c >= min_confidence]

        # 3. BOU allowlist
        candidates = [(s, c) for s, c in candidates if s in self.bou_allowed]

        # 4. Seasonal filter
        if self.sf.enabled:
            candidates = [(s, c) for s, c in candidates if self.sf.check(s, week)]

        # 5. Nocturnal filter
        if self.nf.enabled:
            candidates = [(s, c) for s, c in candidates if self.nf.check(s, ts)]

        return candidates

    def test_compliant_species_survives_all_filters(self):
        """A species passing every filter reaches the confirmation stage."""
        ts = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)  # week ~42 = in Robin's range
        week = 42
        candidates = [("European Robin", 0.85)]

        result = self._apply_pipeline(candidates, ts, week)
        assert len(result) == 1
        assert result[0][0] == "European Robin"

    def test_species_on_exclude_list_removed(self):
        ts = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        week = 42
        candidates = [("European Robin", 0.85)]

        result = self._apply_pipeline(
            candidates, ts, week, exclude=frozenset({"european robin"})
        )
        assert result == []

    def test_low_confidence_removed(self):
        ts = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        week = 42
        candidates = [("European Robin", 0.50)]   # below 0.7 threshold

        result = self._apply_pipeline(candidates, ts, week)
        assert result == []

    def test_non_bou_species_removed(self):
        """Common Cuckoo is not in our BOU JSON → removed at BOU stage."""
        ts = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
        week = 20
        candidates = [("Common Cuckoo", 0.80)]   # high confidence but not in BOU list

        result = self._apply_pipeline(candidates, ts, week)
        assert result == []

    def test_excluded_bou_status_removes_species(self):
        """Common Blackbird has 'Accidental' status → excluded at BOU stage."""
        ts = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
        week = 20
        candidates = [("Common Blackbird", 0.90)]

        result = self._apply_pipeline(candidates, ts, week)
        assert result == []

    def test_out_of_season_species_removed(self):
        """European Robin in summer (week 25) is out of its JSON season."""
        ts = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
        week = 25  # summer — Robin's JSON range is weeks 40-52 + 1-9
        candidates = [("European Robin", 0.85)]

        result = self._apply_pipeline(candidates, ts, week)
        assert result == []

    def test_multiple_candidates_filtered_independently(self):
        """Each candidate is evaluated independently; survivors form the output."""
        ts = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        week = 42
        candidates = [
            ("European Robin",   0.85),  # passes all
            ("Common Blackbird", 0.90),  # blocked by BOU (Accidental status)
            ("Common Cuckoo",    0.80),  # not in BOU JSON
            ("European Robin",   0.50),  # duplicate, blocked by confidence
        ]
        result = self._apply_pipeline(candidates, ts, week)
        species = [s for s, _ in result]
        assert species == ["European Robin"]   # only the high-conf Robin survives

    def test_empty_candidates_stays_empty(self):
        ts = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        assert self._apply_pipeline([], ts, 42) == []
