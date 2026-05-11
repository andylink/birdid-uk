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
Perch uses eBird species codes (e.g. ``"robin1"``) as its class identifiers.
:meth:`PerchModel.load_label_map` converts these to common names via the
following priority order:

1. Scientific-name match against ``species_bto_FINAL_filtered.json`` → BTO
   British common name (e.g. ``"Robin"``).  This re-uses the same data that
   drives the BOU filter so the BOU allowlist works correctly with Perch.
2. English common name from the label CSV bundled in the Kaggle model dir
   (column ``common_name``, ``english_name``, or ``name``).
3. eBird code itself as a last resort (ensures no species is silently dropped).

The returned ``{common_name: "Scientific_Common"}`` format is identical to
BirdNET's label map so ``bou_filter`` and ``seasonal_filter`` work without
modification.

Cross-validation hook
---------------------
This module is designed to support a future cross-validation mode where both
BirdNET and Perch run on every confirmed detection.  The ``PerchModel``
instance is stateful (lazy model + map loading) and safe to hold long-term.
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
        self._label_map:     dict[str, str] | None = None  # {common_name: label_str}
        self._code_to_common: dict[str, str]        = {}   # {ebird_code: common_name}

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

    def _ebird_codes_from_model(self) -> list[str]:
        """Extract the ordered eBird code list from the loaded model object."""
        self._ensure_model()
        try:
            cls_obj = (
                self._model.class_list.get("label")  # type: ignore[union-attr]
                or next(iter(self._model.class_list.values()), None)  # type: ignore[union-attr]
            )
            return list(cls_obj.classes) if cls_obj is not None else []
        except Exception:
            logger.warning("Could not extract Perch class list from model object.")
            return []

    def _build_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        """Build both the label map and the eBird-code → common-name lookup.

        Called once on the first invocation of :meth:`load_label_map`.
        Returns ``(label_map, code_to_common)``.
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

        # ── Step 2: parse the label CSV bundled in the Kaggle model dir ───────
        # The CSV has one row per species with at minimum the eBird code.
        # Scientific name and common name columns are present in the BirdCLEF
        # dataset format used by Perch; handle column-name variants gracefully.
        csv_rows: dict[str, dict[str, str]] = {}  # ebird_code → {sci, name}
        model_dir = self._get_model_dir()
        if model_dir is not None:
            assets_dir = model_dir / "assets"
            csv_candidates = (
                list(assets_dir.glob("*.csv"))
                if assets_dir.is_dir()
                else []
            )
            for csv_path in csv_candidates:
                try:
                    with open(csv_path, newline="") as fh:
                        reader = csv_mod.DictReader(fh)
                        raw_fields = reader.fieldnames or []
                        fields = [f.lower().strip() for f in raw_fields]

                        def _col(*candidates: str) -> str | None:
                            for c in candidates:
                                if c in fields:
                                    return c
                            return None

                        code_col = _col(
                            "primary_label", "species_code", "ebird_code", "code"
                        )
                        sci_col  = _col("scientific_name", "sci_name")
                        name_col = _col(
                            "common_name", "english_name", "name", "species_name"
                        )

                        if code_col is None:
                            continue  # not the right CSV

                        for raw in reader:
                            row  = {k.lower().strip(): v.strip() for k, v in raw.items()}
                            code = row.get(code_col, "")
                            if not code:
                                continue
                            csv_rows[code] = {
                                "sci":  row.get(sci_col,  "") if sci_col  else "",
                                "name": row.get(name_col, "") if name_col else "",
                            }
                    if csv_rows:
                        logger.debug(
                            "Perch label CSV loaded from %s (%d rows)",
                            csv_path.name, len(csv_rows),
                        )
                        break  # use the first usable CSV
                except Exception as exc:
                    logger.debug("Could not parse %s: %s", csv_path, exc)

        # ── Step 3: get the ordered eBird code list ───────────────────────────
        # Prefer the CSV row order; fall back to the model's class list.
        if csv_rows:
            ebird_codes = list(csv_rows.keys())
        else:
            logger.info(
                "No Perch label CSV found — loading model to retrieve class list "
                "(common names will be eBird codes unless BTO scientific-name "
                "matching succeeds)."
            )
            ebird_codes = self._ebird_codes_from_model()

        # ── Step 4: assemble the maps ─────────────────────────────────────────
        label_map:     dict[str, str] = {}
        code_to_common: dict[str, str] = {}

        for code in ebird_codes:
            info      = csv_rows.get(code, {})
            sci_lower = info.get("sci", "").lower()
            csv_name  = info.get("name", "")

            # Priority: BTO british name > CSV english name > eBird code
            common = sci_to_bto.get(sci_lower) or csv_name or code

            # Build a label string in BirdNET's "Scientific name_Common name"
            # format so bou_filter's existing matching logic works unchanged.
            sci_words    = sci_lower.split()
            sci_display  = " ".join(
                w.capitalize() for w in sci_words
            ) if sci_words else code
            label_map[common]     = f"{sci_display}_{common}"
            code_to_common[code]  = common

        logger.info(
            "Perch label map: %d species (%d matched to BTO names)",
            len(label_map),
            sum(1 for c in ebird_codes
                if sci_to_bto.get(csv_rows.get(c, {}).get("sci", "").lower())),
        )
        return label_map, code_to_common

    def _ensure_maps(self) -> None:
        """Ensure label map and code→common lookup are built (once)."""
        if self._label_map is not None:
            return
        self._label_map, self._code_to_common = self._build_maps()

    # ── Public interface ──────────────────────────────────────────────────────

    def load_label_map(self) -> dict[str, str]:
        """Return ``{common_name: "Scientific name_Common name"}`` for all Perch species.

        Building the map requires downloading (or locating the cached copy of)
        the Kaggle model to access the bundled label CSV.  The TF model itself
        is *not* loaded here — that happens lazily on the first
        :meth:`run_inference` call.

        The returned format is identical to :meth:`inference_birdnet.BirdNETModel.load_label_map`
        so ``bou_filter`` and ``seasonal_filter`` work without modification.
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

        self._ensure_maps()   # build code→common map before we need it
        self._ensure_model()  # load TF model (no-op after first call)

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

        # Pick the primary class list ("label" preferred, else first available)
        primary_key = (
            "label"
            if "label" in logits_dict
            else next(iter(logits_dict))
        )
        logits: np.ndarray = logits_dict[primary_key]

        # Average over temporal frames if the model returned multiple windows
        if logits.ndim > 1:
            logits = logits.mean(axis=0)
        logits = logits.flatten()

        # ── Softmax: raw logits → probabilities ───────────────────────────────
        shifted = logits - logits.max()
        probs   = np.exp(shifted) / np.exp(shifted).sum()

        # ── Retrieve the ordered eBird class names ────────────────────────────
        try:
            classes: list[str] = list(
                self._model.class_list[primary_key].classes  # type: ignore[index]
            )
        except Exception:
            logger.warning("Could not retrieve Perch class list during inference.")
            return []

        if len(classes) != len(probs):
            logger.warning(
                "Perch class count mismatch: %d classes vs %d probabilities",
                len(classes), len(probs),
            )
            return []

        # ── Map eBird codes → common names and build results ──────────────────
        results: list[tuple[str, float]] = []
        for code, prob in zip(classes, probs):
            common = self._code_to_common.get(code, code)  # fallback: eBird code
            if common.lower() not in noise_labels:
                results.append((common, float(prob)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results
