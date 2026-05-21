"""
Google Perch v2 bird sound classifier backend — ONNX Runtime edition.

Prerequisites
-------------
Install the inference package::

    pip install onnxruntime

No TensorFlow or Kaggle account required.

Model download
--------------
The Perch v2 ONNX model (~409 MB) is loaded in order of preference:

1. **Local cache** — ``~/.cache/birdid-uk/perch_v2_onnx/`` (or the path set
   by the ``BIRDID_PERCH_MODEL_PATH`` environment variable).  install.sh
   downloads this directly from HuggingFace so no account is needed.

2. **HuggingFace download** — last resort if the local cache is missing.
   Re-run install.sh to populate the cache automatically.

Audio
-----
Perch v2 expects 5-second windows at 32 kHz.  The classify loop records at
``cfg.audio.sample_rate`` (typically 48 kHz) and accumulates a 5-second
buffer.  ``run_inference`` resamples to 32 kHz internally using
``scipy.signal.resample_poly``.

Label mapping
-------------
Labels come from ``labels.txt`` in the model cache — one scientific name per
line; the first line is the dataset marker (``inat2024_fsd50k``) and is
skipped.  Scientific names are mapped to BTO British common names using
``uk_species_filter.json`` (same as BirdNET), falling back to the scientific
name for non-UK species.

The returned ``{common_name: "Scientific_Common"}`` format is identical to
BirdNET's so ``species_filter`` and ``seasonal_filter`` work unchanged.

Performance
-----------
The ONNX Runtime path is ~9× faster than TFLite and avoids the GPU
``DEVICE_TYPE_INVALID`` bug present in the TF SavedModel export.  Inference
runs on CPU via ORT; BirdNET continues to use the GPU via its own runtime.
"""

from __future__ import annotations

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

# Local model cache — populated by install.sh.
# Can be overridden at runtime via the BIRDID_PERCH_MODEL_PATH env var.
_LOCAL_MODEL_DIR = Path(
    os.environ.get("BIRDID_PERCH_MODEL_PATH", "")
    or Path.home() / ".cache" / "birdid-uk" / "perch_v2_onnx"
)

_ONNX_FILENAME   = "perch_v2.onnx"
_LABELS_FILENAME = "labels.txt"

_HF_BASE = (
    "https://huggingface.co/tphakala/Perch-v2/resolve/main"
)


class PerchModel:
    """Google Perch v2 bird sound classifier — ONNX Runtime backend.

    All heavy objects (ORT session, label maps) are loaded lazily on first
    use so that importing this module is free when Perch is not active.
    """

    #: Audio window size expected by Perch v2.
    window_seconds: float = _PERCH_WINDOW_SECONDS

    def __init__(self) -> None:
        self._session: object | None = None          # onnxruntime.InferenceSession
        self._label_map:    dict[str, str] | None = None
        self._sci_to_common: dict[str, str]        = {}
        self._classes:       list[str]             = []  # scientific names, logit-aligned

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _model_path(self) -> Path:
        return _LOCAL_MODEL_DIR / _ONNX_FILENAME

    def _labels_path(self) -> Path:
        return _LOCAL_MODEL_DIR / _LABELS_FILENAME

    def _download_file(self, url: str, dest: Path) -> None:
        """Download *url* to *dest* with a progress log line."""
        import urllib.request
        logger.info("Downloading %s → %s …", url, dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        logger.info("Downloaded %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)

    def _ensure_files(self) -> None:
        """Ensure the ONNX model and labels file exist locally."""
        if not self._model_path().exists():
            logger.warning(
                "Perch ONNX model not found at %s — attempting HuggingFace download.",
                self._model_path(),
            )
            self._download_file(f"{_HF_BASE}/{_ONNX_FILENAME}", self._model_path())

        if not self._labels_path().exists():
            logger.warning(
                "Perch labels not found at %s — attempting HuggingFace download.",
                self._labels_path(),
            )
            self._download_file(f"{_HF_BASE}/{_LABELS_FILENAME}", self._labels_path())

    def _ensure_model(self) -> None:
        """Load the ORT session on first call."""
        if self._session is not None:
            return
        try:
            import onnxruntime as ort  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is not installed.\n"
                "Install it with:  pip install onnxruntime"
            ) from exc

        self._ensure_files()

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = os.cpu_count() or 4
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        logger.info("Loading Perch v2 ONNX model from %s …", self._model_path())
        t0 = time.perf_counter()
        self._session = ort.InferenceSession(
            str(self._model_path()),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        logger.info("Perch v2 ONNX model ready (%.2f s load time).", time.perf_counter() - t0)

    def _load_classes(self) -> list[str]:
        """Read scientific names from labels.txt; skip first (dataset marker) line."""
        self._ensure_files()
        lines = self._labels_path().read_text(encoding="utf-8").splitlines()
        # First line is 'inat2024_fsd50k' — skip it
        return [ln.strip() for ln in lines[1:] if ln.strip()]

    def _build_maps(self) -> tuple[dict[str, str], dict[str, str], list[str]]:
        """Build label_map, sci→common lookup, and ordered class list."""
        # Load BTO scientific → British common name
        bto_path = Path(__file__).parent.parent / "filters" / "uk_species_filter.json"
        sci_to_bto: dict[str, str] = {}
        if bto_path.exists():
            for sp in json.loads(bto_path.read_text()):
                sci  = sp.get("scientific_name", "").strip().lower()
                name = sp.get("name", "").strip()
                if sci and name:
                    sci_to_bto[sci] = name

        # Load BirdNET label file to build sci→BirdNET-common-name lookup so
        # that Perch stores the same species name as BirdNET (e.g.
        # "Eurasian Blackbird" rather than the BTO short form "Blackbird").
        sci_to_birdnet: dict[str, str] = {}
        try:
            import birdnet_analyzer as _bna
            import pathlib as _pl
            _labels = (
                _pl.Path(_bna.__file__).parent
                / "checkpoints" / "V2.4"
                / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"
            )
            if _labels.exists():
                for _line in _labels.read_text(encoding="utf-8").splitlines():
                    _label = _line.strip()
                    if not _label:
                        continue
                    _sci_part, _, _common = _label.partition("_")
                    if _sci_part and _common:
                        sci_to_birdnet[_sci_part.strip().lower()] = _common
                logger.debug(
                    "Perch: loaded %d BirdNET name mappings for consistent species names.",
                    len(sci_to_birdnet),
                )
        except ImportError:
            logger.debug("Perch: birdnet_analyzer not installed; using BTO names as fallback.")

        sci_names = self._load_classes()
        if not sci_names:
            logger.warning("Perch: empty class list; label map will be empty.")
            return {}, {}, []

        label_map:     dict[str, str] = {}
        sci_to_common: dict[str, str] = {}
        bto_hits = 0

        for sci_name in sci_names:
            sci_lower = sci_name.lower()
            # Prefer BirdNET name so species strings are identical across models,
            # then fall back to BTO British name, then raw scientific name.
            birdnet_name = sci_to_birdnet.get(sci_lower)
            bto_name     = sci_to_bto.get(sci_lower)
            if birdnet_name:
                common = birdnet_name
                bto_hits += 1
            elif bto_name:
                common = bto_name
                bto_hits += 1
            else:
                common = sci_name
            # "Scientific name_Common name" format — same as BirdNET
            label_map[common]       = f"{sci_name}_{common}"
            sci_to_common[sci_name] = common

        logger.info(
            "Perch label map: %d species (%d matched to BirdNET/BTO names, %d unmatched).",
            len(label_map), bto_hits, len(sci_names) - bto_hits,
        )
        return label_map, sci_to_common, sci_names

    def _ensure_maps(self) -> None:
        """Build maps once."""
        if self._label_map is not None:
            return
        self._label_map, self._sci_to_common, self._classes = self._build_maps()

    # ── Public interface ──────────────────────────────────────────────────────

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: "Scientific name_Common name"}`` for all Perch species.

        The TF/ORT model is not loaded here — that happens lazily on the
        first ``run_inference`` call.  Format is identical to
        ``BirdNETModel.load_label_map``.
        """
        self._ensure_maps()
        assert self._label_map is not None
        return self._label_map

    def run_inference(self, audio: np.ndarray) -> list[tuple[str, float]]:
        """Resample *audio* to 32 kHz, run Perch v2 ONNX, return results.

        Returns ``[(common_name, confidence), ...]`` sorted descending.
        Entries in ``NOISE_LABELS`` are removed.  No threshold or top-N cap
        is applied here.

        Args:
            audio: PCM array (int16 or float32) at ``cfg.audio.sample_rate``.
        """
        from scipy.signal import resample_poly  # type: ignore[import]

        self._ensure_maps()
        self._ensure_model()

        if not self._classes:
            logger.warning("Perch class list is empty; cannot run inference.")
            return []

        t0 = time.perf_counter()

        # Normalise int16 → float32 in [-1, 1]
        if audio.dtype == np.int16:
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            audio_f = audio.astype(np.float32)

        # Resample to 32 kHz
        src_rate = cfg.audio.sample_rate
        if src_rate != _PERCH_SAMPLE_RATE:
            g    = gcd(src_rate, _PERCH_SAMPLE_RATE)
            up   = _PERCH_SAMPLE_RATE // g
            down = src_rate // g
            audio_f = resample_poly(audio_f, up, down).astype(np.float32)

        # Pad or truncate to exactly 160,000 samples (5 s @ 32 kHz)
        expected = int(_PERCH_WINDOW_SECONDS * _PERCH_SAMPLE_RATE)
        if len(audio_f) < expected:
            audio_f = np.pad(audio_f, (0, expected - len(audio_f)))
        else:
            audio_f = audio_f[:expected]

        # ORT expects shape [batch, 160000]
        inp = audio_f[np.newaxis, :]  # (1, 160000)

        try:
            outputs = self._session.run(  # type: ignore[union-attr]
                ["label"],
                {"inputs": inp},
            )
        except Exception:
            logger.exception("Perch ONNX inference error")
            return []

        logits: np.ndarray = outputs[0].flatten()  # (14795,)

        if len(logits) != len(self._classes):
            logger.warning(
                "Perch class count mismatch: %d classes vs %d logits",
                len(self._classes), len(logits),
            )
            return []

        # Softmax
        shifted     = logits - logits.max()
        exp_shifted = np.exp(shifted)
        probs       = exp_shifted / exp_shifted.sum()

        _prob_floor = 0.01
        results: list[tuple[str, float]] = []
        for sci_name, prob in zip(self._classes, probs):
            if prob < _prob_floor:
                continue
            common = self._sci_to_common.get(sci_name, sci_name)
            if common.lower() not in NOISE_LABELS:
                results.append((common, float(prob)))

        results.sort(key=lambda x: x[1], reverse=True)
        elapsed = time.perf_counter() - t0
        logger.debug(
            "Perch ONNX inference: %.3f s for %.1f s window (%.1fx real-time)",
            elapsed, self.window_seconds, self.window_seconds / elapsed,
        )
        return results
