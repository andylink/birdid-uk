"""
Selects and exposes the configured inference backend (BirdNET or Perch).

The active model is chosen by ``cfg.inference.model``. Both backends share
the same interface (``Inferencer``) so the rest of the codebase doesn't need
to know which one is in use.

Adding a new backend
--------------------
1. Create ``inference/<name>.py`` with a class that has a ``window_seconds``
   attribute and ``run_inference`` / ``load_label_map`` methods.
2. Add an ``elif cfg.inference.model == "<name>"`` branch in ``get_model``.
3. Document the new ``model`` value in ``config.toml`` and ``AGENTS.md``.

Backward compatibility
----------------------
Module-level ``run_inference`` and ``load_label_map`` functions are kept so
that existing code using ``from inference import run_inference`` still works.
New code should call ``get_model()`` directly to also access
``model.window_seconds``.

Secondary model
---------------
``get_secondary_model`` returns whichever backend is *not* the primary. Used
by ``cross_validate`` when ``cfg.cross_validation.enabled`` is ``True``.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from config import cfg


# ── Model protocol ────────────────────────────────────────────────────────────

class Inferencer(Protocol):
    """Interface every inference backend must implement.

    ``window_seconds`` tells the classify loop how large an audio buffer to
    keep. Both methods must return results in the same format so that
    filtering, confirmation logic, and persistence are backend-agnostic.
    """

    #: Length of the audio window the model expects, in seconds.
    window_seconds: float

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Run the model on *audio* and return detections.

        Args:
            audio: PCM array at ``cfg.audio.sample_rate``. The backend
                handles any resampling its model requires.

        Returns:
            ``[(common_name, confidence), ...]`` sorted by confidence
            descending. Noise labels are removed. No threshold or top-N
            cap is applied — the classify loop handles those.
        """
        ...

    def load_label_map(self) -> dict[str, str]:
        """Return the label map used to build species filter sets.

        Returns:
            ``{common_name: "Scientific name_Common name"}`` — the format
            expected by ``species_filter.build_bou_allowed_set`` and
            ``species_filter.build_birdnet_to_bto_map``.
        """
        ...



# ── Singletons ────────────────────────────────────────────────────────────────

_active_model:    Inferencer | None = None
_secondary_model: Inferencer | None = None


def get_model() -> Inferencer:
    """Return the configured inference backend, creating it once on first call.

    Backend is selected by ``cfg.inference.model``:

    * ``"birdnet"`` → ``inference.birdnet.BirdNETModel`` (default)
    * ``"perch"``   → ``inference.perch.PerchModel``

    Raises:
        ValueError: If ``cfg.inference.model`` is not a recognised value.
        RuntimeError: If the backend's dependencies are missing
            (e.g. ``perch-hoplite`` not installed when using Perch).
    """
    global _active_model
    if _active_model is not None:
        return _active_model

    model_name = cfg.inference.model.lower().strip()

    if model_name == "birdnet":
        from .birdnet import BirdNETModel
        _active_model = BirdNETModel()
    elif model_name == "perch":
        from .perch import PerchModel
        _active_model = PerchModel()
    else:
        raise ValueError(
            f"Unknown inference model {cfg.inference.model!r}. "
            "Supported values: 'birdnet', 'perch'."
        )

    return _active_model


def get_secondary_model_name() -> str:
    """Return the name of the secondary (cross-validation) model.

    Always the other backend: if primary is BirdNET, secondary is Perch,
    and vice versa.

    Raises:
        ValueError: If the primary model name is not ``"birdnet"`` or ``"perch"``.
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
    """Return the secondary inference backend, creating it once on first call.

    Used by ``CrossValidator`` when ``cfg.cross_validation.enabled`` is
    ``True``. The secondary is whichever backend is NOT the primary.

    Raises:
        ValueError: If the primary model has no known secondary.
        RuntimeError: If the secondary backend's dependencies are missing.
    """
    global _secondary_model
    if _secondary_model is not None:
        return _secondary_model

    secondary_name = get_secondary_model_name()

    if secondary_name == "birdnet":
        from .birdnet import BirdNETModel
        _secondary_model = BirdNETModel()
    elif secondary_name == "perch":
        from .perch import PerchModel
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
