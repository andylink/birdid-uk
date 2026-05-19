"""
Meteobridge personal weather station plugin.

Meteobridge (https://www.meteobridge.com) is a network bridge that connects
weather stations (Davis Vantage, and many others) to internet services. It
exposes a simple HTTP template API that substitutes bracketed variable names
with live sensor values.

Configuration (config.toml)
---------------------------
::

    [weather]
    enabled    = true
    provider   = "pws"
    pws_plugin = "meteobridge"

    [weather.pws_meteobridge]
    host            = "192.168.1.100"   # IP address or hostname
    port            = 80
    username        = "meteobridge"     # HTTP Basic Auth credentials
    password        = "meteobridge"
    wind_speed_unit = "ms"              # "ms" (m/s, default) or "kmh"
    template        = "[th0temp-act];[th0hum-act];[wind0avgspd-act];[wind0dir-act];[msl0press-act];[rain0rate-act]"

Template format
---------------
Values are fetched in a single request as a semicolon-separated string.
The order is fixed:

    temp ; humidity ; wind_speed ; wind_direction ; pressure ; rain_rate

If your station uses different sensor numbering (e.g. ``th1`` for a second
outdoor sensor), edit the ``template`` value in config.toml.
Meteobridge returns ``------`` for any sensor that has no current reading.

Wind speed
----------
Set ``wind_speed_unit = "kmh"`` if your Meteobridge is configured to report
km/h; this plugin will convert to m/s automatically.

Note: personal weather stations don't report a sky condition (clear, cloudy,
etc.), so ``condition`` is always ``None`` for this provider.

To write a new PWS plugin, copy this file to ``weather/pws_<name>.py``,
implement ``fetch(lat, lon, ts) -> WeatherData | None``, and set
``pws_plugin = "<name>"`` in config.toml.
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

_NULL_SENTINEL = "------"  # Meteobridge placeholder for missing/offline sensor


def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
    """Fetch live readings from Meteobridge via its HTTP template API.

    Sends one GET request to ``/cgi-bin/template.cgi``. The response is a
    semicolon-separated list of values matching the configured template order.
    ``lat``, ``lon``, and ``ts`` are not used — readings come from local sensors.
    Returns ``None`` if the device is unreachable or the response is malformed.
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

    # Response fields: temp ; humidity ; wind_speed ; wind_direction ; pressure ; rain_rate
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

    # Convert to m/s if the station reports km/h
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
    """Parse one Meteobridge template field.

    Returns ``None`` for the null sentinel (``------``), empty strings, or
    anything that isn't a valid number.
    """
    s = s.strip()
    if not s or s == _NULL_SENTINEL:
        return None
    try:
        return float(s)
    except ValueError:
        return None
