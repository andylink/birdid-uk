"""
weather_pws_meteobridge.py — Meteobridge personal weather station plugin.

Meteobridge (https://www.meteobridge.com) is a network bridge that connects
professional weather stations (e.g. Davis Vantage Vue / Vantage Pro 2, and
many others) to internet weather services.  It exposes a simple HTTP template
API that expands bracketed variable names into live sensor readings.

Configuration (config.toml)
---------------------------
::

    [weather]
    enabled    = true
    provider   = "pws"
    pws_plugin = "meteobridge"

    [weather.pws_meteobridge]
    host            = "192.168.1.100"   # Meteobridge IP address or hostname
    port            = 80
    username        = "meteobridge"     # HTTP Basic Auth credentials
    password        = "meteobridge"
    wind_speed_unit = "ms"              # "ms" (m/s default) or "kmh"
    template        = "[th0temp-act];[th0hum-act];[wind0avgspd-act];[wind0dir-act];[msl0press-act];[rain0rate-act]"

Template format
---------------
Values are fetched in a single HTTP request using a semicolon-separated
template string.  The order of variables is fixed:

    temp ; humidity ; wind_speed ; wind_direction ; pressure ; rain_rate

If your station uses different sensor numbering (e.g. ``th1`` for a second
outdoor sensor), edit the ``template`` value in ``[weather.pws_meteobridge]``.
Meteobridge returns ``------`` (six dashes) for any sensor that is offline or
has no current reading; these are treated as ``None``.

Wind speed unit
---------------
Meteobridge can report wind speed in m/s or km/h depending on the unit
settings in its web interface.  The default here is m/s (``wind_speed_unit
= "ms"``).  If your setup reports km/h, set ``wind_speed_unit = "kmh"`` and
the plugin converts to m/s automatically.

Note on condition
-----------------
Personal weather stations measure raw atmospheric data; they do not report a
sky condition string (clear, cloudy, raining, etc.).  The ``condition`` field
is therefore always ``None`` for this provider.  Sky state can be inferred
from precipitation rate and solar radiation if those sensors are available,
but that logic is left to future extensions.

Writing a new PWS plugin
------------------------
Copy this file to ``weather/pws_<yourstation>.py``, implement the single
``fetch(lat, lon, ts) -> WeatherData | None`` function, and set
``pws_plugin = "<yourstation>"`` in ``[weather]`` config.toml.  No changes
to ``weather/__init__.py`` or ``detector.py`` are needed.
"""

from __future__ import annotations

import base64
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from config import cfg
from . import WeatherData

logger = logging.getLogger(__name__)

_NULL_SENTINEL = "------"  # Meteobridge default null placeholder


def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
    """Fetch current readings from Meteobridge via the HTTP template API.

    Sends a single GET request to ``/cgi-bin/template.cgi`` with the
    configured template string.  The response is a semicolon-delimited list
    of sensor values in template order.

    Args:
        lat: Latitude (not used; Meteobridge reads from local sensors).
        lon: Longitude (not used; Meteobridge reads from local sensors).
        ts:  Detection timestamp (not used; returns live sensor readings).

    Returns:
        A populated :class:`~weather.WeatherData` instance, or ``None``
        if the device is unreachable or the response cannot be parsed.
    """
    mb       = cfg.weather.pws_meteobridge
    host     = mb.host
    port     = mb.port
    username = mb.username
    password = mb.password
    template = mb.template

    params = urllib.parse.urlencode({"template": template})
    url    = f"http://{host}:{port}/cgi-bin/template.cgi?{params}"

    try:
        req = urllib.request.Request(url)
        # HTTP Basic Authentication
        credentials = base64.b64encode(
            f"{username}:{password}".encode()
        ).decode()
        req.add_header("Authorization", f"Basic {credentials}")
        req.add_header("User-Agent", "bird-detector/1.0")

        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
    except urllib.error.URLError as exc:
        logger.debug("[weather/meteobridge] network error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[weather/meteobridge] unexpected error: %s", exc)
        return None

    # Response is semicolon-separated values in template order:
    # temp ; humidity ; wind_speed ; wind_direction ; pressure ; rain_rate
    parts = body.split(";")
    if len(parts) < 6:
        logger.debug(
            "[weather/meteobridge] unexpected response (%d fields, expected ≥6): %r",
            len(parts), body,
        )
        return None

    temp = _parse(parts[0])
    hum  = _parse(parts[1])
    wspd = _parse(parts[2])
    wdir = _parse(parts[3])
    pres = _parse(parts[4])
    rain = _parse(parts[5])

    # Convert wind speed to m/s if the station is configured to report km/h
    if mb.wind_speed_unit == "kmh" and wspd is not None:
        wspd = wspd / 3.6

    return WeatherData(
        temperature    = temp,
        humidity       = hum,
        wind_speed     = wspd,
        wind_direction = wdir,
        pressure       = pres,
        condition      = None,   # PWS stations don't report a sky condition
        precipitation  = rain,
        provider       = "meteobridge",
    )


def _parse(s: str) -> float | None:
    """Parse a single Meteobridge template field.

    Returns ``None`` for the null sentinel (``------``), empty strings, or
    any value that cannot be converted to float.
    """
    s = s.strip()
    if not s or s == _NULL_SENTINEL:
        return None
    try:
        return float(s)
    except ValueError:
        return None
