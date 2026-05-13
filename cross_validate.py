"""
cross_validate.py — dual-model cross-validation for confirmed bird detections.

After the primary model confirms a detection (via the confirmation filter in
``detector._classify_loop``), the deferred-save task can optionally re-run the
*secondary* model on the same audio window and compare the two species calls.

Agreement is evaluated at the BTO-name level so that label-namespace
differences between BirdNET (IOC English, e.g. "European Robin") and Perch
(eBird-based, maps to BTO "Robin") are bridged through the shared BTO map.

Outcome
-------
:class:`CrossValidationResult` encodes the full outcome:

* ``performed``  — whether the secondary model was actually invoked
* ``skipped_high_conf`` — True when the primary confidence exceeded
  ``cfg.cross_validation.skip_threshold``; the detection is saved without CV
* ``secondary_*`` fields — secondary model output (species, BTO name,
  confidence); all ``None`` when CV was not performed
* ``agree``      — ``True`` if both models resolved to the same BTO name
* ``action``     — ``"save"`` | ``"drop"`` | ``"flag"``
* ``final_confidence`` — the primary model confidence value to write to the database;

The :class:`CrossValidator` class is instantiated once in ``detector.main()``
and stored as a module-level variable so it is shared across all deferred-save
worker threads.
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
    """Full outcome of a cross-validation check for one confirmed detection.

    Fields are written directly to the ``detections`` table by
    ``database.record_detection``; see that function's docstring for the
    column mapping.
    """

    #: Was the secondary model actually invoked?  ``False`` when CV is
    #: globally disabled, when the primary confidence exceeded
    #: ``skip_threshold``, or when an error prevented the secondary run.
    performed: bool

    #: ``True`` when the skip-threshold shortcut fired (primary conf was high
    #: enough that CV was intentionally bypassed).
    skipped_high_conf: bool

    #: Name of the secondary model used (e.g. ``"perch"``).  ``None`` when
    #: ``performed`` is ``False``.
    secondary_model_name: str | None

    #: Raw common-name label returned by the secondary model's top result.
    #: ``None`` when the secondary produced no results above the confidence
    #: floor, or when CV was not performed.
    secondary_species: str | None

    #: BTO-resolved name for ``secondary_species`` (via the secondary model's
    #: BTO map).  ``None`` if the species couldn't be mapped or CV wasn't run.
    secondary_bto_name: str | None

    #: Confidence score of the secondary model's top result.  ``None`` when
    #: no secondary result was produced or CV wasn't run.
    secondary_confidence: float | None

    #: ``True`` if both models resolved to the same BTO name.  ``False`` if
    #: they disagreed or the secondary found nothing.  ``None`` if CV was not
    #: performed (disabled / skipped).
    agree: bool | None

    #: Decision taken:
    #: * ``"save"``  — proceed to save the detection normally
    #: * ``"drop"``  — discard (no clip written, no DB row)
    #: * ``"flag"``  — save but mark ``flagged = True`` for manual review
    action: str

    final_confidence: float


# ── Validator ─────────────────────────────────────────────────────────────────

class CrossValidator:
    """Validates a confirmed detection against the secondary model.

    Args:
        secondary_model:      The secondary :class:`~inference.Inferencer`.
        secondary_bto_map:    Mapping from secondary model common names to BTO
                              British names, built the same way as the primary
                              model's BTO map in ``detector.main()``.
        secondary_model_name: String name of the secondary model
                              (``"birdnet"`` or ``"perch"``).
        min_conf_threshold:   Minimum confidence for a secondary result to be
                              considered.  Defaults to
                              ``cfg.defaults.min_confidence``.
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
        species_name:     str | None = None,
    ) -> CrossValidationResult:
        """Run the secondary model and return a :class:`CrossValidationResult`.

        Args:
            audio:            PCM audio at ``cfg.audio.sample_rate`` sized to
                              the secondary model's ``window_seconds``.  If the
                              array is shorter than the required window the
                              secondary model will still be called but the
                              result should be treated as lower quality; most
                              backends handle variable-length input gracefully.
            primary_species:  Raw common-name label from the primary model
                              (used for fallback comparison if BTO mapping
                              fails on both sides).
            primary_bto_name: BTO-resolved name for the primary detection.
                              If ``None``, comparison falls back to raw common
                              names.
            primary_conf:     Primary model confidence for this detection.
                              Compared against ``cfg.cross_validation.skip_threshold``.
            species_name:     Common name to look up in the per-species
                              config for an ``on_disagree`` override.  If
                              ``None``, ``primary_species`` is used.

        Returns:
            :class:`CrossValidationResult` — always returned; never raises.
        """
        # ── High-confidence shortcut ──────────────────────────────────────────
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

        # Apply the same minimum-confidence floor used in the primary loop so
        # that noise and marginal hits don't count as a "species call".
        candidates = [
            (s, c) for s, c in candidates if c >= self._min_conf
        ]

        # ── Determine agreement ───────────────────────────────────────────────
        if not candidates:
            # Secondary model produced nothing above the confidence floor.
            # Treat as disagreement — the secondary cannot confirm the species.
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

            # Compare at BTO level when both names are available (most
            # reliable, bridging IOC / eBird label namespaces).
            if primary_bto_name and sec_bto_name:
                agree = primary_bto_name.lower() == sec_bto_name.lower()
            elif primary_bto_name is None and sec_bto_name is None:
                # Neither mapped — fall back to raw common names
                agree = primary_species.lower() == sec_species.lower()
            else:
                # One mapped, one not — can't reliably bridge namespaces
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
            # Look up per-species on_disagree override; fall back to global.
            lookup_name = species_name or primary_species
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
