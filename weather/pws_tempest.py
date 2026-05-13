"""
weather_pws_tempest.py — Tempest WeatherFlow personal weather station plugin.

Tempest (https://weatherflow.com/tempest-weather-system/) is a consumer PWS
that reports via the WeatherFlow cloud API.  This plugin fetches the
``better_forecast`` endpoint, which returns a ``current_conditions`` object
with named fields and a human-readable sky condition string.

Configuration (config.toml)
---------------------------
::

    [weather]
    enabled    = true
    provider   = "pws"
    pws_plugin = "tempest"

    [weather.pws_tempest]
    station_id = 12345          # numeric station ID from tempestwx.com
    token      = "YOUR_TOKEN"   # personal access token from tempestwx.com

Obtaining credentials
---------------------
1. Create an account at https://tempestwx.com and claim your station.
2. Navigate to *Settings → Data Authorizations* and generate a personal
   access token (PAT).  Copy the token value into ``config.toml``.
3. Your station ID is shown in the URL when you view your station online,
   e.g. ``https://tempestwx.com/station/12345/``.

API details
-----------
Endpoint::

    GET https://swd.weatherflow.com/swd/rest/better_forecast
        ?station_id={id}
        &token={token}
        &units_temp=c
        &units_wind=mps
        &units_pressure=mb
        &units_precip=mm
        &units_distance=km

The response contains a ``current_conditions`` object with the following
fields (all may be ``None`` if the sensor has no current reading):

* ``air_temperature``       — °C
* ``sea_level_pressure``    — hPa (mb)
* ``relative_humidity``     — %
* ``wind_avg``              — m/s (average)
* ``wind_direction``        — degrees (0–360)
* ``wind_gust``             — m/s (3-second gust; not stored separately)
* ``precip_accum_last_1hr`` — mm in the last hour
* ``conditions``            — human-readable sky condition string,
                              e.g. "Clear", "Partly Cloudy", "Light Rain"
* ``time``                  — Unix timestamp of the observation

Writing a new PWS plugin
------------------------
Copy this file to ``weather/pws_<yourstation>.py``, implement the single
``fetch(lat, lon, ts) -> WeatherData | None`` function, and set
``pws_plugin = "<yourstation>"`` in ``[weather]`` config.toml.  No changes
to ``weather/__init__.py`` or ``detector.py`` are needed.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from config import cfg
from . import WeatherData

logger = logging.getLogger(__name__)

_BASE_URL = "https://swd.weatherflow.com/swd/rest/better_forecast"


def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
    """Fetch current conditions from the Tempest WeatherFlow cloud API.

    Calls the ``better_forecast`` endpoint and reads ``current_conditions``
    from the JSON response.  Latitude and longitude are not used because the
    station is identified by its numeric ID; location is fixed to wherever
    the physical Tempest unit is installed.

    Args:
        lat: Latitude (not used; Tempest reads from the registered station).
        lon: Longitude (not used; Tempest reads from the registered station).
        ts:  Detection timestamp (not used; returns the live sensor reading).

    Returns:
        A populated :class:`~weather.WeatherData` instance, or ``None`` if
        the API is unreachable, the token is invalid, or the response cannot
        be parsed.
    """
    tempest = cfg.weather.pws_tempest

    if not tempest.token:
        logger.warning(
            "[weather/tempest] no token configured — set pws_tempest.token in config.toml"
        )
        return None

    params = urllib.parse.urlencode(
        {
            "station_id":      tempest.station_id,
            "token":           tempest.token,
            "units_temp":      "c",
            "units_wind":      "mps",
            "units_pressure":  "mb",
            "units_precip":    "mm",
            "units_distance":  "km",
        }
    )
    url = f"{_BASE_URL}?{params}"

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "bird-detector/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 401:
                logger.warning(
                    "[weather/tempest] HTTP 401 — check your token in config.toml"
                )
                return None
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            logger.warning(
                "[weather/tempest] HTTP 401 — check your token in config.toml"
            )
        else:
            logger.debug("[weather/tempest] HTTP error %s: %s", exc.code, exc)
        return None
    except urllib.error.URLError as exc:
        logger.debug("[weather/tempest] network error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[weather/tempest] unexpected error: %s", exc)
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.debug("[weather/tempest] JSON parse error: %s", exc)
        return None

    cc = data.get("current_conditions")
    if not isinstance(cc, dict):
        logger.debug(
            "[weather/tempest] missing or malformed current_conditions in response"
        )
        return None

    return WeatherData(
        temperature    = _float(cc.get("air_temperature")),
        humidity       = _float(cc.get("relative_humidity")),
        wind_speed     = _float(cc.get("wind_avg")),
        wind_direction = _float(cc.get("wind_direction")),
        pressure       = _float(cc.get("sea_level_pressure")),
        condition      = _str(cc.get("conditions")),
        precipitation  = _float(cc.get("precip_accum_last_1hr")),
        provider       = "tempest",
    )


def _float(value: object) -> float | None:
    """Coerce *value* to float, returning ``None`` for missing or non-numeric data."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str(value: object) -> str | None:
    """Return *value* as a stripped string, or ``None`` if empty / not a string."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if s else None
