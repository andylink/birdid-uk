"""
nocturnal_filter.py — restricts detections for night-active species to appropriate hours.

For each species listed in uk_nocturnal_filter.json, detections are only accepted
within the species' active window. Daytime detections of owls and other nocturnal
or crepuscular species are likely false positives and are discarded.

Two window types are supported:

sunset_sunrise (recommended)
    Active window runs from (sunset + sunset_offset_minutes) to
    (sunrise + sunrise_offset_minutes). Offset sign convention:
      - sunset_offset_minutes < 0  → window starts before sunset
      - sunrise_offset_minutes > 0 → window extends past sunrise into the morning

    Sunrise/sunset times are computed from the lat/lon in config.toml using the
    astral library, cached per calendar date, and compared in the configured timezone.

fixed
    Active window is a fixed local clock range, e.g.:
      {"type": "fixed", "start": "21:00", "end": "05:00"}
    Windows that span midnight (start > end) are handled correctly.

Species not listed in the data file or config are unrestricted.

Per-species config overrides
-----------------------------
Add an active_hours inline table to any [species."Name"] block in config.toml
to override or add a restriction:

    [species."Tawny Owl"]
    min_detections = 1
    active_hours   = {type = "sunset_sunrise", sunset_offset_minutes = -60, sunrise_offset_minutes = 90}

    [species."Barn Owl"]
    active_hours   = {type = "fixed", start = "20:00", end = "06:00"}

Config overrides take priority over the JSON file.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun as _astral_sun

logger = logging.getLogger(__name__)


class NocturnalFilter:
    """Time-of-day gate for nocturnal and crepuscular species.

    Parameters
    ----------
    enabled:
        If False, check() always returns True (no filtering).
    json_path:
        Path to the JSON file mapping species names to active window specs.
        Defaults to uk_nocturnal_filter.json.
    lat, lon:
        WGS-84 decimal degrees for sunrise/sunset calculation.
    timezone_str:
        IANA timezone name, e.g. "Europe/London". All time comparisons use this zone.
    species_overrides:
        The [species] dict from config.toml. Entries with an active_hours key
        override the JSON file for that species.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        json_path: Path,
        lat: float,
        lon: float,
        timezone_str: str,
        species_overrides: dict[str, dict],
    ) -> None:
        self.enabled = enabled
        self._tz = ZoneInfo(timezone_str)
        self._location = LocationInfo(
            name="Garden",
            region="UK",
            timezone=timezone_str,
            latitude=lat,
            longitude=lon,
        )
        # Sunrise/sunset results cached by date. Safe without locking — classify loop is single-threaded.
        self._sun_cache: dict[date, dict[str, datetime]] = {}

        # Active window specs keyed by BirdNET common name (case-sensitive as stored in JSON)
        self._windows: dict[str, dict] = {}

        if enabled:
            try:
                with open(json_path) as fh:
                    raw = json.load(fh)
                self._windows = raw.get("species", {})
                logger.debug(
                    "Nocturnal filter: loaded %d species from %s",
                    len(self._windows), json_path,
                )
            except FileNotFoundError:
                logger.warning(
                    "Nocturnal filter JSON not found: %s — filter disabled", json_path
                )
                self.enabled = False

        # Config overrides take priority over the JSON file
        for species, overrides in species_overrides.items():
            if "active_hours" in overrides:
                self._windows[species] = overrides["active_hours"]
                logger.debug(
                    "Nocturnal filter: config override applied for %r", species
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_sun(self, local_date: date) -> dict[str, datetime]:
        """Return astral sunrise/sunset times for the given date, using a per-date cache.

        Old entries (more than 2 days back) are evicted to keep memory use low
        for long-running processes.
        """
        if local_date not in self._sun_cache:
            self._sun_cache[local_date] = _astral_sun(
                self._location.observer,
                date=local_date,
                tzinfo=self._tz,
            )
            # Keep only today and yesterday
            cutoff = local_date - timedelta(days=2)
            for stale in [d for d in self._sun_cache if d < cutoff]:
                del self._sun_cache[stale]
        return self._sun_cache[local_date]

    def _get_window(self, species: str) -> dict | None:
        """Return the active window spec for a species, or None if unrestricted.

        Case-insensitive lookup to handle minor capitalisation differences in BirdNET output.
        """
        species_lower = species.lower()
        for key, val in self._windows.items():
            if key.lower() == species_lower:
                return val
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, species: str, ts: datetime) -> bool:
        """Return True to allow the detection, False to discard it.

        A detection passes if:
        - The filter is disabled, or
        - The species has no time restriction, or
        - The detection timestamp falls within the species' active window.

        Parameters
        ----------
        species:
            BirdNET common name, e.g. "Tawny Owl".
        ts:
            Detection timestamp (timezone-aware, typically UTC from the classify loop).
        """
        if not self.enabled:
            return True

        window = self._get_window(species)
        if window is None:
            return True  # no restriction for this species

        ts_local = ts.astimezone(self._tz)
        wtype = window.get("type", "sunset_sunrise")

        if wtype == "sunset_sunrise":
            s = self._get_sun(ts_local.date())
            sunrise_offset = timedelta(minutes=window.get("sunrise_offset_minutes", 0))
            sunset_offset  = timedelta(minutes=window.get("sunset_offset_minutes",  0))

            # The "daytime" band is from (sunrise + morning margin) to (sunset + evening margin).
            # The species is active — and the detection is allowed — outside this band.
            daytime_start = s["sunrise"] + sunrise_offset
            daytime_end   = s["sunset"]  + sunset_offset

            return not (daytime_start < ts_local < daytime_end)

        elif wtype == "fixed":
            from datetime import time as _time
            start = _time.fromisoformat(window["start"])
            end   = _time.fromisoformat(window["end"])
            t     = ts_local.time()
            # Strip tzinfo from the time component so comparisons work cleanly
            t = t.replace(tzinfo=None)

            if start > end:
                # Overnight window (e.g. 21:00–05:00): active after start OR before end
                return t >= start or t <= end
            else:
                # Same-day window: active between start and end
                return start <= t <= end

        else:
            logger.warning(
                "Nocturnal filter: unknown window type %r for %r — allowing",
                wtype, species,
            )
            return True
