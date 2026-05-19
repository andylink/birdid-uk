"""
Unit tests for CrossValidator.validate().

Tests use a local mock inferencer and patch cross_validate.cfg /
cross_validate.get_species_config so the real config.toml doesn't affect outcomes.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

import cross_validate as cv_mod
from cross_validate import CrossValidator, CrossValidationResult
from config import CrossValidationConfig, SpeciesConfig


# ── Local mock inferencer ─────────────────────────────────────────────────────

class _MockInferencer:
    """Minimal stand-in for a real Inferencer."""

    window_seconds: float = 3.0

    def __init__(self, results: list[tuple[str, float]] | None = None) -> None:
        self.results: list[tuple[str, float]] = results if results is not None else []

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        return list(self.results)

    def load_label_map(self) -> dict[str, str]:
        return {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _species_cfg(on_disagree: str | None = None) -> SpeciesConfig:
    return SpeciesConfig(
        min_confidence=0.7,
        cooldown_seconds=60,
        min_detections=3,
        confirmation_window_seconds=9.0,
        on_disagree=on_disagree,
    )


def _build_cfg(test_cfg, *, on_disagree: str = "drop") -> object:
    """Return a copy of test_cfg with cross_validation.on_disagree overridden."""
    new_cv = dataclasses.replace(test_cfg.cross_validation, on_disagree=on_disagree)
    return dataclasses.replace(test_cfg, cross_validation=new_cv)


@pytest.fixture(autouse=True)
def _patch_cv_module(monkeypatch, test_cfg):
    """Patch cfg and get_species_config for every test in this file."""
    monkeypatch.setattr(cv_mod, "cfg", test_cfg)
    monkeypatch.setattr(cv_mod, "get_species_config", lambda _name: _species_cfg())


# ── High-confidence shortcut ──────────────────────────────────────────────────

class TestSkipThreshold:
    def test_at_threshold_skips_cv(self, test_cfg, sample_audio):
        """A detection at or above skip_threshold should bypass CV entirely."""
        sec = _MockInferencer(results=[("Common Blackbird", 0.85)])
        v = CrossValidator(sec, {}, "birdnet", min_conf_threshold=0.5)

        result = v.validate(
            sample_audio, "European Robin", "Robin",
            primary_conf=test_cfg.cross_validation.skip_threshold,
        )

        assert result.performed is False
        assert result.skipped_high_conf is True
        assert result.action == "save"
        assert result.final_confidence == test_cfg.cross_validation.skip_threshold
        assert result.agree is None
        assert result.secondary_species is None

    def test_above_threshold_skips_cv(self, sample_audio):
        sec = _MockInferencer(results=[("European Robin", 0.95)])
        v = CrossValidator(sec, {}, "birdnet", min_conf_threshold=0.5)

        result = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.99)

        assert result.skipped_high_conf is True
        assert result.performed is False

    def test_just_below_threshold_runs_cv(self, test_cfg, sample_audio):
        """A confidence just below skip_threshold should trigger CV."""
        bto = {"European Robin": "Robin"}
        sec = _MockInferencer(results=[("European Robin", 0.8)])
        v = CrossValidator(sec, bto, "birdnet", min_conf_threshold=0.5)

        result = v.validate(
            sample_audio, "European Robin", "Robin",
            primary_conf=test_cfg.cross_validation.skip_threshold - 0.01,
        )

        assert result.performed is True
        assert result.skipped_high_conf is False


# ── Agreement logic ───────────────────────────────────────────────────────────

class TestAgreement:
    def test_bto_names_match(self, sample_audio):
        """Both models resolving to the same BTO name counts as agreement → save."""
        bto = {"European Robin": "Robin"}
        sec = _MockInferencer(results=[("European Robin", 0.82)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.performed is True
        assert r.agree is True
        assert r.action == "save"
        assert r.secondary_model_name == "perch"
        assert r.secondary_species == "European Robin"
        assert r.secondary_bto_name == "Robin"
        assert r.secondary_confidence == pytest.approx(0.82)

    def test_bto_names_differ_drop(self, sample_audio):
        """Models disagree and global on_disagree='drop' → action='drop'."""
        bto = {"Common Blackbird": "Blackbird"}
        sec = _MockInferencer(results=[("Common Blackbird", 0.8)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.agree is False
        assert r.action == "drop"

    def test_bto_names_differ_global_flag(self, monkeypatch, test_cfg, sample_audio):
        """Global on_disagree='flag' → disagreements are flagged rather than dropped."""
        monkeypatch.setattr(cv_mod, "cfg", _build_cfg(test_cfg, on_disagree="flag"))

        bto = {"Common Blackbird": "Blackbird"}
        sec = _MockInferencer(results=[("Common Blackbird", 0.8)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.agree is False
        assert r.action == "flag"

    def test_per_species_on_disagree_flag_overrides_global_drop(
        self, monkeypatch, sample_audio
    ):
        """A per-species on_disagree setting overrides the global default."""
        monkeypatch.setattr(
            cv_mod, "get_species_config", lambda _name: _species_cfg(on_disagree="flag")
        )

        bto = {"Common Blackbird": "Blackbird"}
        sec = _MockInferencer(results=[("Common Blackbird", 0.8)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.agree is False
        assert r.action == "flag"

    def test_case_insensitive_bto_comparison(self, sample_audio):
        """BTO name matching should be case-insensitive."""
        bto = {"European Robin": "robin"}   # lowercase on secondary side
        sec = _MockInferencer(results=[("European Robin", 0.8)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.agree is True

    def test_both_bto_none_same_raw_name_agree(self, sample_audio):
        """If neither side has a BTO name, fall back to comparing raw labels."""
        sec = _MockInferencer(results=[("European Robin", 0.8)])
        v = CrossValidator(sec, {}, "perch", min_conf_threshold=0.5)

        # primary_bto_name=None; secondary not in bto_map so also None
        r = v.validate(sample_audio, "European Robin", None, primary_conf=0.75)

        assert r.agree is True

    def test_both_bto_none_different_raw_disagree(self, sample_audio):
        """No BTO names on either side and different raw labels → disagree."""
        sec = _MockInferencer(results=[("Common Blackbird", 0.8)])
        v = CrossValidator(sec, {}, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", None, primary_conf=0.75)

        assert r.agree is False

    def test_one_bto_none_cannot_compare_disagree(self, sample_audio):
        """If only one side has a BTO name, comparison is not possible → disagree."""
        sec = _MockInferencer(results=[("European Robin", 0.8)])
        v = CrossValidator(sec, {}, "perch", min_conf_threshold=0.5)

        # primary has BTO="Robin", secondary has no BTO mapping
        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.agree is False

    def test_final_confidence_equals_primary_conf(self, sample_audio):
        """final_confidence should always reflect the primary model's confidence."""
        bto = {"European Robin": "Robin"}
        sec = _MockInferencer(results=[("European Robin", 0.99)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.final_confidence == pytest.approx(0.75)


# ── Empty / below-threshold secondary results ─────────────────────────────────

class TestNoSecondaryResults:
    def test_empty_result_disagrees(self, sample_audio):
        """No candidates from the secondary model → treated as disagreement."""
        sec = _MockInferencer(results=[])
        v = CrossValidator(sec, {}, "birdnet", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.performed is True
        assert r.agree is False
        assert r.secondary_species is None
        assert r.secondary_confidence is None

    def test_all_below_min_conf(self, sample_audio):
        """All secondary results below min_conf → no usable candidate → disagree."""
        sec = _MockInferencer(results=[("European Robin", 0.3), ("Song Thrush", 0.2)])
        v = CrossValidator(sec, {}, "birdnet", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.agree is False
        assert r.secondary_species is None

    def test_first_result_above_threshold_used(self, sample_audio):
        """The first result above min_conf is used; lower-ranked candidates are ignored."""
        bto = {"European Robin": "Robin", "Song Thrush": "Song Thrush"}
        sec = _MockInferencer(
            results=[("European Robin", 0.85), ("Song Thrush", 0.75)]
        )
        v = CrossValidator(sec, bto, "birdnet", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.secondary_species == "European Robin"
        assert r.agree is True

    def test_first_result_below_second_above(self, sample_audio):
        """If the top result is below threshold but the next is not, the next is used."""
        bto = {"Song Thrush": "Song Thrush"}
        sec = _MockInferencer(
            results=[("European Robin", 0.3), ("Song Thrush", 0.8)]
        )
        v = CrossValidator(sec, bto, "birdnet", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        # After filtering, the only candidate is Song Thrush
        assert r.secondary_species == "Song Thrush"
        assert r.agree is False   # primary BTO="Robin" ≠ "Song Thrush"


# ── Inference error ───────────────────────────────────────────────────────────

class TestInferenceError:
    def test_exception_yields_save_no_cv(self, sample_audio):
        """If the secondary model raises, the detection is saved without CV."""
        class _Broken:
            window_seconds = 3.0
            def run_inference(self, audio):
                raise RuntimeError("GPU exploded")
            def load_label_map(self):
                return {}

        v = CrossValidator(_Broken(), {}, "perch", min_conf_threshold=0.5)
        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.performed is False
        assert r.skipped_high_conf is False
        assert r.action == "save"
        assert r.agree is None
        assert r.secondary_species is None


# ── Miscellaneous ─────────────────────────────────────────────────────────────

class TestMiscellaneous:
    def test_window_seconds_proxied_from_model(self):
        """window_seconds should delegate to the secondary model."""
        sec = _MockInferencer()
        sec.window_seconds = 5.0
        v = CrossValidator(sec, {}, "perch", min_conf_threshold=0.5)
        assert v.window_seconds == pytest.approx(5.0)

    def test_primary_species_used_for_config_lookup(self, monkeypatch, sample_audio):
        """primary_species is passed to get_species_config for per-species on_disagree lookup."""
        seen_names: list[str] = []

        def tracking_gsc(name: str) -> SpeciesConfig:
            seen_names.append(name)
            return _species_cfg()

        monkeypatch.setattr(cv_mod, "get_species_config", tracking_gsc)

        bto = {"Common Blackbird": "Blackbird"}
        sec = _MockInferencer(results=[("Common Blackbird", 0.8)])
        v = CrossValidator(sec, bto, "perch", min_conf_threshold=0.5)

        v.validate(
            sample_audio,
            "European Robin",
            "Robin",
            primary_conf=0.75,
        )

        assert "European Robin" in seen_names

    def test_secondary_model_name_stored(self, sample_audio):
        """The secondary model name passed to the constructor should appear in results."""
        sec = _MockInferencer(results=[])
        v = CrossValidator(sec, {}, "my_model_v2", min_conf_threshold=0.5)

        r = v.validate(sample_audio, "European Robin", "Robin", primary_conf=0.75)

        assert r.secondary_model_name == "my_model_v2"
