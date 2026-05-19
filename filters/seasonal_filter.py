"""
seasonal_filter.py — skips detections for species outside their expected season.

Loads uk_seasonal_filter.json (built from GBIF Great Britain occurrence data)
and checks whether a species is expected in the UK during the current ISO week.
This avoids false positives from species that are only present part of the year.

Using GBIF GB data rather than BirdNET's built-in metadata avoids the North
American eBird bias in BirdNET's own seasonal model.

To customise for your site, copy uk_seasonal_filter.json to a local copy,
edit the week ranges, and point [seasonal_filter] filter_json in config.toml
at that file.

ISO week numbers
----------------
Weeks are ISO 8601 week numbers (1–52, occasionally 53). Week 53 (which occurs
roughly every 5–6 years, e.g. 2020 and 2026) is clamped to 52 so it always
matches the JSON, which only stores weeks 1–52.

Filter behaviour
----------------
- Species absent from the JSON → no restriction (assumed year-round or sparse data).
- Species present in the JSON → allowed only if the current week is in their list.
- Applied after the BOU allowlist and before per-species confidence thresholds.

Usage:
    from seasonal_filter import SeasonalFilter, current_iso_week

    sf = SeasonalFilter()          # loads JSON once at construction
    week = current_iso_week()
    if not sf.check(species, week):
        continue                   # out of season — skip this detection
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_JSON = Path(__file__).parent / "uk_seasonal_filter.json"


def current_iso_week(ts: datetime | None = None) -> int:
    """Return the ISO week number (1–52) for the given datetime.

    Args:
        ts: UTC datetime. Defaults to now.

    Returns:
        ISO week number 1–52. Week 53 is clamped to 52 to match the JSON range.
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    week = ts.isocalendar()[1]
    return min(week, 52)


class SeasonalFilter:
    """Checks whether a species is expected in the UK during a given ISO week.

    Loaded once at startup from the JSON file. Species not listed in the JSON
    are treated as unrestricted (present year-round).

    Attributes:
        enabled:   Whether the filter is active. If False, check() always returns True.
        json_path: Path of the loaded JSON file.
    """

    def __init__(self, enabled: bool = True, json_path: Path | None = None) -> None:
        self.enabled   = enabled
        self.json_path = json_path or _DEFAULT_JSON
        # {birdnet_common_name: frozenset of allowed ISO week numbers}
        self._allowed: dict[str, frozenset[int]] = {}

        if not self.enabled:
            return

        if not self.json_path.exists():
            logger.warning(
                "seasonal_filter: %s not found — seasonal filtering disabled. "
                "Run build_uk_seasonal_filter.py to generate it.",
                self.json_path,
            )
            self.enabled = False
            return

        try:
            with open(self.json_path) as fh:
                data: dict = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "seasonal_filter: failed to load %s: %s", self.json_path, exc
            )
            self.enabled = False
            return

        species_data: dict[str, list[int]] = data.get("species", {})
        # Keys are normalised to lowercase so check() is case-insensitive,
        # consistent with NocturnalFilter's approach.
        self._allowed = {
            name.lower(): frozenset(weeks)
            for name, weeks in species_data.items()
        }

        week_scale = data.get("_metadata", {}).get("week_scale", "?")
        logger.info(
            "seasonal_filter: loaded %d species with restrictions from %s (week scale: %s)",
            len(self._allowed),
            self.json_path.name,
            week_scale,
        )

    def check(self, species: str, week: int) -> bool:
        """Return True if the species is expected during the given week.

        Args:
            species: BirdNET common name (case-insensitive — lookup is normalised to lowercase).
            week:    ISO week number 1–52 (use current_iso_week()).

        Returns:
            True if the species is unrestricted or within its seasonal window.
            False if the species has a restriction that excludes this week.
        """
        if not self.enabled:
            return True

        allowed_weeks = self._allowed.get(species.lower())
        if allowed_weeks is None:
            # Species not listed — no restriction
            return True

        return week in allowed_weeks
