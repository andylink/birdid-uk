"""
inference_birdnet.py — BirdNET GLOBAL 6K V2.4 inference backend.

Uses the model shipped with *birdnet_analyzer*.  No extra dependencies or
model downloads are required beyond the package itself.

Stock label format
------------------
The bundled labels file uses ``Scientific name_Common name`` (one underscore
separator, space inside the scientific name), e.g.::

    Erithacus rubecula_European Robin

:meth:`BirdNETModel.load_label_map` returns ``{common_name: full_label_line}``
so that ``bou_filter`` can do its three-stage species matching.

The ``analyze()`` CSV already contains the clean common name in the
``Common name`` column, so no name conversion is needed at inference time.

Label locale
------------
``cfg.inference.label_locale`` selects which common-name convention is used.
``"en"`` (the default) uses the bundled global English labels in
``checkpoints/V2.4/``.  Any other value (e.g. ``"en-uk"``) loads the
matching translated file from ``labels/V2.4/`` and passes the locale to
BirdNET's ``analyze()`` so inference results and the label map use the same
naming convention.

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
import pathlib
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from audio import save_wav
from config import cfg


class BirdNETModel:
    """BirdNET GLOBAL 6K V2.4 inference backend."""

    #: Analysis window expected by BirdNET.  The classify loop uses this to
    #: size its rolling audio buffer.
    window_seconds: float = 3.0

    # ── Label map ─────────────────────────────────────────────────────────────

    def _labels_path(self) -> Path:
        import birdnet_analyzer
        base = pathlib.Path(birdnet_analyzer.__file__).parent
        locale = cfg.inference.label_locale
        if locale and locale != "en":
            # BirdNET label filenames use underscores (e.g. en_uk), but config
            # may store the locale with a hyphen (e.g. "en-uk").  Normalise.
            locale_norm = locale.replace("-", "_")
            path = base / "labels" / "V2.4" / f"BirdNET_GLOBAL_6K_V2.4_Labels_{locale_norm}.txt"
            if path.exists():
                return path
        # Default: global English labels in checkpoints/V2.4/
        return base / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: full_label_line}`` for all BirdNET species.

        The locale is controlled by ``cfg.inference.label_locale``.  Label
        lines have the form ``Scientific name_Common name``, e.g.
        ``Erithacus rubecula_European Robin``.  The common name matches the
        ``Common name`` column returned by ``analyze()``.

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

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "clip.wav"
            save_wav(audio, wav_path)

            # Normalise locale: BirdNET expects underscores (en_uk), not hyphens.
            locale_norm = cfg.inference.label_locale.replace("-", "_")
            with redirect_stdout(io.StringIO()):
                analyze(
                    str(wav_path),
                    output=tmpdir,
                    min_conf=0.01,
                    rtype="csv",
                    merge_consecutive=1,
                    threads=1,
                    locale=locale_norm,
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
        return results
