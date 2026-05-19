"""
BirdNET GLOBAL 6K V2.4 inference backend.

Uses the model bundled with ``birdnet_analyzer``. No extra downloads needed.

Label format
------------
The labels file uses ``Scientific name_Common name`` (underscore separator),
e.g. ``Erithacus rubecula_European Robin``. ``load_label_map`` returns
``{common_name: full_label_line}`` so that ``species_filter`` can do its
three-stage species matching.

BTO name translation is handled downstream by
``species_filter.build_birdnet_to_bto_map``, which maps BirdNET IOC names
(e.g. ``"European Robin"``) to BTO British names (e.g. ``"Robin"``) via
``uk_species_filter.json``.

Window
------
BirdNET expects exactly 3-second audio windows. ``window_seconds`` is a class
attribute so the classify loop can size its rolling buffer accordingly. Audio
is assumed to arrive at ``cfg.audio.sample_rate``; no resampling is done.
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
from constants import NOISE_LABELS

logger = logging.getLogger(__name__)


class BirdNETModel:
    """BirdNET GLOBAL 6K V2.4 inference backend."""

    #: Audio window size expected by BirdNET. Used by the classify loop to
    #: size its rolling buffer.
    window_seconds: float = 3.0

    # ── Label map ─────────────────────────────────────────────────────────────

    def _labels_path(self) -> Path:
        import birdnet_analyzer
        base = pathlib.Path(birdnet_analyzer.__file__).parent
        return base / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: full_label_line}`` for all BirdNET species.

        Reads the labels file bundled with birdnet-analyzer. Each line has the
        form ``Scientific name_Common name``, e.g.
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
            _, _, common = label.partition("_")   # split "Genus species_Common name"
            if common:
                label_map[common] = label
        return label_map

    # ── Inference ─────────────────────────────────────────────────────────────

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Write *audio* to a temp WAV, run BirdNET, and return results.

        Returns ``[(common_name, confidence), ...]`` sorted by confidence
        descending. Entries in ``NOISE_LABELS`` are removed. No threshold
        or top-N cap is applied — the classify loop handles those.

        ``min_conf=0.01`` is passed to BirdNET to skip near-zero scores
        without suppressing any real detections.

        Args:
            audio: Raw PCM array at ``cfg.audio.sample_rate``. Typically
                int16 from sounddevice, but float arrays are also accepted.
        """
        from birdnet_analyzer.analyze.core import analyze  # lazy import

        t0 = time.perf_counter()

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "clip.wav"
            save_wav(audio, wav_path)

            # Suppress BirdNET's stdout progress output
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
                    if common.lower() not in NOISE_LABELS:
                        results.append((common, conf))

        results.sort(key=lambda x: x[1], reverse=True)
        logger.debug(
            "BirdNET inference: %.3f s for %.1f s window (%.1fx real-time)",
            time.perf_counter() - t0,
            self.window_seconds,
            self.window_seconds / (time.perf_counter() - t0),
        )
        return results
