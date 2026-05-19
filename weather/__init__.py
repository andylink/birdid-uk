"""
Weather metadata for bird detections.

Fetches current conditions at the configured lat/lon and attaches a snapshot
to each detection. Results are cached for ``cfg.weather.cache_seconds``
(default 300 s) so a burst of detections only triggers one API call.

Supported providers
-------------------
``"open_meteo"``
    Free, no API key needed. https://open-meteo.com

``"yr_no"``
    Norwegian Met Institute, free, no API key. https://api.met.no

``"openweathermap"``
    Free tier available; requires ``api_key`` in ``[weather]`` config.toml.

``"pws"``
    Personal weather station. ``cfg.weather.pws_plugin`` names the plugin
    module: ``weather/pws_<plugin>.py``.

PWS plugin interface
--------------------
Each plugin must expose::

    def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
        ...

Catch all exceptions inside ``fetch`` and return ``None`` on failure — the
detection loop must never be interrupted by a weather error.

Built-in plugins:
    ``weather/pws_meteobridge.py`` — Meteobridge bridge device
    ``weather/pws_tempest.py``     — Tempest WeatherFlow station

To add a new plugin: create ``weather/pws_<name>.py``, implement ``fetch``,
then set ``provider = "pws"`` and ``pws_plugin = "<name>"`` in config.toml.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import ModuleType

from config import cfg

logger = logging.getLogger(__name__)


# ── Weather data container ─────────────────────────────────────────────────────

@dataclass
class WeatherData:
    """Weather conditions at detection time.

    All numeric fields are ``None`` if the provider couldn't supply that
    reading (sensor offline, API doesn't include it, etc.).

    Attributes:
        temperature:    Air temperature in °C.
        humidity:       Relative humidity, 0–100 %.
        wind_speed:     Mean wind speed in m/s.
        wind_direction: Wind direction in degrees clockwise from north.
        pressure:       Sea-level pressure in hPa.
        condition:      Human-readable sky description, e.g. "Partly cloudy".
                        Always ``None`` for PWS providers.
        precipitation:  Precipitation in mm. Exact meaning varies by provider
                        (current rate, last-hour total, etc.).
        provider:       Which data source produced this reading, e.g. "open_meteo".
    """
    temperature:    float | None = None
    humidity:       float | None = None
    wind_speed:     float | None = None
    wind_direction: float | None = None
    pressure:       float | None = None
    condition:      str | None   = None
    precipitation:  float | None = None
    provider:       str          = field(default="")


# ── Module-level state ─────────────────────────────────────────────────────────

_provider: ModuleType | None = None  # loaded once by init_weather()

# Simple one-slot cache: timestamp + last result
_cache_ts:   datetime | None    = None
_cache_data: WeatherData | None = None


# ── Public API ─────────────────────────────────────────────────────────────────

def init_weather() -> None:
    """Load the configured weather provider module.

    Does nothing if ``[weather] enabled = false``. Logs an error and leaves
    ``_provider`` as ``None`` if the module can't be imported; all subsequent
    ``get_weather()`` calls will return ``None`` silently.

    Called once from ``detector.main()`` at startup.
    """
    global _provider

    if not cfg.weather.enabled:
        return

    provider_name = cfg.weather.provider

    if provider_name == "pws":
        module_name = f"weather.pws_{cfg.weather.pws_plugin}"
    else:
        module_name = f"weather.{provider_name}"

    try:
        _provider = importlib.import_module(module_name)
        logger.info(
            "[weather] provider: %s (module: %s, cache: %d s)",
            provider_name, module_name, cfg.weather.cache_seconds,
        )
    except ImportError as exc:
        logger.error(
            "[weather] cannot load provider module %r: %s",
            module_name, exc,
        )


def get_weather(ts: datetime) -> WeatherData | None:
    """Return current weather, served from cache if fresh enough.

    Returns ``None`` if weather is disabled, the provider failed to load, or
    the fetch raises an exception. On fetch failure, stale cached data is
    returned rather than nothing (logged at DEBUG). Never raises.

    Args:
        ts: Detection timestamp. Passed to the provider but most providers
            ignore it and always return the latest available reading.
    """
    global _cache_ts, _cache_data

    if not cfg.weather.enabled or _provider is None:
        return None

    now = datetime.now(tz=timezone.utc)
    if _cache_ts is not None:
        age = (now - _cache_ts).total_seconds()
        if age < cfg.weather.cache_seconds:
            return _cache_data

    try:
        data = _provider.fetch(cfg.location.lat, cfg.location.lon, ts)
        _cache_ts   = now
        _cache_data = data
        if data is not None:
            logger.debug(
                "[weather] %s  %.1f°C  %d%%  %.1f m/s  %.1f hPa  %s",
                data.provider,
                data.temperature    or 0.0,
                data.humidity       or 0,
                data.wind_speed     or 0.0,
                data.pressure       or 0.0,
                data.condition      or "–",
            )
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[weather] fetch failed: %s — %s",
            exc,
            "returning stale data" if _cache_data is not None else "no data available",
        )
        return _cache_data  # stale is better than nothing
