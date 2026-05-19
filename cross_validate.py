"""
cross_validate.py — runs a second model to confirm bird detections.

After the primary model confirms a detection, the deferred-save task can
optionally re-run a secondary model on the same audio and compare the two
species calls. This helps filter false positives.

Agreement is checked at the BTO name level, so label differences between
BirdNET (IOC English, e.g. "European Robin") and Perch (eBird-based, maps to
BTO "Robin") are resolved through the shared BTO name map.

CrossValidationResult holds the full outcome:
  performed           — whether the secondary model actually ran
  skipped_high_conf   — True when primary confidence exceeded skip_threshold
                        (CV intentionally bypassed for high-confidence hits)
  secondary_* fields  — secondary model output; all None when CV didn't run
  agree               — True if both models named the same BTO species
  action              — "save" | "drop" | "flag"
  final_confidence    — confidence value written to the database

CrossValidator is instantiated once in detector.main() and shared across
all deferred-save worker threads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import numpy as np

from config import cfg, get_species_config

if TYPE_CHECKING:
    from inference import Inferencer

logger = logging.getLogger(__name__)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CrossValidationResult:
    """Full outcome of a cross-validation check for one detection.

    Fields map directly to columns in the detections table — see
    database.record_detection for the column mapping.
    """

    #: Whether the secondary model was actually invoked. False when CV is
    #: globally disabled, primary confidence exceeded skip_threshold, or
    #: an error occurred during the secondary run.
    performed: bool

    #: True when CV was skipped because primary confidence was high enough.
    skipped_high_conf: bool

    #: Name of the secondary model (e.g. "perch"). None when performed is False.
    secondary_model_name: str | None

    #: Top species label from the secondary model. None when CV didn't run or
    #: no result exceeded the confidence floor.
    secondary_species: str | None

    #: BTO-resolved name for secondary_species. None if unmapped or CV didn't run.
    secondary_bto_name: str | None

    #: Secondary model's top confidence score. None when CV didn't run.
    secondary_confidence: float | None

    #: True if both models agreed on the same BTO name. False if they disagreed
    #: or the secondary found nothing. None if CV was not performed.
    agree: bool | None

    #: What to do with this detection:
    #: "save" — write to DB and keep the clip
    #: "drop" — discard entirely
    #: "flag" — save but mark flagged=True for manual review
    action: str

    final_confidence: float


# ── Validator ─────────────────────────────────────────────────────────────────

class CrossValidator:
    """Runs a secondary model against a confirmed detection and decides what to do.

    Args:
        secondary_model:      The secondary Inferencer instance.
        secondary_bto_map:    Map from secondary model common names to BTO
                              British names (built the same way as the primary
                              model's BTO map in detector.main()).
        secondary_model_name: String identifier for the secondary model
                              ("birdnet" or "perch").
        min_conf_threshold:   Minimum confidence for a secondary result to count.
                              Defaults to cfg.defaults.min_confidence.
    """

    def __init__(
        self,
        secondary_model:      "Inferencer",
        secondary_bto_map:    dict[str, str],
        secondary_model_name: str,
        min_conf_threshold:   float | None = None,
    ) -> None:
        self._model            = secondary_model
        self._bto_map          = secondary_bto_map
        self._model_name       = secondary_model_name
        self._min_conf         = (
            min_conf_threshold
            if min_conf_threshold is not None
            else cfg.defaults.min_confidence
        )

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def window_seconds(self) -> float:
        """Audio window length required by the secondary model, in seconds."""
        return self._model.window_seconds

    def validate(
        self,
        audio:            np.ndarray,
        primary_species:  str,
        primary_bto_name: str | None,
        primary_conf:     float,
    ) -> CrossValidationResult:
        """Run the secondary model and return the validation outcome.

        Args:
            audio:            PCM audio at cfg.audio.sample_rate sized to the
                              secondary model's window_seconds. Shorter arrays
                              are passed through — most backends handle them.
            primary_species:  Raw common name from the primary model. Used as
                               a fallback if BTO mapping fails on both sides,
                               and as the key for per-species on_disagree overrides.
            primary_bto_name: BTO-resolved name for the primary detection.
                              If None, comparison falls back to raw names.
            primary_conf:     Primary model confidence. Checked against
                              cfg.cross_validation.skip_threshold.

        Returns:
            CrossValidationResult — always returned, never raises.
        """
        # Skip CV when the primary model is already very confident.
        if primary_conf >= cfg.cross_validation.skip_threshold:
            return CrossValidationResult(
                performed            = False,
                skipped_high_conf    = True,
                secondary_model_name = self._model_name,
                secondary_species    = None,
                secondary_bto_name   = None,
                secondary_confidence = None,
                agree                = None,
                action               = "save",
                final_confidence     = primary_conf,
            )

        # ── Run secondary model ───────────────────────────────────────────────
        try:
            candidates = self._model.run_inference(audio)
        except Exception:
            logger.exception(
                "Secondary model (%s) inference error during CV for %r — "
                "saving without cross-validation",
                self._model_name, primary_species,
            )
            return CrossValidationResult(
                performed            = False,
                skipped_high_conf    = False,
                secondary_model_name = self._model_name,
                secondary_species    = None,
                secondary_bto_name   = None,
                secondary_confidence = None,
                agree                = None,
                action               = "save",
                final_confidence     = primary_conf,
            )

        # Discard results below the confidence floor so noise doesn't count as agreement.
        candidates = [
            (s, c) for s, c in candidates if c >= self._min_conf
        ]

        # ── Determine agreement ───────────────────────────────────────────────
        if not candidates:
            # Secondary model found nothing above the threshold — treat as disagreement.
            sec_species    = None
            sec_bto_name   = None
            sec_confidence = None
            agree          = False
            logger.debug(
                "CV: secondary (%s) returned no candidates for %r — disagree",
                self._model_name, primary_species,
            )
        else:
            sec_species, sec_confidence = candidates[0]
            sec_bto_name = self._bto_map.get(sec_species)

            # Prefer BTO-level comparison — it bridges IOC and eBird label namespaces.
            if primary_bto_name and sec_bto_name:
                agree = primary_bto_name.lower() == sec_bto_name.lower()
            elif primary_bto_name is None and sec_bto_name is None:
                # Neither side mapped — fall back to raw common names.
                agree = primary_species.lower() == sec_species.lower()
            else:
                # One side mapped, the other not — can't reliably compare.
                agree = False

            logger.debug(
                "CV: primary=%r (bto=%r %.2f)  secondary=%r (bto=%r %.2f)  agree=%s",
                primary_species, primary_bto_name, primary_conf,
                sec_species,     sec_bto_name,     sec_confidence,
                agree,
            )

        # ── Determine action ──────────────────────────────────────────────────
        if agree:
            action           = "save"
            final_confidence = primary_conf
        else:
            # Check for a per-species override before falling back to the global setting.
            lookup_name = primary_species
            sc          = get_species_config(lookup_name)
            on_disagree = sc.on_disagree or cfg.cross_validation.on_disagree

            if on_disagree == "flag":
                action = "flag"
            else:
                action = "drop"

            final_confidence = primary_conf

        return CrossValidationResult(
            performed            = True,
            skipped_high_conf    = False,
            secondary_model_name = self._model_name,
            secondary_species    = sec_species,
            secondary_bto_name   = sec_bto_name,
            secondary_confidence = sec_confidence,
            agree                = agree,
            action               = action,
            final_confidence     = final_confidence,
        )
