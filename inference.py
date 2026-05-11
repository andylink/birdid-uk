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


# ── Singleton ─────────────────────────────────────────────────────────────────

_active_model: Inferencer | None = None


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


# ── Backward-compatible module-level helpers ──────────────────────────────────

def load_label_map() -> dict[str, str]:
    """Convenience wrapper — delegates to the active model's ``load_label_map``."""
    return get_model().load_label_map()


def run_inference(audio: np.ndarray) -> list[tuple[str, float]]:
    """Convenience wrapper — delegates to the active model's ``run_inference``."""
    return get_model().run_inference(audio)
