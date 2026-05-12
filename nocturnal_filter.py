"""
nocturnal_filter.py — time-of-day gate for nocturnal and crepuscular species.

For each species listed in the filter JSON (default: uk_nocturnal_filter.json),
detections are only accepted within the species' active window.  Detections
that fall in the middle of the day are discarded as likely false positives.

Two window types are supported:

``sunset_sunrise`` (recommended)
    The active window spans from (sunset + sunset_offset_minutes) to
    (sunrise + sunrise_offset_minutes).  Offset signs follow the convention:

      - ``sunset_offset_minutes < 0``  → window starts *before* sunset
      - ``sunrise_offset_minutes > 0`` → window extends *past* sunrise into the morning

    Sunrise and sunset are computed from [location] lat/lon in config.toml
    using the *astral* library and cached per calendar date.  All comparisons
    are made in the detector's configured timezone ([general] timezone).

``fixed``
    The active window is a fixed local clock-time range, e.g.
    ``{"type": "fixed", "start": "21:00", "end": "05:00"}``.  A window that
    spans midnight (start > end) is handled correctly.

Species absent from both the data file and config overrides are unrestricted.

Per-species config overrides
-----------------------------
Add an ``active_hours`` inline table to any ``[species."Name"]`` block in
config.toml to override (or add) a time restriction::

    [species."Tawny Owl"]
    min_detections = 1
    active_hours   = {type = "sunset_sunrise", sunset_offset_minutes = -60, sunrise_offset_minutes = 90}

    [species."Barn Owl"]
    active_hours   = {type = "fixed", start = "20:00", end = "06:00"}

Config overrides take priority over the JSON data file.
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
        If ``False``, :meth:`check` always returns ``True`` (pass-through).
    json_path:
        Path to the JSON data file mapping BirdNET species names to active
        window specs (default: ``uk_nocturnal_filter.json``).
    lat, lon:
        WGS-84 decimal degrees — used for sunrise/sunset computation when
        ``type = "sunset_sunrise"`` windows are in use.
    timezone_str:
        IANA timezone name, e.g. ``"Europe/London"``.  All time comparisons
        are made in this timezone.
    species_overrides:
        Raw ``[species]`` dict from config.toml.  Any entry that contains an
        ``active_hours`` key overrides the JSON data file for that species.
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
        # Sunrise/sunset results cached per calendar date.
        # The classify loop is single-threaded so no locking is needed.
        self._sun_cache: dict[date, dict[str, datetime]] = {}

        # Windows keyed by BirdNET common name (case-sensitive as stored in JSON).
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

        # Apply per-species config overrides — these take priority over the JSON.
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
        """Return astral sunrise/sunset datetimes for *local_date*.

        Results are memoised; entries older than 2 days are evicted so the
        cache stays small over a long-running daemon.
        """
        if local_date not in self._sun_cache:
            self._sun_cache[local_date] = _astral_sun(
                self._location.observer,
                date=local_date,
                tzinfo=self._tz,
            )
            # Evict stale entries (keep only today and yesterday).
            cutoff = local_date - timedelta(days=2)
            for stale in [d for d in self._sun_cache if d < cutoff]:
                del self._sun_cache[stale]
        return self._sun_cache[local_date]

    def _get_window(self, species: str) -> dict | None:
        """Return the window spec for *species*, or ``None`` if unrestricted.

        Lookup is case-insensitive so minor capitalisation differences in
        BirdNET output are handled gracefully.
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
        """Return ``True`` to allow the detection, ``False`` to discard it.

        A detection passes when any of the following are true:

        * The filter is disabled.
        * The species has no time restriction in the data file or config.
        * The detection timestamp falls within the species' active window.

        Parameters
        ----------
        species:
            BirdNET common name (IOC English), e.g. ``"Tawny Owl"``.
        ts:
            Detection timestamp (timezone-aware, typically UTC from the
            classify loop).
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

            # The "daytime" band runs from (sunrise + morning_margin) to
            # (sunset + evening_margin, which may be before sunset if negative).
            # A detection is ALLOWED when it falls OUTSIDE this band.
            daytime_start = s["sunrise"] + sunrise_offset
            daytime_end   = s["sunset"]  + sunset_offset

            return not (daytime_start < ts_local < daytime_end)

        elif wtype == "fixed":
            from datetime import time as _time
            start = _time.fromisoformat(window["start"])
            end   = _time.fromisoformat(window["end"])
            t     = ts_local.time()
            # Strip tzinfo from the time component so comparisons work cleanly.
            t = t.replace(tzinfo=None)

            if start > end:
                # Overnight window (e.g. 21:00 → 05:00): active if AFTER start
                # OR BEFORE end.
                return t >= start or t <= end
            else:
                # Same-day window (unusual for nocturnal species): active if
                # within [start, end].
                return start <= t <= end

        else:
            logger.warning(
                "Nocturnal filter: unknown window type %r for %r — allowing",
                wtype, species,
            )
            return True
