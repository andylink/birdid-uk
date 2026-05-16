"""
filters/privacy_filter.py — clip-level human-sound privacy gate.

When enabled, :class:`PrivacyFilter` runs the active inference model against
each confirmed detection clip (inside ``_deferred_save``) and drops any clip
whose highest human-label score meets or exceeds the configured threshold.
No database row, FLAC clip, MQTT message, or BirdWeather upload is created for
dropped clips.

Thresholds are model-specific because the two backends produce scores on
different scales:

* **BirdNET** — per-label logistic scores in ``[0, 1]``.  A clearly audible
  voice typically scores ``0.03–0.20`` on the ``"Human non-vocal"`` label.
  The default threshold ``0.05`` catches most audible speech while tolerating
  faint background conversation at distance.

* **Perch v2** — softmax probabilities over ~10 000 classes; human-label
  scores are structurally much smaller (``0.002–0.05`` for an audible voice).
  The default threshold ``0.01`` is appropriate for this scale.

Usage::

    from filters.privacy_filter import PrivacyFilter
    from config import cfg
    from inference import get_model

    pf = PrivacyFilter(cfg.privacy_filter, get_model(), cfg.inference.model)
    if pf.scan(audio_segment):
        return  # drop — human sound detected
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from config import PrivacyFilterConfig
    from inference import Inferencer

logger = logging.getLogger(__name__)


class PrivacyFilter:
    """Clip-level gate that drops detections containing human sounds.

    Parameters
    ----------
    cfg:
        :class:`~config.PrivacyFilterConfig` with ``enabled``,
        ``birdnet_threshold``, and ``perch_threshold``.
    model:
        The active :class:`~inference.Inferencer` instance.  Must implement
        :meth:`~inference.Inferencer.scan_for_human`.
    model_name:
        ``"birdnet"`` or ``"perch"`` — selects which threshold to apply.
    """

    def __init__(
        self,
        cfg: PrivacyFilterConfig,
        model: Inferencer,
        model_name: str,
    ) -> None:
        self._cfg        = cfg
        self._model      = model
        self._model_name = model_name.lower().strip()
        self._threshold  = (
            cfg.birdnet_threshold
            if self._model_name == "birdnet"
            else cfg.perch_threshold
        )
        logger.info(
            "Privacy filter: model=%s  threshold=%.4f",
            self._model_name, self._threshold,
        )

    @property
    def enabled(self) -> bool:
        """True when the filter is active (mirrors ``cfg.privacy_filter.enabled``)."""
        return self._cfg.enabled

    def scan(self, audio: np.ndarray) -> bool:
        """Return ``True`` if human sound is detected above threshold.

        Calls :meth:`~inference.Inferencer.scan_for_human` on *audio* and
        compares the result against the model-appropriate threshold.  The score
        is logged at DEBUG level on every call so it is available for threshold
        tuning without noisy INFO output.

        Args:
            audio: PCM array at ``cfg.audio.sample_rate`` — typically the
                model-window slice of the assembled detection clip (same audio
                that primary inference ran on).

        Returns:
            ``True``  → human score ≥ threshold; caller should drop the clip.
            ``False`` → no human sound detected above threshold; proceed normally.
        """
        score = self._model.scan_for_human(audio)
        logger.debug(
            "privacy scan: model=%s  score=%.4f  threshold=%.4f  drop=%s",
            self._model_name, score, self._threshold, score >= self._threshold,
        )
        return score >= self._threshold
