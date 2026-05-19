"""
Yr.no / met.no weather provider.

Fetches current conditions from the Norwegian Meteorological Institute's
Locationforecast 2.0 API (https://api.met.no). Free, no API key needed.
Their terms of service require a descriptive User-Agent header; this module
sets it to ``bird-detector/1.0 https://github.com/anomalyco/bird-detector``.

API reference: https://api.met.no/weatherapi/locationforecast/2.0/documentation
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import WeatherData

logger = logging.getLogger(__name__)

_BASE_URL   = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
_USER_AGENT = "bird-detector/1.0 https://github.com/anomalyco/bird-detector"

# Maps yr.no symbol code prefixes to plain-English condition strings.
# Checked in order; first match wins, so more specific entries come first.
# Full symbol list: https://api.met.no/weatherapi/weathericon/2.0/documentation
_SYMBOL_MAP: list[tuple[str, str]] = [
    ("clearsky",             "Clear sky"),
    ("fair",                 "Fair"),
    ("partlycloudy",         "Partly cloudy"),
    ("cloudy",               "Overcast"),
    ("fog",                  "Fog"),
    ("heavyrainandthunder",  "Heavy rain with thunder"),
    ("heavyrain",            "Heavy rain"),
    ("heavyrainshowers",     "Heavy rain showers"),
    ("lightrainandthunder",  "Light rain with thunder"),
    ("lightrain",            "Light rain"),
    ("lightrainshowers",     "Light rain showers"),
    ("rainandthunder",       "Rain with thunder"),
    ("rainshowers",          "Rain showers"),
    ("rain",                 "Rain"),
    ("heavysleetandthunder", "Heavy sleet with thunder"),
    ("heavysleet",           "Heavy sleet"),
    ("lightsleet",           "Light sleet"),
    ("sleet",                "Sleet"),
    ("heavysnowandthunder",  "Heavy snow with thunder"),
    ("heavysnow",            "Heavy snow"),
    ("lightsnow",            "Light snow"),
    ("snowandthunder",       "Snow with thunder"),
    ("snowshowers",          "Snow showers"),
    ("snow",                 "Snow"),
]


def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
    """Fetch current conditions from yr.no Locationforecast 2.0.

    Uses the first (most recent) time-step from the forecast series.
    Precipitation comes from ``next_1_hours`` if present, else ``next_6_hours``.
    ``ts`` is not used directly. Returns ``None`` if the request fails.
    """
    params = urllib.parse.urlencode({
        "lat": round(lat, 4),
        "lon": round(lon, 4),
    })
    url = f"{_BASE_URL}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as exc:
        logger.debug("[weather/yr_no] network error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[weather/yr_no] unexpected error: %s", exc)
        return None

    try:
        ts_data = body["properties"]["timeseries"][0]["data"]
        instant = ts_data["instant"]["details"]
        # Prefer next_1_hours; fall back to next_6_hours if absent
        next_period = (
            ts_data.get("next_1_hours")
            or ts_data.get("next_6_hours")
            or {}
        )
        next_details = next_period.get("details", {})
        symbol_code  = next_period.get("summary", {}).get("symbol_code", "")
    except (KeyError, IndexError, TypeError) as exc:
        logger.debug("[weather/yr_no] unexpected response structure: %s", exc)
        return None

    return WeatherData(
        temperature    = _f(instant.get("air_temperature")),
        humidity       = _f(instant.get("relative_humidity")),
        wind_speed     = _f(instant.get("wind_speed")),
        wind_direction = _f(instant.get("wind_from_direction")),
        pressure       = _f(instant.get("air_pressure_at_sea_level")),
        condition      = _symbol_to_condition(symbol_code),
        precipitation  = _f(next_details.get("precipitation_amount")),
        provider       = "yr_no",
    )


def _symbol_to_condition(symbol_code: str) -> str | None:
    """Map a yr.no symbol code (e.g. ``clearsky_day``) to a plain string."""
    if not symbol_code:
        return None
    # Strip the time-of-day suffix (_day, _night, _polartwilight)
    base = symbol_code.split("_")[0].lower()
    for prefix, label in _SYMBOL_MAP:
        if base == prefix:
            return label
    # Unknown code: title-case it as a fallback
    return symbol_code.replace("_", " ").title()


def _f(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
