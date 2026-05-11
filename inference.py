"""
inference.py — BirdNET analysis and label-map utilities.

Uses the built-in BirdNET GLOBAL 6K V2.4 model shipped with
*birdnet_analyzer*.  No custom classifier is loaded.

Stock label format
------------------
The bundled labels file uses ``Scientific name_Common name`` (one underscore
separator, space inside the scientific name), e.g.::

    Erithacus rubecula_European Robin

``load_label_map()`` returns ``{common_name: full_label_line}`` so that
``save_pending_clip`` can create per-species folders with a consistent name.

The ``analyze()`` CSV already contains the clean common name in the
``Common name`` column, so no name conversion is needed at inference time.

Label locale
------------
``cfg.inference.label_locale`` selects which common-name convention is used.
``"en"`` (the default) uses the bundled global English labels in
``checkpoints/V2.4/``.  Any other value (e.g. ``"en_uk"``) loads the
matching translated file from ``labels/V2.4/`` and passes the locale to
BirdNET's ``analyze()`` so inference results and the label map use the same
naming convention.
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

# Path to the BirdNET labels file, respecting cfg.inference.label_locale.
def _labels_path() -> Path:
    import birdnet_analyzer
    base = pathlib.Path(birdnet_analyzer.__file__).parent
    locale = cfg.inference.label_locale
    if locale and locale != "en":
        # BirdNET label filenames use underscores (e.g. en_uk), but config may
        # store the locale with a hyphen (e.g. "en-uk").  Normalise here.
        locale_norm = locale.replace("-", "_")
        # Translated labels live in labels/V2.4/
        path = base / "labels" / "V2.4" / f"BirdNET_GLOBAL_6K_V2.4_Labels_{locale_norm}.txt"
        if path.exists():
            return path
    # Default: global English labels in checkpoints/V2.4/
    return base / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"


# ── Label map ─────────────────────────────────────────────────────────────────

def load_label_map() -> dict[str, str]:
    """
    Return ``{common_name: full_label_line}`` for all stock BirdNET species.

    The locale is controlled by ``cfg.inference.label_locale`` (see
    :func:`_labels_path`).  Label lines have the form
    ``Scientific name_Common name``, e.g.
    ``Erithacus rubecula_European Robin``.  The common name matches the
    ``Common name`` column returned by ``analyze()``.

    Returns an empty dict if the labels file cannot be found.
    """
    labels_path = _labels_path()
    if not labels_path.exists():
        return {}

    label_map: dict[str, str] = {}
    for line in labels_path.read_text().splitlines():
        label = line.strip()
        if not label:
            continue
        _, _, common = label.partition("_")   # "Genus species_Common name" → common
        if common:
            label_map[common] = label
    return label_map


# ── Inference ─────────────────────────────────────────────────────────────────

def run_inference(audio: np.ndarray) -> list[tuple[str, float]]:
    """
    Write *audio* to a temporary WAV, run BirdNET GLOBAL 6K V2.4, and return
    ``[(common_name, confidence), ...]`` sorted by confidence descending.

    Noise labels (``cfg.defaults.noise_labels``) are removed.  No confidence
    threshold or top-N cap is applied — the classify loop handles those.

    A raw floor of ``0.01`` is passed so near-zero scores are skipped without
    suppressing any real detections.
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
