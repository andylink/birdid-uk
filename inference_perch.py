"""
inference_perch.py — Google Perch v2 bird sound classifier backend.

Prerequisites
-------------
Install the inference package::

    pip install 'perch-hoplite[tf]'

Kaggle credentials are required for the first model download.  Create an API
token at https://www.kaggle.com/settings and save it as
``~/.config/kaggle/kaggle.json`` (or set the ``KAGGLE_KEY`` environment
variable).  The model (~400 MB) is cached in ``~/.cache/kagglehub/`` after
the first download; subsequent runs use the local copy.

Audio specification
-------------------
Perch v2 expects **5-second windows at 32 kHz**.  The classify loop records
audio at ``cfg.audio.sample_rate`` (typically 48 kHz) and accumulates a 5-second
buffer; :meth:`PerchModel.run_inference` resamples from the recording rate to
32 kHz internally using ``scipy.signal.resample_poly``.  Clip saving and the
capture ring buffer are unaffected — they always operate at the recording rate.

Label mapping
-------------
Perch v2's class list (``model.class_list["labels"].classes``) contains
**scientific names** in ``inat2024_fsd50k`` namespace order — the same order
as the logits vector.  :meth:`PerchModel.load_label_map` maps these to common
names via the following priority:

1. Scientific-name match against ``species_bto_FINAL_filtered.json`` → BTO
   British common name (e.g. ``"Robin"``).  This re-uses the same data that
   drives the BOU filter so the BOU allowlist works correctly with Perch.
2. Scientific name itself as a last resort (ensures no species is silently
   dropped; non-UK species are filtered by the BOU allowlist anyway).

The returned ``{common_name: "Scientific_Common"}`` format is identical to
BirdNET's label map so ``bou_filter`` and ``seasonal_filter`` work without
modification.

Implementation notes
--------------------
The ordered class list is read from ``assets/labels.csv`` (column
``inat2024_fsd50k``) in the Kaggle model cache directory.  This avoids loading
the 400 MB TF model just to build the label map.  The model itself is loaded
lazily on the first :meth:`run_inference` call.

``run_inference`` uses the cached ``self._classes`` list (scientific names,
aligned with the logits vector) and never re-accesses
``model.class_list`` — avoiding the key mismatch between logits key
``"label"`` and class_list key ``"labels"``.
"""

from __future__ import annotations

import csv as csv_mod
import json
import logging
from math import gcd
from pathlib import Path

import numpy as np

from config import cfg

logger = logging.getLogger(__name__)

# Perch v2 native audio specification
_PERCH_SAMPLE_RATE    = 32_000
_PERCH_WINDOW_SECONDS = 5.0


class PerchModel:
    """Google Perch v2 bird sound classifier backend.

    All heavy objects (TF model, label maps) are loaded lazily on first use
    so that importing this module has zero cost when Perch is not active.
    """

    #: Analysis window expected by Perch v2.
    window_seconds: float = _PERCH_WINDOW_SECONDS

    def __init__(self) -> None:
        self._model: object | None = None
        self._label_map:    dict[str, str] | None = None  # {common_name: label_str}
        self._sci_to_common: dict[str, str]        = {}   # {scientific_name: common_name}
        self._classes:       list[str]             = []   # ordered sci names (aligned with logits)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_model(self) -> None:
        """Lazy-load the Perch v2 TF model (downloads from Kaggle if needed)."""
        if self._model is not None:
            return
        try:
            from perch_hoplite.zoo import model_configs  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "perch-hoplite is not installed.\n"
                "Install it with:  pip install 'perch-hoplite[tf]'\n"
                "Kaggle credentials are also required for the first model download.\n"
                "See: https://www.kaggle.com/docs/api#authentication"
            ) from exc

        logger.info(
            "Loading Perch v2 model — first run downloads ~400 MB from Kaggle "
            "(cached in ~/.cache/kagglehub/ afterwards)…"
        )
        self._model = model_configs.load_model_by_name("perch_v2")
        logger.info("Perch v2 model ready.")

    def _get_model_dir(self) -> Path | None:
        """Return the local Kaggle cache directory for perch_v2, or None."""
        try:
            import kagglehub  # type: ignore[import]
            path = kagglehub.model_download(
                "google/bird-vocalization-classifier/tensorFlow2/perch_v2"
            )
            return Path(path)
        except Exception as exc:
            logger.debug("Could not locate Perch v2 Kaggle model directory: %s", exc)
            return None

    def _sci_names_from_csv(self) -> list[str]:
        """Read the ordered scientific-name list from ``assets/labels.csv``.

        The CSV has a single column ``inat2024_fsd50k`` whose rows are
        scientific names aligned with the model's logits vector.  This is the
        preferred source because it does not require loading the TF model.
        """
        model_dir = self._get_model_dir()
        if model_dir is None:
            return []
        labels_csv = model_dir / "assets" / "labels.csv"
        if not labels_csv.exists():
            logger.debug("Perch labels.csv not found at %s", labels_csv)
            return []
        try:
            with open(labels_csv, newline="") as fh:
                reader = csv_mod.DictReader(fh)
                names: list[str] = []
                for row in reader:
                    # Column name is the namespace; accept any single-column CSV
                    # by trying the known name first then falling back.
                    name = (
                        row.get("inat2024_fsd50k")
                        or next(iter(row.values()), "")
                    ).strip()
                    if name:
                        names.append(name)
            logger.debug("Perch labels.csv: %d scientific names loaded.", len(names))
            return names
        except Exception as exc:
            logger.debug("Could not read Perch labels.csv: %s", exc)
            return []

    def _sci_names_from_model(self) -> list[str]:
        """Extract the ordered scientific-name list from the loaded model (fallback).

        Used when ``labels.csv`` is unavailable.  Requires the TF model to be
        loaded first via :meth:`_ensure_model`.
        """
        self._ensure_model()
        try:
            cl = self._model.class_list  # type: ignore[union-attr]
            # class_list is a dict; key is "labels" (not "label")
            cls_obj = cl.get("labels") or next(iter(cl.values()), None)
            if cls_obj is None:
                return []
            return list(cls_obj.classes)
        except Exception as exc:
            logger.warning(
                "Could not extract Perch class list from model object: %s", exc
            )
            return []

    def _build_maps(self) -> tuple[dict[str, str], dict[str, str], list[str]]:
        """Build the label map, sci→common lookup, and ordered class list.

        Called once on the first invocation of :meth:`_ensure_maps`.
        Returns ``(label_map, sci_to_common, classes)``.

        The class list comes from ``assets/labels.csv`` (preferred, no TF load)
        or from ``model.class_list["labels"].classes`` (fallback).  Either way
        the entries are **scientific names** in the same order as the logits
        vector produced by :meth:`run_inference`.
        """
        # ── Step 1: BTO scientific_name → british_common_name ─────────────────
        bto_path = Path(__file__).parent / "species_bto_FINAL_filtered.json"
        sci_to_bto: dict[str, str] = {}
        if bto_path.exists():
            for sp in json.loads(bto_path.read_text()):
                sci  = sp.get("scientific_name", "").strip().lower()
                name = sp.get("name", "").strip()
                if sci and name:
                    sci_to_bto[sci] = name

        # ── Step 2: get the ordered scientific-name class list ────────────────
        sci_names = self._sci_names_from_csv()
        if not sci_names:
            logger.info(
                "Perch labels.csv unavailable — loading TF model to retrieve "
                "class list (BTO name matching still applied)."
            )
            sci_names = self._sci_names_from_model()

        if not sci_names:
            logger.warning("Perch: could not determine class list; label map will be empty.")
            return {}, {}, []

        # ── Step 3: assemble the maps ─────────────────────────────────────────
        label_map:      dict[str, str] = {}
        sci_to_common:  dict[str, str] = {}

        bto_hits = 0
        for sci_name in sci_names:
            sci_lower = sci_name.lower()

            # Priority: BTO british name > scientific name as last resort
            bto_name = sci_to_bto.get(sci_lower)
            if bto_name:
                common = bto_name
                bto_hits += 1
            else:
                common = sci_name

            # label_map value: "Scientific name_Common name" — matches BirdNET
            # format so bou_filter and seasonal_filter work unchanged.
            label_map[common]         = f"{sci_name}_{common}"
            sci_to_common[sci_name]   = common

        logger.info(
            "Perch label map: %d species (%d matched to BTO names, %d unmatched).",
            len(label_map),
            bto_hits,
            len(sci_names) - bto_hits,
        )
        return label_map, sci_to_common, sci_names

    def _ensure_maps(self) -> None:
        """Ensure label map, sci→common lookup, and class list are built (once)."""
        if self._label_map is not None:
            return
        self._label_map, self._sci_to_common, self._classes = self._build_maps()

    # ── Public interface ──────────────────────────────────────────────────────

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: "Scientific name_Common name"}`` for all Perch species.

        Building the map reads ``assets/labels.csv`` from the Kaggle model cache
        and the BTO species list.  The TF model itself is *not* loaded here —
        that happens lazily on the first :meth:`run_inference` call.

        The returned format is identical to
        :meth:`inference_birdnet.BirdNETModel.load_label_map` so ``bou_filter``
        and ``seasonal_filter`` work without modification.
        """
        self._ensure_maps()
        assert self._label_map is not None
        return self._label_map

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Resample *audio*, run Perch v2, and return results.

        Returns ``[(common_name, confidence), ...]`` sorted by confidence
        descending.  Noise labels (``cfg.defaults.noise_labels``) are removed.
        No confidence threshold or top-N cap is applied.

        The input *audio* is expected at ``cfg.audio.sample_rate`` (48 kHz by
        default), as recorded by sounddevice.  It is resampled to 32 kHz
        internally with ``scipy.signal.resample_poly``, then padded or
        truncated to exactly one 5-second Perch window.

        Raw logits are converted to probabilities via softmax (averaged over
        any multiple output frames) before being returned as confidence values.

        Args:
            audio: PCM array (int16 or float32) at ``cfg.audio.sample_rate``.
        """
        from scipy.signal import resample_poly  # type: ignore[import]

        self._ensure_maps()   # build sci→common map and class list before we need them
        self._ensure_model()  # load TF model (no-op after first call)

        if not self._classes:
            logger.warning("Perch class list is empty; cannot run inference.")
            return []

        noise_labels = cfg.defaults.noise_labels

        # ── Convert int16 PCM → float32 in [-1, 1] ───────────────────────────
        if audio.dtype == np.int16:
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            audio_f = audio.astype(np.float32)

        # ── Resample to Perch's native 32 kHz ────────────────────────────────
        src_rate = cfg.audio.sample_rate
        if src_rate != _PERCH_SAMPLE_RATE:
            g    = gcd(src_rate, _PERCH_SAMPLE_RATE)
            up   = _PERCH_SAMPLE_RATE // g
            down = src_rate // g
            audio_f = resample_poly(audio_f, up, down).astype(np.float32)

        # ── Pad or truncate to exactly one 5-second window ───────────────────
        expected_samples = int(_PERCH_WINDOW_SECONDS * _PERCH_SAMPLE_RATE)
        if len(audio_f) < expected_samples:
            audio_f = np.pad(audio_f, (0, expected_samples - len(audio_f)))
        else:
            audio_f = audio_f[:expected_samples]

        # ── Run Perch ─────────────────────────────────────────────────────────
        try:
            outputs = self._model.embed(audio_f)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Perch inference error")
            return []

        logits_dict = outputs.logits
        if not logits_dict:
            return []

        # logits key is "label" (no 's'); class_list key is "labels" (with 's').
        # We use self._classes (pre-built, aligned with logits) rather than
        # re-accessing model.class_list to avoid the key mismatch at runtime.
        primary_key = (
            "label"
            if "label" in logits_dict
            else next(iter(logits_dict))
        )
        logits: np.ndarray = np.array(logits_dict[primary_key])

        # Average over temporal frames if the model returned multiple windows
        if logits.ndim > 1:
            logits = logits.mean(axis=0)
        logits = logits.flatten()

        if len(logits) != len(self._classes):
            logger.warning(
                "Perch class count mismatch: %d classes vs %d logits",
                len(self._classes), len(logits),
            )
            return []

        # ── Softmax: raw logits → probabilities ───────────────────────────────
        shifted = logits - logits.max()
        probs   = np.exp(shifted) / np.exp(shifted).sum()

        # ── Map scientific names → common names and build results ─────────────
        results: list[tuple[str, float]] = []
        for sci_name, prob in zip(self._classes, probs):
            common = self._sci_to_common.get(sci_name, sci_name)
            if common.lower() not in noise_labels:
                results.append((common, float(prob)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results
