"""
Google Perch v2 bird sound classifier backend.

Prerequisites
-------------
Install the inference package::

    pip install 'perch-hoplite[tf]'

Model download
--------------
The Perch v2 model (~400 MB) is loaded in order of preference:

1. **Local cache** — ``~/.cache/birdid-uk/perch_v2/`` (or the path set by
   the ``BIRDID_PERCH_MODEL_PATH`` environment variable).  install.sh
   downloads this directly from the GitHub Release asset so no Kaggle account
   is needed.

2. **Kaggle cache** — ``~/.cache/kagglehub/…`` populated by a previous run
   with Kaggle credentials.

3. **Kaggle download** — last resort if neither cache exists.  Requires a
   free Kaggle account and an API token saved to
   ``~/.config/kaggle/kaggle.json``.  The easiest path is to re-run
   install.sh which handles the download automatically.

Audio
-----
Perch v2 expects 5-second windows at 32 kHz. The classify loop records at
``cfg.audio.sample_rate`` (typically 48 kHz) and accumulates a 5-second
buffer. ``run_inference`` resamples to 32 kHz internally using
``scipy.signal.resample_poly``. Clip saving and the capture ring buffer are
unaffected — they always operate at the recording rate.

Label mapping
-------------
Perch v2's class list contains scientific names in ``inat2024_fsd50k``
namespace order, aligned with the logits vector. ``load_label_map`` converts
these to common names using:

1. Scientific-name lookup in ``uk_species_filter.json`` → BTO British common
   name (e.g. ``"Robin"``). This reuses the same data as the BOU filter.
2. Scientific name as a fallback (non-UK species are filtered by the BOU
   allowlist anyway, so nothing is silently dropped).

The returned ``{common_name: "Scientific_Common"}`` format is identical to
BirdNET's so ``species_filter`` and ``seasonal_filter`` work unchanged.

Implementation note
-------------------
The ordered class list is read from ``assets/labels.csv`` in the Kaggle
model cache. This avoids loading the 400 MB TF model just to build the label
map. The TF model is loaded lazily on the first ``run_inference`` call.

``run_inference`` uses the cached ``self._classes`` list (scientific names,
aligned with the logits vector) rather than re-accessing
``model.class_list`` — the logits key is ``"label"`` but the class_list key
is ``"labels"``, which would cause a mismatch at runtime.
"""

from __future__ import annotations

import csv as csv_mod
import json
import logging
import os
import time
from math import gcd
from pathlib import Path

import numpy as np

from config import cfg
from constants import NOISE_LABELS

logger = logging.getLogger(__name__)

# Perch v2 native audio specification
_PERCH_SAMPLE_RATE    = 32_000
_PERCH_WINDOW_SECONDS = 5.0

# Local model cache — populated by install.sh so users don't need a Kaggle
# account.  Can be overridden at runtime via the BIRDID_PERCH_MODEL_PATH env var.
_LOCAL_MODEL_DIR = Path(
    os.environ.get("BIRDID_PERCH_MODEL_PATH", "")
    or Path.home() / ".cache" / "birdid-uk" / "perch_v2"
)

# Kaggle model handle used as fallback when no local copy exists
_KAGGLE_MODEL_HANDLE = "google/bird-vocalization-classifier/tensorFlow2/perch_v2_cpu"


class PerchModel:
    """Google Perch v2 bird sound classifier backend.

    All heavy objects (TF model, label maps) are loaded lazily on first use
    so that importing this module is free when Perch is not active.
    """

    #: Audio window size expected by Perch v2.
    window_seconds: float = _PERCH_WINDOW_SECONDS

    def __init__(self) -> None:
        self._model: object | None = None
        self._label_map:    dict[str, str] | None = None  # {common_name: label_str}
        self._sci_to_common: dict[str, str]        = {}   # {scientific_name: common_name}
        self._classes:       list[str]             = []   # scientific names, aligned with logits

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _deduplicate_ebird_csv(self) -> None:
        """Remove duplicate rows from ``perch_v2_ebird_classes.csv`` in the model cache.

        Perch v2 ships with duplicate entries in this file, which causes a
        noisy warning when the model loads. The warning is harmless — we use
        ``assets/labels.csv`` for class ordering anyway — but deduplicating
        the file once silences it on all future runs.
        """
        model_dir = self._get_model_dir()
        if model_dir is None:
            return
        ebird_csv = model_dir / "assets" / "perch_v2_ebird_classes.csv"
        if not ebird_csv.exists():
            return
        try:
            lines = ebird_csv.read_text(encoding="utf-8").splitlines()
            seen: set[str] = set()
            deduped: list[str] = []
            for line in lines:
                if line not in seen:
                    seen.add(line)
                    deduped.append(line)
            if len(deduped) < len(lines):
                logger.debug(
                    "Perch: deduplicating perch_v2_ebird_classes.csv "
                    "(%d → %d entries to silence Perch class-list warning)",
                    len(lines), len(deduped),
                )
                ebird_csv.write_text("\n".join(deduped), encoding="utf-8")
        except Exception:
            logger.debug(
                "Perch: could not pre-process perch_v2_ebird_classes.csv "
                "(non-fatal — model will still load)",
                exc_info=True,
            )

    def _ensure_model(self) -> None:
        """Load the Perch v2 TF model on first call.

        Loading order:
        1. Local model cache (``~/.cache/birdid-uk/perch_v2/``) — no Kaggle needed.
        2. Kaggle hub cache (``~/.cache/kagglehub/``) — used if already downloaded.
        3. Kaggle download — requires credentials, downloads ~400 MB.
        """
        if self._model is not None:
            return
        try:
            from perch_hoplite.zoo import taxonomy_model_tf  # type: ignore[import]
            from perch_hoplite.zoo import model_configs       # type: ignore[import]
            from ml_collections import config_dict            # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "perch-hoplite is not installed.\n"
                "Install it with:  pip install 'perch-hoplite[tf]'"
            ) from exc

        # Hide GPUs from TF for Perch. The Perch v2 saved_model uses XLA ops
        # compiled for CPU. When a GPU is present TF tries to dispatch XLA to
        # CUDA, causing a platform-mismatch error. BirdNET uses its own runtime
        # (tflite/ONNX) so hiding the GPU here doesn't affect it.
        try:
            import tensorflow as tf  # type: ignore[import]
            tf.config.set_visible_devices([], "GPU")
        except Exception:
            # TF not yet imported or already finalised — fall back to env var.
            os.environ["CUDA_VISIBLE_DEVICES"] = ""

        self._deduplicate_ebird_csv()

        # ── 1. Local cache (populated by install.sh, no Kaggle needed) ─────────
        if (_LOCAL_MODEL_DIR / "saved_model.pb").exists() or \
           (_LOCAL_MODEL_DIR / "savedmodel" / "saved_model.pb").exists():
            logger.info("Loading Perch v2 model from local cache: %s", _LOCAL_MODEL_DIR)
            cfg_dict = config_dict.ConfigDict({
                "model_path": str(_LOCAL_MODEL_DIR),
                "window_size_s": 5.0,
                "hop_size_s": 5.0,
                "sample_rate": 32000,
                "target_peak": 0.25,
            })
            try:
                self._model = taxonomy_model_tf.TaxonomyModelTF.from_config(cfg_dict)
                logger.info("Perch v2 model ready (local cache).")
                return
            except Exception as exc:
                logger.warning(
                    "Failed to load Perch v2 from local cache (%s): %s — "
                    "falling back to Kaggle.", _LOCAL_MODEL_DIR, exc
                )

        # ── 2 & 3. Kaggle hub (cached or fresh download) ────────────────────────
        logger.info(
            "Loading Perch v2 model via Kaggle hub "
            "(first run downloads ~400 MB — cached in ~/.cache/kagglehub/ afterwards)…"
        )
        try:
            self._model = model_configs.load_model_by_name("perch_v2_cpu")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load Perch v2 model: {exc}\n\n"
                "The model was not found in the local cache or Kaggle hub.\n"
                "Re-run install.sh to download it automatically:\n"
                "    bash install.sh   # choose 'Install Perch' when prompted"
            ) from exc
        logger.info("Perch v2 model ready (Kaggle hub).")

    def _get_model_dir(self) -> Path | None:
        """Return the local model directory for perch_v2, or None.

        Checks the local cache first, then the Kaggle hub cache.
        """
        # ── 1. Local install.sh cache ──────────────────────────────────────────
        if (_LOCAL_MODEL_DIR / "saved_model.pb").exists() or \
           (_LOCAL_MODEL_DIR / "savedmodel" / "saved_model.pb").exists():
            return _LOCAL_MODEL_DIR

        # ── 2. Kaggle hub cache ────────────────────────────────────────────────
        try:
            import kagglehub  # type: ignore[import]
            path = kagglehub.model_download(_KAGGLE_MODEL_HANDLE)
            return Path(path)
        except Exception as exc:
            logger.debug("Could not locate Perch v2 model directory: %s", exc)
            return None

    def _sci_names_from_csv(self) -> list[str]:
        """Read the ordered scientific-name list from ``assets/labels.csv``.

        The CSV column ``inat2024_fsd50k`` lists scientific names in the same
        order as the model's logits vector. Reading this file avoids loading
        the full TF model just to get the class list.
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
                    # Try the known column name first, fall back to whatever is there
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
        """Extract the ordered scientific-name list from the loaded TF model.

        Fallback used when ``labels.csv`` is unavailable. Requires the model
        to be loaded first via ``_ensure_model``.
        """
        self._ensure_model()
        try:
            cl = self._model.class_list  # type: ignore[union-attr]
            # The dict key is "labels" (not "label")
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

        Called once by ``_ensure_maps``. Returns
        ``(label_map, sci_to_common, classes)``.

        Class order comes from ``assets/labels.csv`` (preferred, no TF load
        needed) or ``model.class_list["labels"].classes`` (fallback). Either
        way the entries are scientific names aligned with the logits vector.
        """
        # Step 1: load BTO scientific_name → british_common_name from the filter file
        bto_path = Path(__file__).parent.parent / "filters" / "uk_species_filter.json"
        sci_to_bto: dict[str, str] = {}
        if bto_path.exists():
            for sp in json.loads(bto_path.read_text()):
                sci  = sp.get("scientific_name", "").strip().lower()
                name = sp.get("name", "").strip()
                if sci and name:
                    sci_to_bto[sci] = name

        # Step 2: get the ordered scientific-name class list
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

        # Step 3: build both maps
        label_map:      dict[str, str] = {}
        sci_to_common:  dict[str, str] = {}

        bto_hits = 0
        for sci_name in sci_names:
            sci_lower = sci_name.lower()

            # Use the BTO British name if available; fall back to the scientific name
            bto_name = sci_to_bto.get(sci_lower)
            if bto_name:
                common = bto_name
                bto_hits += 1
            else:
                common = sci_name

            # Store in "Scientific name_Common name" format to match BirdNET's
            # label map, so species_filter and seasonal_filter work unchanged.
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
        """Build the label map, sci→common lookup, and class list once."""
        if self._label_map is not None:
            return
        self._label_map, self._sci_to_common, self._classes = self._build_maps()

    # ── Public interface ──────────────────────────────────────────────────────

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: "Scientific name_Common name"}`` for all Perch species.

        Reads ``assets/labels.csv`` from the Kaggle model cache and the BTO
        species list. The TF model itself is not loaded here — that happens
        lazily on the first ``run_inference`` call.

        The format is identical to ``BirdNETModel.load_label_map`` so
        ``species_filter`` and ``seasonal_filter`` work without modification.
        """
        self._ensure_maps()
        assert self._label_map is not None
        return self._label_map

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Resample *audio* to 32 kHz, run Perch v2, and return results.

        Returns ``[(common_name, confidence), ...]`` sorted by confidence
        descending. Entries in ``NOISE_LABELS`` are removed. No threshold
        or top-N cap is applied.

        Input audio is expected at ``cfg.audio.sample_rate`` (48 kHz by
        default). It is resampled to 32 kHz with ``scipy.signal.resample_poly``
        then padded or truncated to exactly one 5-second window.

        Raw logits are averaged over any temporal frames then converted to
        probabilities via softmax before being returned as confidence values.

        Args:
            audio: PCM array (int16 or float32) at ``cfg.audio.sample_rate``.
        """
        from scipy.signal import resample_poly  # type: ignore[import]

        self._ensure_maps()   # build sci→common map and class list before inference
        self._ensure_model()  # load TF model (no-op after first call)

        if not self._classes:
            logger.warning("Perch class list is empty; cannot run inference.")
            return []

        t0 = time.perf_counter()

        # Normalise int16 PCM to float32 in [-1, 1]
        if audio.dtype == np.int16:
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            audio_f = audio.astype(np.float32)

        # Resample to Perch's native 32 kHz
        src_rate = cfg.audio.sample_rate
        if src_rate != _PERCH_SAMPLE_RATE:
            g    = gcd(src_rate, _PERCH_SAMPLE_RATE)
            up   = _PERCH_SAMPLE_RATE // g
            down = src_rate // g
            audio_f = resample_poly(audio_f, up, down).astype(np.float32)

        # Pad or truncate to exactly one 5-second window
        expected_samples = int(_PERCH_WINDOW_SECONDS * _PERCH_SAMPLE_RATE)
        if len(audio_f) < expected_samples:
            audio_f = np.pad(audio_f, (0, expected_samples - len(audio_f)))
        else:
            audio_f = audio_f[:expected_samples]

        # Run the model
        try:
            outputs = self._model.embed(audio_f)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Perch inference error")
            return []

        logits_dict = outputs.logits
        if not logits_dict:
            return []

        # The logits key is "label" (no 's'); we use self._classes (pre-built,
        # aligned with logits) rather than model.class_list to avoid the
        # "label" vs "labels" key mismatch.
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

        # Convert logits to probabilities via softmax
        shifted     = logits - logits.max()
        exp_shifted = np.exp(shifted)
        probs       = exp_shifted / exp_shifted.sum()

        # Skip entries below 0.01 — matches BirdNET's min_conf floor and avoids
        # returning thousands of near-zero softmax scores for absent species.
        _prob_floor = 0.01
        results: list[tuple[str, float]] = []
        for sci_name, prob in zip(self._classes, probs):
            if prob < _prob_floor:
                continue
            common = self._sci_to_common.get(sci_name, sci_name)
            if common.lower() not in NOISE_LABELS:
                results.append((common, float(prob)))

        results.sort(key=lambda x: x[1], reverse=True)
        logger.debug(
            "Perch inference: %.3f s for %.1f s window (%.1fx real-time)",
            time.perf_counter() - t0,
            self.window_seconds,
            self.window_seconds / (time.perf_counter() - t0),
        )
        return results
