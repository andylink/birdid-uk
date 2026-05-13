"""
tests/unit/test_species_filter.py — unit tests for species_filter.py

The three-stage matching logic is tested with a small synthetic BOU JSON
injected via monkeypatching the module-level ``_BOU_JSON`` path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import species_filter
from species_filter import (
    _status_excluded,
    build_bou_allowed_set,
    build_birdnet_to_bto_map,
)


# ── Helpers / fixtures ────────────────────────────────────────────────────────

# A small label map that covers the test species.
# Format: {birdnet_common_name: "Genus species_Common Name"}
_TEST_LABEL_MAP: dict[str, str] = {
    # Stage 0 match target (international_english_name differs from BTO name)
    "Eurasian Wigeon":   "Mareca penelope_Eurasian Wigeon",
    # Stage 1 match target (scientific name match)
    "European Robin":    "Erithacus rubecula_European Robin",
    # Stage 2 match target (common name fallback; scientific name intentionally wrong)
    "Skylark":           "Alauda arvensis_Skylark",
    # Extra label for the "unlisted" species tests
    "Common Buzzard":    "Buteo buteo_Common Buzzard",
    # Label for the force-include test
    "Rüppell's Vulture": "Gyps rueppelli_Rüppell's Vulture",
}

# A BOU JSON covering stage 0, 1, 2, excluded, and force-include cases.
_TEST_BOU_JSON: list[dict] = [
    # Stage 0 — has international_english_name which is in label_map
    {
        "name": "Wigeon",
        "scientific_name": "Mareca penelope",
        "british_list_status": "Winter Visitor",
        "international_english_name": "Eurasian Wigeon",
    },
    # Stage 1 — no international_english_name; matched via scientific name
    {
        "name": "Robin",
        "scientific_name": "Erithacus rubecula",
        "british_list_status": "Resident Breeder",
    },
    # Stage 2 — scientific name in JSON doesn't match any label (purposely "fake")
    # but BTO name "Skylark" matches the BirdNET common name directly
    {
        "name": "Skylark",
        "scientific_name": "Alauda arvensis.FAKE",
        "british_list_status": "Resident Breeder",
    },
    # Excluded by status
    {
        "name": "Cattle Egret",
        "scientific_name": "Bubulcus ibis",
        "british_list_status": "Accidental",
    },
    # Force-include override: status would be excluded but species_status_override saves it
    {
        "name": "Rüppell's Vulture",
        "scientific_name": "Gyps rueppelli",
        "british_list_status": "Accidental",
        "international_english_name": "Rüppell's Vulture",
    },
    # Unmatched — scientific name and common name both missing from label_map
    {
        "name": "Imaginary Bird",
        "scientific_name": "Fictus avium",
        "british_list_status": "Resident Breeder",
    },
]


@pytest.fixture
def bou_json_path(tmp_path: Path) -> Path:
    """Write _TEST_BOU_JSON to a temp file and return its path."""
    p = tmp_path / "test_bou.json"
    p.write_text(json.dumps(_TEST_BOU_JSON), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def patch_bou_json(bou_json_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace _BOU_JSON with our synthetic test file for every test in this module."""
    monkeypatch.setattr(species_filter, "_BOU_JSON", bou_json_path)


# ── _status_excluded ──────────────────────────────────────────────────────────

class TestStatusExcluded:
    def test_excluded_when_token_matches(self):
        assert _status_excluded("Accidental", frozenset({"accidental"})) is True

    def test_excluded_multi_token(self):
        # "Accidental" is one of two comma-split tokens
        assert _status_excluded("Accidental, Has Bred", frozenset({"accidental"})) is True

    def test_not_excluded_unrelated_status(self):
        assert _status_excluded("Scarce Visitor", frozenset({"accidental"})) is False

    def test_not_excluded_empty_exclude_tokens(self):
        assert _status_excluded("Accidental", frozenset()) is False

    def test_case_insensitive(self):
        assert _status_excluded("ACCIDENTAL", frozenset({"accidental"})) is True

    def test_slash_not_treated_as_separator(self):
        # "Passage/Winter Visitor" is a single concept — the slash is NOT a separator
        assert _status_excluded(
            "Passage/Winter Visitor", frozenset({"passage"})
        ) is False

    def test_whitespace_stripped(self):
        assert _status_excluded("  Accidental  , Has Bred", frozenset({"accidental"})) is True


# ── build_bou_allowed_set ─────────────────────────────────────────────────────

class TestBuildBouAllowedSet:
    def test_stage0_explicit_international_name(self):
        """Species with international_english_name matching a label → stage-0 hit."""
        allowed = build_bou_allowed_set(_TEST_LABEL_MAP)
        assert "Eurasian Wigeon" in allowed

    def test_stage1_scientific_name_match(self):
        """Species matched via scientific name → BirdNET common name added."""
        allowed = build_bou_allowed_set(_TEST_LABEL_MAP)
        assert "European Robin" in allowed

    def test_stage2_common_name_fallback(self):
        """Species with fake scientific name but matching common name → stage-2 hit."""
        allowed = build_bou_allowed_set(_TEST_LABEL_MAP)
        assert "Skylark" in allowed

    def test_excluded_by_status(self):
        """Species with excluded status not in allowed set."""
        allowed = build_bou_allowed_set(
            _TEST_LABEL_MAP, exclude_status=["Accidental"]
        )
        # Cattle Egret has status "Accidental" and no force_include
        # Its label would be absent in our label map anyway, but the point is
        # we test that excluded species don't appear
        # Rüppell's Vulture is also Accidental but listed in label_map
        assert "Rüppell's Vulture" not in allowed

    def test_force_include_overrides_exclusion(self):
        """force_include admits a species even when its status is excluded."""
        allowed = build_bou_allowed_set(
            _TEST_LABEL_MAP,
            exclude_status=["Accidental"],
            force_include=frozenset({"Rüppell's Vulture"}),
        )
        assert "Rüppell's Vulture" in allowed

    def test_unmatched_species_absent(self):
        """Species with no match in any stage not in allowed set."""
        allowed = build_bou_allowed_set(_TEST_LABEL_MAP)
        # "Common Buzzard" is in label_map but not in BOU JSON → not included
        # "Imaginary Bird" is in BOU JSON but not in label_map → not included
        assert "Common Buzzard" not in allowed

    def test_empty_label_map_returns_empty_set(self):
        """Empty label map → empty frozenset (all detections suppressed)."""
        allowed = build_bou_allowed_set({})
        assert allowed == frozenset()

    def test_returns_frozenset(self):
        allowed = build_bou_allowed_set(_TEST_LABEL_MAP)
        assert isinstance(allowed, frozenset)

    def test_no_exclusions_by_default(self):
        """Without exclude_status, even Accidental species are included if matchable."""
        allowed = build_bou_allowed_set(_TEST_LABEL_MAP)
        # Cattle Egret: not in label_map (no label "Cattle Egret") → unmatched anyway
        # Rüppell's Vulture: in label_map AND in BOU JSON → should appear
        assert "Rüppell's Vulture" in allowed


# ── build_birdnet_to_bto_map ──────────────────────────────────────────────────

class TestBuildBirdnetToBtoMap:
    def test_stage0_maps_international_name_to_bto_name(self):
        """Eurasian Wigeon → Wigeon (stage-0 match)."""
        mapping = build_birdnet_to_bto_map(_TEST_LABEL_MAP)
        assert mapping.get("Eurasian Wigeon") == "Wigeon"

    def test_stage1_maps_birdnet_common_to_bto_name(self):
        """European Robin → Robin (stage-1 scientific name match)."""
        mapping = build_birdnet_to_bto_map(_TEST_LABEL_MAP)
        assert mapping.get("European Robin") == "Robin"

    def test_stage2_maps_via_common_name(self):
        """Skylark → Skylark (stage-2 common name fallback)."""
        mapping = build_birdnet_to_bto_map(_TEST_LABEL_MAP)
        assert mapping.get("Skylark") == "Skylark"

    def test_excluded_species_absent_from_map(self):
        mapping = build_birdnet_to_bto_map(
            _TEST_LABEL_MAP, exclude_status=["Accidental"]
        )
        assert "Rüppell's Vulture" not in mapping

    def test_force_include_restores_excluded_species(self):
        mapping = build_birdnet_to_bto_map(
            _TEST_LABEL_MAP,
            exclude_status=["Accidental"],
            force_include=frozenset({"Rüppell's Vulture"}),
        )
        assert mapping.get("Rüppell's Vulture") == "Rüppell's Vulture"

    def test_empty_label_map_returns_empty_dict(self):
        mapping = build_birdnet_to_bto_map({})
        assert mapping == {}

    def test_returns_dict(self):
        mapping = build_birdnet_to_bto_map(_TEST_LABEL_MAP)
        assert isinstance(mapping, dict)
