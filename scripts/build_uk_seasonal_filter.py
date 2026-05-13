#!/usr/bin/env python3
"""
build_uk_seasonal_filter.py — Generate uk_seasonal_filter.json from GBIF
Great Britain occurrence data.

For each BTO-listed species this script:

  1. Looks up the GBIF taxon key via api.gbif.org/v1/species/match (scientific name).
  2. Queries monthly GB occurrence counts via the GBIF occurrence facet API
     (country=GB, facet=month) — one HTTP request per matched species.
  3. Normalises each month's count as a fraction of the species' annual total.
  4. Marks a month as "present" if its fraction exceeds the threshold (default 2%).
  5. Maps present calendar months to ISO week numbers (1–52) using a fixed
     month→week table.
  6. Species present in all 12 months are omitted (no restriction needed).
  7. Species with fewer than MIN_RECORDS total GB records are also omitted
     (data too sparse to be reliable).

The JSON keys are BirdNET common names in the configured locale (en_uk by default),
not BTO British names, because that is what the detector sees at runtime.

Usage:
    python build_uk_seasonal_filter.py
    python build_uk_seasonal_filter.py --threshold 0.03
    python build_uk_seasonal_filter.py --locale en_uk --output uk_seasonal_filter.json
    python build_uk_seasonal_filter.py --inspect "Barn Swallow"
    python build_uk_seasonal_filter.py --inspect "Water Rail"
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).parent
BOU_JSON     = REPO_ROOT / "uk_species_filter.json"
OUTPUT_JSON  = REPO_ROOT / "uk_seasonal_filter.json"

# Minimum fraction of annual GB records for a month to be considered "present".
# 0.02 = 2%.  A species recorded uniformly all year scores ~8.3% per month, so
# 2% comfortably includes year-round residents while excluding months with only
# a handful of vagrant records.
DEFAULT_THRESHOLD = 0.02

# Species with fewer total GB records than this are skipped — not enough data.
MIN_RECORDS = 30

DEFAULT_LOCALE = "en_uk"

GBIF_API = "https://api.gbif.org/v1"

# Polite delay between GBIF requests (seconds).
REQUEST_DELAY = 0.25

# Fixed month → ISO-week mapping.  Approximate but consistent; covers weeks
# 1–52 exactly (5 months have 5 weeks, 7 months have 4 weeks).
MONTH_TO_ISO_WEEKS: dict[int, list[int]] = {
    1:  [1,  2,  3,  4],
    2:  [5,  6,  7,  8],
    3:  [9,  10, 11, 12, 13],
    4:  [14, 15, 16, 17],
    5:  [18, 19, 20, 21, 22],
    6:  [23, 24, 25, 26],
    7:  [27, 28, 29, 30],
    8:  [31, 32, 33, 34, 35],
    9:  [36, 37, 38, 39],
    10: [40, 41, 42, 43, 44],
    11: [45, 46, 47, 48],
    12: [49, 50, 51, 52],
}


# ── Label helpers ──────────────────────────────────────────────────────────────

def load_birdnet_label_lookups(locale: str) -> tuple[dict[str, str], dict[str, str]]:
    """Load the BirdNET label file and return two lookup dicts.

    Returns:
        sci_to_common:         {scientific_name_lower: birdnet_common_name}
        common_lower_to_common:{birdnet_common_name_lower: birdnet_common_name}
    """
    import birdnet_analyzer
    base = Path(birdnet_analyzer.__file__).parent
    locale_norm = locale.replace("-", "_")
    label_path = (
        base / "labels" / "V2.4"
        / f"BirdNET_GLOBAL_6K_V2.4_Labels_{locale_norm}.txt"
    )
    if not label_path.exists():
        print(
            f"  WARNING: locale label file not found ({label_path.name}); "
            "falling back to global English.",
            file=sys.stderr,
        )
        label_path = base / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"

    print(f"  BirdNET labels: {label_path.name}")

    sci_to_common:          dict[str, str] = {}
    common_lower_to_common: dict[str, str] = {}

    for line in label_path.read_text().splitlines():
        line = line.strip()
        if "_" not in line:
            continue
        sci, _, common = line.partition("_")
        sci    = sci.strip()
        common = common.strip()
        if sci and common:
            sci_to_common[sci.lower()]          = common
            common_lower_to_common[common.lower()] = common

    return sci_to_common, common_lower_to_common


def match_bto_to_birdnet(
    sp:                     dict,
    sci_to_common:          dict[str, str],
    common_lower_to_common: dict[str, str],
) -> str | None:
    """Return the BirdNET common name for a BTO species entry using 3-stage matching.

    Stage 0: explicit ``international_english_name`` field (handles UK vs IOC splits,
             e.g. "Wigeon" → "Eurasian Wigeon").
    Stage 1: scientific name match.
    Stage 2: BTO British common name vs BirdNET common name (case-insensitive).

    Returns ``None`` if no match is found.
    """
    intl  = (sp.get("international_english_name") or "").strip()
    sci   = (sp.get("scientific_name")            or "").strip().lower()
    bto   = (sp.get("name")                        or "").strip().lower()

    # Stage 0
    if intl and intl.lower() in common_lower_to_common:
        return common_lower_to_common[intl.lower()]

    # Stage 1
    if sci and sci in sci_to_common:
        return sci_to_common[sci]

    # Stage 2
    if bto and bto in common_lower_to_common:
        return common_lower_to_common[bto]

    return None


# ── GBIF helpers ───────────────────────────────────────────────────────────────

def gbif_get(url: str, max_retries: int = 4) -> dict | None:
    """HTTP GET a GBIF API endpoint; retries on 429 with exponential backoff."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "bird-detector/build_uk_seasonal_filter"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 5 * 2 ** attempt
                print(
                    f"\n  [rate-limited] waiting {wait}s before retry…",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                print(f"\n  HTTP {exc.code}: {url}", file=sys.stderr)
                return None
        except Exception as exc:
            print(f"\n  Request error: {exc}", file=sys.stderr)
            return None
    return None


def lookup_gbif_key(scientific_name: str) -> int | None:
    """Return the GBIF usageKey for *scientific_name*, or None if not found."""
    encoded = urllib.parse.quote(scientific_name)
    url     = (
        f"{GBIF_API}/species/match"
        f"?name={encoded}&kingdom=Animalia&class=Aves"
    )
    data = gbif_get(url)
    if not data:
        return None
    match_type = data.get("matchType", "NONE")
    confidence = int(data.get("confidence", 0))
    if match_type in ("EXACT", "FUZZY") and confidence >= 80:
        return data.get("usageKey")
    return None


def get_gb_monthly_counts(gbif_key: int) -> dict[int, int]:
    """Return ``{month: record_count}`` for Great Britain occurrences.

    Missing months (no records) are absent from the returned dict (treat as 0).
    """
    url = (
        f"{GBIF_API}/occurrence/search"
        f"?country=GB&taxonKey={gbif_key}"
        f"&facet=month&facetLimit=12&limit=0"
    )
    data = gbif_get(url)
    if not data:
        return {}

    counts: dict[int, int] = {}
    for facet in data.get("facets", []):
        if facet.get("field") == "MONTH":
            for entry in facet.get("counts", []):
                counts[int(entry["name"])] = int(entry["count"])
    return counts


# ── Week helpers ───────────────────────────────────────────────────────────────

def months_to_iso_weeks(present_months: set[int]) -> list[int]:
    """Map a set of present calendar months to sorted ISO week numbers (1–52)."""
    weeks: set[int] = set()
    for m in present_months:
        for w in MONTH_TO_ISO_WEEKS.get(m, []):
            weeks.add(w)
    return sorted(weeks)


def weeks_to_ranges(weeks: list[int]) -> str:
    """Format a week list as compact ranges, e.g. '14–39, 49–52, 1–8'."""
    if not weeks:
        return "none"
    if len(weeks) == 52:
        return "all year"
    s = sorted(weeks)
    ranges: list[str] = []
    start = prev = s[0]
    for w in s[1:]:
        if w == prev + 1:
            prev = w
        else:
            ranges.append(f"{start}–{prev}" if start != prev else str(start))
            start = prev = w
    ranges.append(f"{start}–{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def build_week_reference() -> dict[str, str]:
    """Return {str(week): "D Mon"} for ISO weeks 1–52 using 2025 as reference."""
    ref: dict[str, str] = {}
    for week in range(1, 53):
        try:
            monday = datetime.date.fromisocalendar(2025, week, 1)
            ref[str(week)] = monday.strftime("%-d %b")
        except ValueError:
            break  # 2025 only has 52 weeks; stop gracefully
    return ref


# ── Inspect helper ─────────────────────────────────────────────────────────────

def inspect_species(
    name:       str,
    bou_species: list[dict],
    sci_to_common: dict[str, str],
    common_lower_to_common: dict[str, str],
    threshold: float,
) -> None:
    """Print detailed GBIF monthly data and derived seasonality for one species."""
    target = name.strip().lower()

    # Find a match in the BTO list
    hit_sp: dict | None = None
    hit_birdnet: str | None = None
    for sp in bou_species:
        birdnet_name = match_bto_to_birdnet(sp, sci_to_common, common_lower_to_common)
        bto_name = sp.get("name", "")
        if (
            bto_name.lower() == target
            or (birdnet_name and birdnet_name.lower() == target)
        ):
            hit_sp      = sp
            hit_birdnet = birdnet_name
            break

    if hit_sp is None:
        print(f"  '{name}' not found in BTO species list.")
        return

    sci_name = hit_sp.get("scientific_name", "?")
    print(f"\n  BTO name    : {hit_sp['name']}")
    print(f"  BirdNET name: {hit_birdnet or '(no match)'}")
    print(f"  Scientific  : {sci_name}")

    gbif_key = lookup_gbif_key(sci_name)
    if not gbif_key:
        print(f"  GBIF key    : not found")
        return
    print(f"  GBIF key    : {gbif_key}")
    time.sleep(REQUEST_DELAY)

    counts = get_gb_monthly_counts(gbif_key)
    total  = sum(counts.values())
    print(f"  GB records  : {total:,}")
    print(f"  Threshold   : {threshold * 100:.1f}% of annual total "
          f"(= {total * threshold:,.0f} records/month)")
    print()

    present_months: set[int] = set()
    month_names = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
    print(f"  {'Month':>5}  {'Records':>8}  {'Fraction':>8}  {'Present':>7}")
    print(f"  {'─'*5}  {'─'*8}  {'─'*8}  {'─'*7}")
    for m in range(1, 13):
        cnt  = counts.get(m, 0)
        frac = cnt / total if total else 0.0
        flag = "  YES" if frac >= threshold else "   no"
        if frac >= threshold:
            present_months.add(m)
        print(f"  {month_names[m-1]:>5}  {cnt:>8,}  {frac:>7.1%}  {flag}")

    iso_weeks = months_to_iso_weeks(present_months)
    print(f"\n  Present months : {', '.join(month_names[m-1] for m in sorted(present_months))}")
    print(f"  ISO weeks ({len(iso_weeks):2d}/52): {weeks_to_ranges(iso_weeks)}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=(
            f"Fraction of annual GB records for a month to count as 'present' "
            f"(default {DEFAULT_THRESHOLD:.2f} = {DEFAULT_THRESHOLD*100:.0f}%%)"
        ),
    )
    parser.add_argument(
        "--min-records", type=int, default=MIN_RECORDS,
        help=f"Skip species with fewer total GB records than this (default {MIN_RECORDS})",
    )
    parser.add_argument(
        "--locale", default=DEFAULT_LOCALE,
        help=f"BirdNET label locale for JSON keys (default '{DEFAULT_LOCALE}')",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_JSON,
        help=f"Output JSON path (default {OUTPUT_JSON.name})",
    )
    parser.add_argument(
        "--inspect", metavar="SPECIES",
        help="Print detailed GBIF monthly data for one species then exit",
    )
    args = parser.parse_args()

    # ── Load BTO species list ──────────────────────────────────────────────────
    if not BOU_JSON.exists():
        print(f"ERROR: {BOU_JSON} not found", file=sys.stderr)
        sys.exit(1)
    bou_species: list[dict] = json.loads(BOU_JSON.read_text())
    print(f"BTO species loaded  : {len(bou_species)}")

    # ── Load BirdNET label lookups ─────────────────────────────────────────────
    print("Loading BirdNET label file...")
    sci_to_common, common_lower_to_common = load_birdnet_label_lookups(args.locale)
    print(f"  Labels loaded     : {len(sci_to_common)} species")

    # ── Inspect mode ───────────────────────────────────────────────────────────
    if args.inspect:
        inspect_species(
            args.inspect, bou_species,
            sci_to_common, common_lower_to_common,
            args.threshold,
        )
        return

    # ── Process each BTO species ───────────────────────────────────────────────
    print(
        f"\nQuerying GBIF (country=GB) for {len(bou_species)} species "
        f"[threshold={args.threshold*100:.0f}%, min_records={args.min_records}]..."
    )

    seasonal:       dict[str, list[int]] = {}
    n_year_round    = 0
    n_sparse        = 0
    n_no_gbif       = 0
    n_unmatched_bn  = 0
    n_absent        = 0

    for i, sp in enumerate(bou_species, 1):
        bto_name  = sp.get("name", "?")
        sci_name  = (sp.get("scientific_name") or "").strip()

        # Progress indicator
        print(f"  [{i:3d}/{len(bou_species)}] {bto_name:<35}", end="\r", flush=True)

        # Match to BirdNET label name
        birdnet_name = match_bto_to_birdnet(sp, sci_to_common, common_lower_to_common)
        if not birdnet_name:
            n_unmatched_bn += 1
            continue

        # GBIF species lookup
        if not sci_name:
            n_no_gbif += 1
            continue

        time.sleep(REQUEST_DELAY)
        gbif_key = lookup_gbif_key(sci_name)
        if not gbif_key:
            n_no_gbif += 1
            continue

        # Monthly occurrence counts in GB
        time.sleep(REQUEST_DELAY)
        counts = get_gb_monthly_counts(gbif_key)
        total  = sum(counts.values())

        if total < args.min_records:
            n_sparse += 1
            continue

        # Determine present months
        present_months: set[int] = set()
        for month in range(1, 13):
            frac = counts.get(month, 0) / total
            if frac >= args.threshold:
                present_months.add(month)

        if len(present_months) == 12:
            n_year_round += 1
            # Year-round — no restriction entry needed
            continue

        if len(present_months) == 0:
            n_absent += 1
            continue

        iso_weeks = months_to_iso_weeks(present_months)
        seasonal[birdnet_name] = iso_weeks

    print()  # clear progress line

    # Sort alphabetically for readable diffs
    seasonal = dict(sorted(seasonal.items()))

    # ── Write output ───────────────────────────────────────────────────────────
    output = {
        "_metadata": {
            "generated":              datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source":                 "GBIF occurrence data (country=GB)",
            "gbif_api":               GBIF_API,
            "locale":                 args.locale,
            "threshold":              args.threshold,
            "min_records":            args.min_records,
            "week_scale":             52,
            "bou_species_total":      len(bou_species),
            "bou_species_unmatched_birdnet": n_unmatched_bn,
            "bou_species_no_gbif":    n_no_gbif,
            "bou_species_sparse":     n_sparse,
            "species_year_round":     n_year_round,
            "species_with_restriction": len(seasonal),
            "species_absent":         n_absent,
            "note": (
                "ISO weeks (1-52) when each species IS expected in Great Britain, "
                "derived from GBIF occurrence frequency. Species absent from 'species' "
                "have no seasonal restriction (year-round or data too sparse). "
                "Months are mapped to ISO weeks using the fixed MONTH_TO_ISO_WEEKS "
                "table in build_uk_seasonal_filter.py. "
                "Edit or replace this file with a local copy for site-specific overrides."
            ),
            "month_to_iso_weeks": MONTH_TO_ISO_WEEKS,
            "week_reference": build_week_reference(),
        },
        "species": seasonal,
    }

    args.output.write_text(json.dumps(output, indent=2))

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\nResults:")
    print(f"  Year-round (omitted)           : {n_year_round}")
    print(f"  Seasonal restrictions written  : {len(seasonal)}")
    print(f"  Absent all year (omitted)      : {n_absent}")
    print(f"  Sparse GBIF data (omitted)     : {n_sparse}")
    print(f"  No GBIF key found (omitted)    : {n_no_gbif}")
    print(f"  No BirdNET label match (skipped): {n_unmatched_bn}")
    print(f"\nOutput: {args.output}")

    examples = list(seasonal.items())[:8]
    if examples:
        print("\nSample entries:")
        for name, weeks in examples:
            print(f"  {name:<35} weeks {weeks_to_ranges(weeks)}")


if __name__ == "__main__":
    main()
