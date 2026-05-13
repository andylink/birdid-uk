"""
weather.py — weather metadata provider for bird detections.

Fetches current weather conditions at the configured lat/lon at detection
time and attaches the snapshot to each saved detection.  Data is cached for
``cfg.weather.cache_seconds`` (default 300 s) so a burst of rapid detections
only triggers a single upstream API call.

Providers
---------
``"open_meteo"``
    Open-Meteo (https://open-meteo.com).  Completely free; no registration
    or API key required.  Provides current conditions for any lat/lon.

``"yr_no"``
    Yr.no / Norwegian Meteorological Institute (https://api.met.no).
    Free, no key required.  ``User-Agent`` is set to ``bird-detector/1.0``
    as required by their terms of service.

``"openweathermap"``
    OpenWeatherMap (https://openweathermap.org).  Free tier available.
    Requires ``api_key`` in ``[weather]`` config.toml.

``"pws"``
    Personal Weather Station plugin.  ``cfg.weather.pws_plugin`` names the
    provider module: ``weather_pws_<plugin>.py``.

PWS plugins
-----------
Each plugin must expose a single function::

    def fetch(lat: float, lon: float, ts: datetime) -> WeatherData | None:
        ...

The function should catch all exceptions internally and return ``None`` on
failure so the detect loop is never interrupted.

Built-in plugin
    ``weather_pws_meteobridge.py`` — Meteobridge bridge device (Davis Vantage
    Vue / Vantage Pro and many other stations).

Writing a new plugin
    1. Create ``weather_pws_<name>.py`` in the project root.
    2. Implement ``fetch(lat, lon, ts) -> WeatherData | None``.
    3. Set ``provider = "pws"`` and ``pws_plugin = "<name>"`` in
       ``[weather]`` config.toml.
    That's it — no changes to this file required.
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
    """Snapshot of weather conditions at detection time.

    All numeric fields may be ``None`` if the provider could not supply
    that particular reading (e.g. a sensor is offline, or the API does
    not include that variable).

    Attributes:
        temperature:    Dry-bulb air temperature in °C.
        humidity:       Relative humidity in percent (0–100).
        wind_speed:     Mean wind speed in m/s.
        wind_direction: Wind direction in degrees clockwise from north (0–360).
        pressure:       Sea-level atmospheric pressure in hPa.
        condition:      Human-readable sky/weather description, e.g.
                        ``"Partly cloudy"``, ``"Light rain"``.  ``None`` for
                        PWS providers that do not report a sky condition.
        precipitation:  Precipitation amount in mm.  Interpretation varies
                        by provider: current rate (mm/h), last-hour total, or
                        last-reading total.
        provider:       Identifier of the data source, e.g. ``"open_meteo"``,
                        ``"yr_no"``, ``"meteobridge"``.
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

# One-slot cache: (fetch timestamp UTC, WeatherData | None)
_cache_ts:   datetime | None   = None
_cache_data: WeatherData | None = None


# ── Public API ─────────────────────────────────────────────────────────────────

def init_weather() -> None:
    """Load the configured weather provider module.

    No-op when ``[weather] enabled = false``.  Logs a clear error and leaves
    ``_provider`` as ``None`` if the module cannot be imported; all subsequent
    ``get_weather()`` calls will silently return ``None`` in that case.

    Called once from ``detector.main()`` after ``init_db()`` and
    ``init_mqtt()``.
    """
    global _provider

    if not cfg.weather.enabled:
        return

    provider_name = cfg.weather.provider

    if provider_name == "pws":
        module_name = f"weather_pws_{cfg.weather.pws_plugin}"
    else:
        module_name = f"weather_{provider_name}"

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
    """Return the current weather reading, using a short-lived cache.

    Returns ``None`` if weather is disabled, the provider failed to load,
    or the fetch raises an exception.  On failure, stale cached data is
    returned if available (logged at DEBUG).  This function never raises.

    Args:
        ts: Detection timestamp (used only for debug logging; the provider
            always fetches the most current reading available).

    Returns:
        A :class:`WeatherData` instance, or ``None``.
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
