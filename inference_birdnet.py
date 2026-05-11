"""
inference_birdnet.py — BirdNET GLOBAL 6K V2.4 inference backend.

Uses the model shipped with *birdnet_analyzer*.  No extra dependencies or
model downloads are required beyond the package itself.

Label format
------------
The bundled labels file uses ``Scientific name_Common name`` (one underscore
separator, space inside the scientific name), e.g.::

    Erithacus rubecula_European Robin

:meth:`BirdNETModel.load_label_map` returns ``{common_name: full_label_line}``
so that ``bou_filter`` can do its three-stage species matching.

The ``analyze()`` CSV contains the common name in the ``Common name`` column;
this is used directly as the species key throughout the detect loop.

BTO name translation is handled downstream by ``bou_filter.build_birdnet_to_bto_map``,
which maps BirdNET international English names (e.g. ``"European Robin"``) to
BTO British names (e.g. ``"Robin"``) via the ``international_english_name``
field in ``species_bto_FINAL_filtered.json``.  No name conversion is done here.

Label locale
------------
``cfg.inference.label_locale`` is passed to BirdNET's ``analyze()`` and used
to select the labels file.  The default ``"en"`` uses the bundled global
English / IOC names from ``checkpoints/V2.4/``.  Non-default locales load from
``labels/V2.4/``; the ``en_uk`` translation file exists but is incomplete, so
``"en"`` with ``bou_filter`` name translation is preferred.

Window spec
-----------
BirdNET expects exactly 3-second windows.  ``window_seconds`` is exposed as a
class attribute so the classify loop can size its rolling buffer appropriately.
Audio is assumed to arrive at ``cfg.audio.sample_rate`` (48 kHz by default);
no resampling is performed.
"""

from __future__ import annotations

import csv
import io
import logging
import pathlib
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from audio import save_wav
from config import cfg

logger = logging.getLogger(__name__)


class BirdNETModel:
    """BirdNET GLOBAL 6K V2.4 inference backend."""

    #: Analysis window expected by BirdNET.  The classify loop uses this to
    #: size its rolling audio buffer.
    window_seconds: float = 3.0

    # ── Label map ─────────────────────────────────────────────────────────────

    def _labels_path(self) -> Path:
        import birdnet_analyzer
        base = pathlib.Path(birdnet_analyzer.__file__).parent
        return base / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: full_label_line}`` for all BirdNET species.

        Uses the standard global English / IOC labels bundled with
        birdnet-analyzer (``checkpoints/V2.4/BirdNET_GLOBAL_6K_V2.4_Labels.txt``).
        Label lines have the form ``Scientific name_Common name``, e.g.
        ``Erithacus rubecula_European Robin``.

        Returns an empty dict if the labels file cannot be found.
        """
        labels_path = self._labels_path()
        if not labels_path.exists():
            return {}

        label_map: dict[str, str] = {}
        for line in labels_path.read_text().splitlines():
            label = line.strip()
            if not label:
                continue
            _, _, common = label.partition("_")   # "Genus species_Common name"
            if common:
                label_map[common] = label
        return label_map

    # ── Inference ─────────────────────────────────────────────────────────────

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Write *audio* to a temporary WAV, run BirdNET, and return results.

        Returns ``[(common_name, confidence), ...]`` sorted by confidence
        descending.  Noise labels (``cfg.defaults.noise_labels``) are removed.
        No confidence threshold or top-N cap is applied — the classify loop
        handles those.

        A raw floor of ``0.01`` is passed to BirdNET so near-zero scores are
        skipped without suppressing any real detections.

        Args:
            audio: Raw PCM array at ``cfg.audio.sample_rate``.  Typically
                int16 from sounddevice, but float arrays are also accepted.
        """
        from birdnet_analyzer.analyze.core import analyze  # lazy import

        noise_labels = cfg.defaults.noise_labels
        t0 = time.perf_counter()

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "clip.wav"
            save_wav(audio, wav_path)

            with redirect_stdout(io.StringIO()):
                analyze(
                    str(wav_path),
                    output=tmpdir,
                    min_conf=0.01,
                    rtype="csv",
                    merge_consecutive=1,
                    threads=1,
                )

            csv_path = Path(tmpdir) / "clip.BirdNET.results.csv"
            if not csv_path.exists():
                return []

            results: list[tuple[str, float]] = []
            with open(csv_path) as fh:
                for row in csv.DictReader(fh):
                    common = row["Common name"].strip()
                    conf   = float(row["Confidence"])
                    if common.lower() not in noise_labels:
                        results.append((common, conf))

        results.sort(key=lambda x: x[1], reverse=True)
        logger.debug(
            "BirdNET inference: %.3f s for %.1f s window (%.1fx real-time)",
            time.perf_counter() - t0,
            self.window_seconds,
            self.window_seconds / (time.perf_counter() - t0),
        )
        return results
