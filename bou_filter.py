"""
bou_filter.py — BTO species allowlist filtering.

Loads ``species_bto_FINAL_filtered.json`` (the BTO checklist for UK birds) and
matches each entry to a BirdNET label using a three-stage strategy.  When
enabled in ``config.toml``, the detect loop discards any detection whose
BirdNET common name is not present in the matched set.

Matching strategy
-----------------
BirdNET label lines have the form ``Genus species_Common name``, e.g.::

    Erithacus rubecula_European Robin

**Stage 0 — explicit international_english_name**: if the JSON entry has a
non-null ``international_english_name`` field, that value is used directly
(validated against the label map).  This handles cases where the British name
differs from the international English name used by BirdNET (e.g. "Wigeon"
vs "Eurasian Wigeon").

**Stage 1 — scientific name**: the left-of-``_`` part of each BirdNET label
is compared case-insensitively against the ``scientific_name`` field in each
JSON entry.

**Stage 2 — common name fallback**: species that were not matched in stages 0
or 1 are retried by comparing the British ``name`` field case-insensitively
against the BirdNET common name (right-of-``_``).  This catches species where
the British and international English names happen to be the same.

No fuzzy matching is used in any stage.

Species in the list that remain unmatched after all three stages are logged at
DEBUG level.  The summary match counts are logged at INFO level so they are
visible on startup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BOU_JSON = Path(__file__).parent / "species_bto_FINAL_filtered.json"


def build_birdnet_to_bto_map(label_map: dict[str, str]) -> dict[str, str]:
    """Return ``{birdnet_common_name: bto_british_name}`` for all BOU-listed species.

    Uses the same three-stage matching logic as :func:`build_bou_allowed_set`
    but produces a reverse mapping so that the detector can translate a BirdNET
    common name (e.g. ``"European Robin"``) to the canonical BTO British name
    (e.g. ``"Robin"``) before writing to the database.

    Args:
        label_map: ``{birdnet_common_name: full_label_line}`` as returned by
                   :func:`inference.load_label_map`.

    Returns:
        dict mapping each matched BirdNET common name to its BTO British name.
        Species that cannot be matched are omitted.
    """
    if not label_map:
        logger.warning(
            "BOU map: BirdNET label map is empty — bto_name will not be "
            "populated.  Check that the BirdNET labels file exists."
        )
        return {}

    # Build reverse lookup: scientific_name_lower → birdnet_common_name
    sci_to_common: dict[str, str] = {}
    for common, label in label_map.items():
        scientific = label.partition("_")[0].strip().lower()
        if scientific:
            sci_to_common[scientific] = common

    # common-name fallback: birdnet_common_lower → canonical birdnet_common_name
    common_lower_to_birdnet: dict[str, str] = {
        c.lower(): c for c in label_map
    }

    with open(_BOU_JSON) as fh:
        bou_species: list[dict] = json.load(fh)

    mapping: dict[str, str] = {}

    for sp in bou_species:
        sci_raw = sp.get("scientific_name") or ""
        sci = sci_raw.strip().lower()
        bto_name = sp.get("name", "")
        if not bto_name:
            continue

        # Stage 0: explicit international_english_name
        birdnet_name = sp.get("international_english_name")
        if birdnet_name and birdnet_name in label_map:
            mapping[birdnet_name] = bto_name
            continue

        # Stage 1: scientific name
        if sci and sci in sci_to_common:
            mapping[sci_to_common[sci]] = bto_name
            continue

        # Stage 2: common name fallback
        bto_lower = bto_name.strip().lower()
        if bto_lower and bto_lower in common_lower_to_birdnet:
            mapping[common_lower_to_birdnet[bto_lower]] = bto_name
            continue

    logger.info(
        "BOU name map: %d BirdNET → BTO name mappings built",
        len(mapping),
    )
    return mapping


def build_bou_allowed_set(label_map: dict[str, str]) -> frozenset[str]:
    """
    Return a frozenset of BirdNET common names for all BOU-listed species.

    The set is built once at startup and passed into the classify loop.
    Detections whose common name is *not* in this set are suppressed when
    the BOU filter is enabled.

    Args:
        label_map: ``{birdnet_common_name: full_label_line}`` as returned by
                   :func:`inference.load_label_map`.  An empty dict (e.g. if
                   the labels file is missing) causes all detections to be
                   suppressed — log a warning in that case.

    Returns:
        frozenset of BirdNET common names that correspond to BOU species.
    """
    if not label_map:
        logger.warning(
            "BOU filter: BirdNET label map is empty — all detections will be "
            "suppressed while bou_filter is enabled.  Check that the BirdNET "
            "labels file exists."
        )
        return frozenset()

    # Build reverse lookup: scientific_name_lower → birdnet_common_name
    sci_to_common: dict[str, str] = {}
    for common, label in label_map.items():
        # label format: "Genus species_Common name"
        scientific = label.partition("_")[0].strip().lower()
        if scientific:
            sci_to_common[scientific] = common

    # Build common-name lookup for stage-2 fallback:
    # birdnet_common_lower → canonical birdnet_common_name (preserves original casing)
    common_lower_to_birdnet: dict[str, str] = {
        c.lower(): c for c in label_map
    }

    with open(_BOU_JSON) as fh:
        bou_species: list[dict] = json.load(fh)

    allowed: set[str] = set()
    n_explicit = 0
    n_sci = 0
    n_common = 0
    unmatched: list[str] = []

    for sp in bou_species:
        sci_raw = sp.get("scientific_name") or ""
        sci = sci_raw.strip().lower()
        bou_name = sp.get("name", "?")

        # Stage 0: explicit international_english_name in JSON
        birdnet_name = sp.get("international_english_name")
        if birdnet_name and birdnet_name in label_map:
            allowed.add(birdnet_name)
            n_explicit += 1
            continue

        # Stage 1: scientific name
        if sci and sci in sci_to_common:
            allowed.add(sci_to_common[sci])
            n_sci += 1
            continue

        # Stage 2: common name fallback
        bou_name_lower = bou_name.strip().lower()
        if bou_name_lower and bou_name_lower in common_lower_to_birdnet:
            allowed.add(common_lower_to_birdnet[bou_name_lower])
            n_common += 1
            continue

        unmatched.append(f"{bou_name} ({sci_raw or '?'})")

    n_bou = len(bou_species)
    n_matched = len(allowed)

    logger.info(
        "BOU filter: %d/%d BTO species matched to BirdNET labels "
        "(%d explicit, %d by scientific name, %d by common name)",
        n_matched,
        n_bou,
        n_explicit,
        n_sci,
        n_common,
    )
    if unmatched:
        logger.debug(
            "BOU filter: %d BTO species not matched in BirdNET labels "
            "(tried explicit international_english_name, scientific and common name): %s",
            len(unmatched),
            ", ".join(unmatched[:30]) + ("…" if len(unmatched) > 30 else ""),
        )

    return frozenset(allowed)
