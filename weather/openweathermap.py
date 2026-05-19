"""
OpenWeatherMap weather provider.

Fetches current conditions from https://openweathermap.org/current.
A free API key is required — sign up at https://openweathermap.org/api.

Add to config.toml::

    [weather]
    enabled  = true
    provider = "openweathermap"
    api_key  = "your_key_here"
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

_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
    """Fetch current conditions from OpenWeatherMap.

    Uses ``units=metric`` so temperatures are °C and wind speed is m/s.
    Precipitation is last-hour rainfall in mm (``rain.1h``); ``None`` when
    the field is absent (i.e. no rain). ``ts`` is not used directly.
    Returns ``None`` if the API key is missing or the request fails.
    """
    api_key = cfg.weather.api_key
    if not api_key:
        logger.warning(
            "[weather/openweathermap] api_key is not set — "
            "add api_key = \"<your_key>\" to [weather] in config.toml"
        )
        return None

    params = urllib.parse.urlencode({
        "lat":   round(lat, 6),
        "lon":   round(lon, 6),
        "appid": api_key,
        "units": "metric",   # °C, m/s
    })
    url = f"{_BASE_URL}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "bird-detector/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            logger.warning(
                "[weather/openweathermap] HTTP 401 Unauthorized — "
                "check that api_key in config.toml is correct"
            )
        else:
            logger.debug("[weather/openweathermap] HTTP %d: %s", exc.code, exc.reason)
        return None
    except urllib.error.URLError as exc:
        logger.debug("[weather/openweathermap] network error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[weather/openweathermap] unexpected error: %s", exc)
        return None

    main    = body.get("main",    {})
    wind    = body.get("wind",    {})
    rain    = body.get("rain",    {})
    weather = body.get("weather", [{}])
    desc    = weather[0].get("description", "") if weather else ""

    return WeatherData(
        temperature    = _f(main.get("temp")),
        humidity       = _f(main.get("humidity")),
        wind_speed     = _f(wind.get("speed")),
        wind_direction = _f(wind.get("deg")),
        pressure       = _f(main.get("pressure")),
        condition      = str(desc).title() or None,
        precipitation  = _f(rain.get("1h")),   # mm last hour; absent when no rain
        provider       = "openweathermap",
    )


def _f(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
