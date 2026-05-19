"""
Tempest WeatherFlow personal weather station plugin.

Fetches current conditions from the WeatherFlow cloud API for a Tempest
station (https://weatherflow.com/tempest-weather-system/). Unlike other
providers, location is identified by station ID rather than lat/lon.

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
2. Go to *Settings → Data Authorizations* and generate a personal access token.
3. Your station ID appears in the URL when viewing your station, e.g.
   ``https://tempestwx.com/station/12345/``.

Response fields used from ``current_conditions``
------------------------------------------------
* ``air_temperature``       — °C
* ``sea_level_pressure``    — hPa
* ``relative_humidity``     — %
* ``wind_avg``              — m/s
* ``wind_direction``        — degrees (0–360)
* ``precip_accum_last_1hr`` — mm in the last hour
* ``conditions``            — human-readable sky condition, e.g. "Clear"

To write a new PWS plugin, copy this file to ``weather/pws_<name>.py``,
implement ``fetch(lat, lon, ts) -> WeatherData | None``, and set
``pws_plugin = "<name>"`` in config.toml.
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

    Reads ``current_conditions`` from the ``better_forecast`` endpoint.
    ``lat``, ``lon``, and ``ts`` are not used — the station is identified
    by its numeric ID and always returns the latest reading.
    Returns ``None`` if the token is missing, the API is unreachable, or
    the response can't be parsed.
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
    """Convert a value to float, or return ``None`` if missing or non-numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str(value: object) -> str | None:
    """Return the value as a stripped string, or ``None`` if empty or not a string."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if s else None
