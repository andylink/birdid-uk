"""
inference.py — inference backend dispatcher.

Selects and exposes the active inference model based on
``cfg.inference.model`` (``"birdnet"`` or ``"perch"``).

Adding a new backend
--------------------
1. Create ``inference_<name>.py`` with a class that satisfies
   :class:`Inferencer` (``window_seconds`` attribute, ``run_inference`` and
   ``load_label_map`` methods).
2. Add an ``elif cfg.inference.model == "<name>"`` branch in :func:`get_model`.
3. Document the ``model`` key in ``config.toml`` and ``AGENTS.md``.

Backward compatibility
----------------------
Module-level :func:`run_inference` and :func:`load_label_map` functions are
kept so that any code which did ``from inference import run_inference`` continues
to work.  New code should call :func:`get_model` directly so it can also access
``model.window_seconds``.

Secondary model (cross-validation)
-----------------------------------
:func:`get_secondary_model` returns the model that is *not* the primary, used
by :mod:`cross_validate` when ``cfg.cross_validation.enabled`` is ``True``.
:func:`get_secondary_model_name` returns its name as a string (``"birdnet"``
or ``"perch"``).
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from config import cfg


# ── Model protocol ────────────────────────────────────────────────────────────

class Inferencer(Protocol):
    """Interface that every inference backend must satisfy.

    ``window_seconds`` tells the classify loop how large a rolling audio
    buffer to maintain.  Both methods must return results in the same format
    regardless of which underlying model is used so that filters, confirmation
    logic, and persistence are model-agnostic.
    """

    #: Length of audio window the model expects, in seconds.
    window_seconds: float

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Run the model on *audio* and return results.

        Args:
            audio: PCM array at ``cfg.audio.sample_rate``.  The backend is
                responsible for any resampling required by its model.

        Returns:
            ``[(common_name, confidence), ...]`` sorted by confidence
            descending.  Noise labels are removed; no threshold or top-N cap
            is applied (the classify loop handles both).
        """
        ...

    def load_label_map(self) -> dict[str, str]:
        """Return a label map for building the BOU/seasonal filter sets.

        Returns:
            ``{common_name: "Scientific name_Common name"}`` — the same format
            used by ``bou_filter.build_bou_allowed_set`` and
            ``bou_filter.build_birdnet_to_bto_map``.
        """
        ...


# ── Singletons ────────────────────────────────────────────────────────────────

_active_model:    Inferencer | None = None
_secondary_model: Inferencer | None = None


def get_model() -> Inferencer:
    """Return the configured inference backend (singleton, lazy initialisation).

    The backend is selected by ``cfg.inference.model``:

    * ``"birdnet"`` → :class:`inference_birdnet.BirdNETModel` (default)
    * ``"perch"``   → :class:`inference_perch.PerchModel`

    Raises:
        ValueError: If ``cfg.inference.model`` is not a recognised value.
        RuntimeError: If the selected backend's prerequisites are not installed
            (e.g. ``perch-hoplite`` not present for Perch).
    """
    global _active_model
    if _active_model is not None:
        return _active_model

    model_name = cfg.inference.model.lower().strip()

    if model_name == "birdnet":
        from inference_birdnet import BirdNETModel
        _active_model = BirdNETModel()
    elif model_name == "perch":
        from inference_perch import PerchModel
        _active_model = PerchModel()
    else:
        raise ValueError(
            f"Unknown inference model {cfg.inference.model!r}. "
            "Supported values: 'birdnet', 'perch'."
        )

    return _active_model


def get_secondary_model_name() -> str:
    """Return the name of the secondary (cross-validation) model.

    The secondary model is always whichever of ``"birdnet"`` / ``"perch"``
    is *not* selected as ``cfg.inference.model``.

    Raises:
        ValueError: If the primary model name is not ``"birdnet"`` or
            ``"perch"`` (no known secondary exists).
    """
    primary = cfg.inference.model.lower().strip()
    if primary == "birdnet":
        return "perch"
    if primary == "perch":
        return "birdnet"
    raise ValueError(
        f"Cannot determine secondary model for primary {primary!r}. "
        "Supported primary values: 'birdnet', 'perch'."
    )


def get_secondary_model() -> Inferencer:
    """Return the secondary inference backend (singleton, lazy initialisation).

    Used by :class:`cross_validate.CrossValidator` when
    ``cfg.cross_validation.enabled`` is ``True``.  The secondary model is the
    model NOT selected as ``cfg.inference.model``.

    Raises:
        ValueError: If the primary model has no known secondary.
        RuntimeError: If the secondary backend's prerequisites are not
            installed (e.g. ``perch-hoplite`` not present when BirdNET is
            primary and Perch is therefore secondary).
    """
    global _secondary_model
    if _secondary_model is not None:
        return _secondary_model

    secondary_name = get_secondary_model_name()

    if secondary_name == "birdnet":
        from inference_birdnet import BirdNETModel
        _secondary_model = BirdNETModel()
    elif secondary_name == "perch":
        from inference_perch import PerchModel
        _secondary_model = PerchModel()
    else:
        raise ValueError(
            f"Unknown secondary inference model {secondary_name!r}."
        )

    return _secondary_model


# ── Backward-compatible module-level helpers ──────────────────────────────────

def load_label_map() -> dict[str, str]:
    """Convenience wrapper — delegates to the active model's ``load_label_map``."""
    return get_model().load_label_map()


def run_inference(audio: np.ndarray) -> list[tuple[str, float]]:
    """Convenience wrapper — delegates to the active model's ``run_inference``."""
    return get_model().run_inference(audio)

