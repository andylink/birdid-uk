#!/usr/bin/env python3
"""
add_ebird_codes.py — Enrich species_bto_FINAL_filtered.json with eBird codes.

Downloads the AviCommons species catalogue (https://avicommons.org/latest.json),
matches each BTO species to an AviCommons entry via three-stage lookup, and
writes the ``ebird_code`` field (or ``null``) back into the JSON in-place.

Matching stages (first match wins):
  1. Scientific name   — exact, case-insensitive
  2. International English name (hyphen-normalised)
  3. BTO British name  (hyphen-normalised)

Hyphen normalisation: replace ``-`` with space, lowercase, strip whitespace.

Manual overrides are applied before the automatic stages.

Usage:
    python add_ebird_codes.py
    python add_ebird_codes.py --dry-run   # print report but don't write file
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parent
SPECIES_JSON = REPO_ROOT / "species_bto_FINAL_filtered.json"

AVICOMMONS_URL = "https://avicommons.org/latest.json"
AVICOMMONS_CDN = "https://static.avicommons.org"

# ── Manual overrides ───────────────────────────────────────────────────────────
# BTO British name → eBird code.  Applied before automatic matching.
# Needed when scientific-name lookup fails (e.g. genus reclassification) and
# the English-name lookup is ambiguous or absent in AviCommons.

MANUAL_OVERRIDES: dict[str, str] = {
    "Lesser Redpoll":    "redpol1",   # shares code with Arctic Redpoll
    "Arctic Redpoll":    "redpol1",   # mealy/Arctic lumped in eBird
    "Lesser Sand Plover": "lessap2",  # Siberian Sand-Plover, UK-relevant form
    "Greater Sand Plover": "grsplo",  # Anarhynchus leschenaultii (genus reclassified)
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _norm(s: str | None) -> str:
    """Hyphen-normalise: lower-case, replace hyphens with spaces, strip."""
    if not s:
        return ""
    return s.replace("-", " ").lower().strip()


def _fetch_avicommons(url: str) -> list[dict]:
    print(f"Downloading AviCommons catalogue from {url} …")
    req = urllib.request.Request(url, headers={"User-Agent": "bird-detector/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(f"  → {len(data)} AviCommons entries loaded.")
    return data


def _build_lookup_tables(avi_entries: list[dict]) -> tuple[
    dict[str, dict],   # sciname_lower → AviCommons entry
    dict[str, dict],   # norm_name     → AviCommons entry
]:
    by_sci:  dict[str, dict] = {}
    by_name: dict[str, dict] = {}

    for entry in avi_entries:
        sci  = (entry.get("sciName") or "").lower().strip()
        name = _norm(entry.get("name"))

        if sci:
            by_sci.setdefault(sci, entry)
        if name:
            by_name.setdefault(name, entry)

    return by_sci, by_name


def _image_url(avi_entry: dict) -> str | None:
    """Return the AviCommons CDN image URL for an entry, or None if key is absent."""
    code = avi_entry.get("code")
    key  = avi_entry.get("key")
    if code and key:
        return f"{AVICOMMONS_CDN}/{code}-{key}-320.jpg"
    return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the match report but do not modify the JSON file.",
    )
    args = parser.parse_args()

    # Load BTO species list
    with SPECIES_JSON.open(encoding="utf-8") as fh:
        entries: list[dict] = json.load(fh)

    # Download AviCommons catalogue
    try:
        avi_entries = _fetch_avicommons(AVICOMMONS_URL)
    except Exception as exc:
        sys.exit(f"ERROR: Could not download AviCommons catalogue: {exc}")

    by_sci, by_name = _build_lookup_tables(avi_entries)

    # ── Match each BTO species ────────────────────────────────────────────────

    matched_auto   = 0
    matched_manual = 0
    unmatched: list[str] = []

    # Build a lookup from code → AviCommons entry (for manual-override image URLs)
    by_code: dict[str, dict] = {e["code"]: e for e in avi_entries if e.get("code")}

    for entry in entries:
        bto_name  = entry.get("name") or ""
        sci_name  = (entry.get("scientific_name") or "").lower().strip()
        int_name  = _norm(entry.get("international_english_name"))
        norm_bto  = _norm(bto_name)

        # Stage 0: manual override
        if bto_name in MANUAL_OVERRIDES:
            code = MANUAL_OVERRIDES[bto_name]
            entry["ebird_code"] = code
            avi = by_code.get(code)
            entry["avicommons_image_url"] = _image_url(avi) if avi else None
            matched_manual += 1
            continue

        # Stage 1: scientific name
        avi = by_sci.get(sci_name)
        if avi:
            entry["ebird_code"] = avi["code"]
            entry["avicommons_image_url"] = _image_url(avi)
            matched_auto += 1
            continue

        # Stage 2: international English name (hyphen-normalised)
        if int_name:
            avi = by_name.get(int_name)
            if avi:
                entry["ebird_code"] = avi["code"]
                entry["avicommons_image_url"] = _image_url(avi)
                matched_auto += 1
                continue

        # Stage 3: BTO British name (hyphen-normalised)
        avi = by_name.get(norm_bto)
        if avi:
            entry["ebird_code"] = avi["code"]
            entry["avicommons_image_url"] = _image_url(avi)
            matched_auto += 1
            continue

        # No match
        entry["ebird_code"] = None
        entry["avicommons_image_url"] = None
        unmatched.append(bto_name)

    total = len(entries)
    matched = matched_auto + matched_manual
    print(
        f"\nMatch report: {matched}/{total} matched "
        f"({matched_auto} automatic, {matched_manual} manual override)"
    )

    if unmatched:
        print(f"\nUnmatched ({len(unmatched)}):")
        for name in unmatched:
            print(f"  - {name}")
    else:
        print("All species matched — no nulls.")

    if args.dry_run:
        print("\n--dry-run: file not modified.")
        return

    with SPECIES_JSON.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"\nWrote {SPECIES_JSON}")


if __name__ == "__main__":
    main()
