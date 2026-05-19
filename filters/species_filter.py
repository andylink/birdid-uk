"""
species_filter.py — filters detections to UK-listed species only.

Loads uk_species_filter.json (the BTO/BOU checklist) and matches each entry
to a BirdNET label. When enabled, the detect loop drops any detection whose
BirdNET common name doesn't appear in the matched set.

Matching strategy
-----------------
BirdNET labels have the form "Genus species_Common name", e.g.:

    Erithacus rubecula_European Robin

Matching runs in three stages, stopping at the first success:

  Stage 0 — international_english_name: if the JSON entry has a non-null
    international_english_name, use it directly. This handles cases where
    the British name differs from BirdNET's name (e.g. "Wigeon" vs
    "Eurasian Wigeon").

  Stage 1 — scientific name: match the left-of-"_" part of the BirdNET label
    against the JSON scientific_name field (case-insensitive).

  Stage 2 — common name fallback: for anything still unmatched, compare the
    British name against the BirdNET common name. Catches species where the
    British and international names happen to be identical.

No fuzzy matching is used. Unmatched species are logged at DEBUG level;
match counts are logged at INFO level on startup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BOU_JSON = Path(__file__).parent / "uk_species_filter.json"


def _status_excluded(status: str, exclude_tokens: frozenset[str]) -> bool:
    """Return True if any comma-separated token in status matches an excluded token.

    Comparison is case-insensitive. The "/" character is not treated as a
    separator ("Passage/Winter Visitor" is treated as a single value).

    Examples:
        _status_excluded("Accidental, Has Bred", frozenset({"accidental"}))  # True
        _status_excluded("Scarce Visitor",        frozenset({"accidental"}))  # False
    """
    if not exclude_tokens:
        return False
    for token in status.split(","):
        if token.strip().lower() in exclude_tokens:
            return True
    return False


def build_birdnet_to_bto_map(
    label_map: dict[str, str],
    exclude_status: list[str] | tuple[str, ...] = (),
    force_include: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Build a mapping from BirdNET common names to BTO British names.

    Used to translate a BirdNET label (e.g. "European Robin") into the
    canonical British name ("Robin") before writing to the database.
    Uses the same three-stage matching logic as build_bou_allowed_set.

    Args:
        label_map: {birdnet_common_name: full_label_line} from inference.load_label_map.
        exclude_status: status tokens that cause a species to be skipped
            (matched case-insensitively against british_list_status).
            Empty by default (no exclusions).
        force_include: species names to admit even if their status would
            normally exclude them. Populated from species_status_override
            entries in config.toml.

    Returns:
        Dict mapping each matched BirdNET common name to its BTO British name.
        Species that can't be matched are omitted.
    """
    if not label_map:
        logger.warning(
            "BOU map: BirdNET label map is empty — bto_name will not be "
            "populated.  Check that the BirdNET labels file exists."
        )
        return {}

    exclude_lower: frozenset[str] = frozenset(s.lower() for s in exclude_status)
    force_include_lower: frozenset[str] = frozenset(s.lower() for s in force_include)

    # scientific_name_lower → birdnet_common_name
    sci_to_common: dict[str, str] = {}
    for common, label in label_map.items():
        scientific = label.partition("_")[0].strip().lower()
        if scientific:
            sci_to_common[scientific] = common

    # birdnet_common_lower → canonical birdnet_common_name (preserves original casing)
    common_lower_to_birdnet: dict[str, str] = {
        c.lower(): c for c in label_map
    }

    with open(_BOU_JSON) as fh:
        bou_species: list[dict] = json.load(fh)

    mapping: dict[str, str] = {}
    n_excluded = 0
    n_overridden = 0

    for sp in bou_species:
        if _status_excluded(sp.get("british_list_status") or "", exclude_lower):
            bto_lower  = sp.get("name", "").strip().lower()
            intl_lower = (sp.get("international_english_name") or "").strip().lower()
            if bto_lower not in force_include_lower and intl_lower not in force_include_lower:
                n_excluded += 1
                continue
            n_overridden += 1   # species_status_override — fall through to normal matching

        sci_raw = sp.get("scientific_name") or ""
        sci = sci_raw.strip().lower()
        bto_name = sp.get("name", "")
        if not bto_name:
            continue

        # Stage 0: use international_english_name if present and recognised by BirdNET
        birdnet_name = sp.get("international_english_name")
        if birdnet_name and birdnet_name in label_map:
            mapping[birdnet_name] = bto_name
            continue

        # Stage 1: match by scientific name
        if sci and sci in sci_to_common:
            mapping[sci_to_common[sci]] = bto_name
            continue

        # Stage 2: fall back to matching by common name
        bto_lower = bto_name.strip().lower()
        if bto_lower and bto_lower in common_lower_to_birdnet:
            mapping[common_lower_to_birdnet[bto_lower]] = bto_name
            continue

    logger.info(
        "BOU name map: %d BirdNET → BTO name mappings built%s%s",
        len(mapping),
        f" ({n_excluded} excluded by status)" if n_excluded else "",
        f" ({n_overridden} status override(s))" if n_overridden else "",
    )
    return mapping


def build_bou_allowed_set(
    label_map: dict[str, str],
    exclude_status: list[str] | tuple[str, ...] = (),
    force_include: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Return a frozenset of BirdNET common names for all BOU-listed species.

    Built once at startup and used by the classify loop to filter out
    non-UK species. Detections not in this set are dropped when the filter
    is enabled.

    Args:
        label_map: {birdnet_common_name: full_label_line} from inference.load_label_map.
            If empty (e.g. labels file missing), all detections will be suppressed.
        exclude_status: status tokens that cause a species to be excluded
            (case-insensitive match against british_list_status). Empty by default.
        force_include: species names to allow even if their status would
            normally exclude them. Populated from species_status_override
            entries in config.toml.

    Returns:
        frozenset of BirdNET common names corresponding to BOU-listed species.
    """
    if not label_map:
        logger.warning(
            "BOU filter: BirdNET label map is empty — all detections will be "
            "suppressed while species_filter is enabled.  Check that the BirdNET "
            "labels file exists."
        )
        return frozenset()

    exclude_lower: frozenset[str] = frozenset(s.lower() for s in exclude_status)
    force_include_lower: frozenset[str] = frozenset(s.lower() for s in force_include)

    # scientific_name_lower → birdnet_common_name
    sci_to_common: dict[str, str] = {}
    for common, label in label_map.items():
        # label format: "Genus species_Common name"
        scientific = label.partition("_")[0].strip().lower()
        if scientific:
            sci_to_common[scientific] = common

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
    n_excluded = 0
    n_overridden = 0
    unmatched: list[str] = []

    for sp in bou_species:
        sci_raw = sp.get("scientific_name") or ""
        sci = sci_raw.strip().lower()
        bou_name = sp.get("name", "?")

        # Skip species whose status is excluded (unless overridden in config)
        if _status_excluded(sp.get("british_list_status") or "", exclude_lower):
            bto_lower  = bou_name.strip().lower()
            intl_lower = (sp.get("international_english_name") or "").strip().lower()
            if bto_lower not in force_include_lower and intl_lower not in force_include_lower:
                n_excluded += 1
                continue
            n_overridden += 1   # species_status_override — fall through to normal matching

        # Stage 0: use international_english_name if present and recognised by BirdNET
        birdnet_name = sp.get("international_english_name")
        if birdnet_name and birdnet_name in label_map:
            allowed.add(birdnet_name)
            n_explicit += 1
            continue

        # Stage 1: match by scientific name
        if sci and sci in sci_to_common:
            allowed.add(sci_to_common[sci])
            n_sci += 1
            continue

        # Stage 2: fall back to matching by common name
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
        "(%d explicit, %d by scientific name, %d by common name%s%s)",
        n_matched,
        n_bou,
        n_explicit,
        n_sci,
        n_common,
        f", {n_excluded} excluded by status" if n_excluded else "",
        f", {n_overridden} status override(s)" if n_overridden else "",
    )
    if unmatched:
        logger.debug(
            "BOU filter: %d BTO species not matched in BirdNET labels "
            "(tried explicit international_english_name, scientific and common name): %s",
            len(unmatched),
            ", ".join(unmatched[:30]) + ("…" if len(unmatched) > 30 else ""),
        )

    return frozenset(allowed)
