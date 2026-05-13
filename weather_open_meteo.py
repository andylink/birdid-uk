"""
weather_open_meteo.py — Open-Meteo weather provider.

Open-Meteo (https://open-meteo.com) is a free, open-source weather API that
requires no registration or API key.  It provides current conditions worldwide
via the Forecast API, requesting only the ``current`` variables needed here so
the payload is minimal.

API reference: https://open-meteo.com/en/docs

This module exposes a single function, ``fetch``, matching the interface
expected by ``weather.py``::

    def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None

All exceptions are caught internally; the caller (``weather.get_weather``)
never sees an exception from this module.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from weather import WeatherData

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Variables requested in the ``current`` block.
# wind_speed_unit=ms requests m/s directly so no unit conversion is needed.
_CURRENT_VARS = (
    "temperature_2m,"
    "relative_humidity_2m,"
    "precipitation,"
    "wind_speed_10m,"
    "wind_direction_10m,"
    "surface_pressure,"
    "weather_code"
)

# WMO Weather Interpretation Codes → human-readable strings.
# https://open-meteo.com/en/docs#weathervariables
_WMO: dict[int, str] = {
    0:  "Clear sky",
    1:  "Mainly clear",
    2:  "Partly cloudy",
    3:  "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
    """Fetch current conditions from the Open-Meteo Forecast API.

    Args:
        lat: Latitude in WGS-84 decimal degrees.
        lon: Longitude in WGS-84 decimal degrees.
        ts:  Detection timestamp (not used directly; Open-Meteo always
             returns the most recent current observation).

    Returns:
        A populated :class:`~weather.WeatherData` instance, or ``None``
        if the request fails for any reason.
    """
    params = urllib.parse.urlencode({
        "latitude":        round(lat, 6),
        "longitude":       round(lon, 6),
        "current":         _CURRENT_VARS,
        "wind_speed_unit": "ms",
    })
    url = f"{_BASE_URL}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "bird-detector/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as exc:
        logger.debug("[weather/open_meteo] network error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[weather/open_meteo] unexpected error: %s", exc)
        return None

    cur = body.get("current", {})

    wmo_raw   = cur.get("weather_code")
    condition: str | None = None
    if wmo_raw is not None:
        try:
            condition = _WMO.get(int(wmo_raw), f"WMO {wmo_raw}")
        except (TypeError, ValueError):
            pass

    return WeatherData(
        temperature    = _f(cur.get("temperature_2m")),
        humidity       = _f(cur.get("relative_humidity_2m")),
        wind_speed     = _f(cur.get("wind_speed_10m")),
        wind_direction = _f(cur.get("wind_direction_10m")),
        pressure       = _f(cur.get("surface_pressure")),
        condition      = condition,
        precipitation  = _f(cur.get("precipitation")),
        provider       = "open_meteo",
    )


def _f(val: object) -> float | None:
    """Coerce a value to float; return ``None`` for missing or non-numeric."""
    if val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
