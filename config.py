"""
Loads config.toml and exposes all settings as typed dataclass instances.

Import ``cfg`` for direct access, or use ``get_species_config`` to retrieve
per-species settings with defaults already applied.

    from config import cfg, get_species_config

    sc = get_species_config("European Robin")
    print(sc.min_confidence, sc.cooldown_seconds)
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Find config.toml relative to this file, so the app can be run from any directory.
_CONFIG_PATH = Path(__file__).parent / "config.toml"


@dataclass(frozen=True)
class GeneralConfig:
    timezone:     str
    station_name: str  # shown in the dashboard header; leave empty for the default "BirdNet-UK"


@dataclass(frozen=True)
class LocationConfig:
    lat: float  # decimal degrees, north positive
    lon: float  # decimal degrees, east positive


@dataclass(frozen=True)
class PathsConfig:
    detections_dir:   Path
    db_path:          Path
    spectrograms_dir: Path


@dataclass(frozen=True)
class AudioSourceConfig:
    """One entry from an ``[[audio.sources]]`` block (multi-source mode).

    When the config defines multiple sources, each runs its own recording
    thread and classifier loop independently.

    Example config.toml fragment::

        [[audio.sources]]
        name   = "garden-north"
        type   = "sounddevice"
        device = 0

        [[audio.sources]]
        name      = "garden-south"
        type      = "rtsp"
        url       = "rtsp://192.168.1.10:554/audio"
        transport = "tcp"
        reconnect_delay_seconds = 5

    For ``type = "sounddevice"``: set *device* to the PortAudio device index
    (omit or use None for the system default).

    For ``type = "rtsp"``: set *url*, *transport*, *reconnect_delay_seconds*,
    and optionally *ffmpeg_path*.
    """
    name:                    str           # used in logs and clip filenames
    type:                    str           # "sounddevice" | "rtsp"
    # sounddevice only
    device:                  int | None = None
    # rtsp only
    url:                     str        = ""
    transport:               str        = "tcp"
    reconnect_delay_seconds: int        = 5
    ffmpeg_path:             str        = "ffmpeg"


@dataclass(frozen=True)
class AudioRtspConfig:
    """Settings for receiving audio over RTSP (used when ``[audio] source = "rtsp"``).

    FFmpeg is launched as a subprocess to decode the stream to raw PCM piped to stdout.

    Use ``transport = "tcp"`` for reliability on most networks; ``"udp"`` has lower
    latency but may drop packets when the network is busy.

    Set *ffmpeg_path* to an absolute path if ffmpeg is not on the system PATH.
    """
    url:                     str   # e.g. rtsp://192.168.1.100:554/audio
    transport:               str   # "tcp" (recommended) | "udp"
    reconnect_delay_seconds: int   # how long to wait before reconnecting after a drop
    ffmpeg_path:             str   # path to ffmpeg binary


@dataclass(frozen=True)
class AudioConfig:
    sample_rate:             int
    hop_seconds:             int
    device:                  int | None
    source:                  str   # "sounddevice" (local mic) | "rtsp" (network stream)
    rtsp:                    AudioRtspConfig
    clip_seconds:            int   # total saved clip length — only used when clip_mode="full"
    pre_capture_seconds:     int   # audio to include before the detection window (clip_mode="full" only)
    capture_buffer_seconds:  int   # ring buffer size; must be larger than the longest clip
    # "window" saves the model's analysis window plus window_pad_seconds of leading audio.
    # "full" uses the older clip_seconds / pre_capture_seconds approach.
    clip_mode:               str   # "window" | "full"
    window_pad_seconds:      float # seconds of audio before the window start (clip_mode="window")
    # post_capture_seconds is not stored here — it depends on the model's window length,
    # which isn't known until the model is loaded. It's computed in detector.main().
    sources:                 tuple[AudioSourceConfig, ...] | None = None  # None = legacy single-source mode


@dataclass(frozen=True)
class SpeciesConfig:
    """Detection settings for a single species, combining defaults with any per-species overrides."""
    min_confidence:              float
    cooldown_seconds:            int
    # A detection is only saved after the species is seen min_detections times
    # within confirmation_window_seconds. Set min_detections = 1 to save on first hit.
    min_detections:              int
    confirmation_window_seconds: float
    # Per-species override for cross-validation disagreement handling.
    # None means fall back to the global [cross_validation] on_disagree setting.
    # Use "flag" for rare or nocturnal species so disagreements can be reviewed.
    on_disagree:                 str | None = None


@dataclass(frozen=True)
class FilterConfig:
    enabled:   bool
    cutoff_hz: float
    order:     int


@dataclass(frozen=True)
class RetentionConfig:
    enabled:                  bool
    max_age_days:             int
    max_usage_percent:        float
    min_clips_per_species:    int
    run_interval_seconds:     int
    spectrogram_max_age_days: int


@dataclass(frozen=True)
class LogConfig:
    enabled:        bool
    path:           Path
    rotation:       str   # "daily" or "size"
    max_size_bytes: int
    backup_count:   int
    level:          str   # "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"


@dataclass(frozen=True)
class DatabaseConfig:
    type:        str   # "sqlite" | "postgresql"
    host:        str
    port:        int
    name:        str
    username:    str
    password:    str
    timescaledb: bool  # if True, initialise TimescaleDB hypertables (postgresql only)


@dataclass(frozen=True)
class MqttConfig:
    enabled:  bool
    broker:   str
    port:     int
    topic:    str
    username: str
    password: str
    retain:   bool


@dataclass(frozen=True)
class BirdmapConfig:
    enabled:      bool
    api_url:      str
    api_key:      str
    station_id:   int
    upload_audio: bool


@dataclass(frozen=True)
class BirdweatherConfig:
    """Credentials and options for posting detections to app.birdweather.com.

    Register a station at https://app.birdweather.com to get a *token*.
    When *upload_audio* is True, the detection's FLAC clip is uploaded first
    as a soundscape so it appears with audio playback in the BirdWeather timeline.
    """
    enabled:      bool
    token:        str   # station authentication token
    upload_audio: bool  # upload the FLAC clip before posting the detection


@dataclass(frozen=True)
class SeasonalFilterConfig:
    """Drops detections for species that are not expected to be present in the current week.

    Uses ISO week numbers (1–52) from *filter_json* to decide which species are
    in season. Species not listed in the JSON are treated as year-round.

    To customise, copy ``uk_seasonal_filter.json`` and point *filter_json* at your copy.
    """
    enabled:     bool
    filter_json: Path


@dataclass(frozen=True)
class NocturnalFilterConfig:
    """Drops daytime detections of nocturnal or crepuscular species.

    Two window types are supported (see ``nocturnal_filter.py`` for details):

    * ``sunset_sunrise`` — window relative to today's sunrise/sunset, computed
      from [location] lat/lon. Supports per-event offsets in minutes.
    * ``fixed`` — fixed local clock-time range (HH:MM), spanning midnight if
      start > end.

    Per-species active hours can be overridden in ``[species."Name"]`` blocks
    using the ``active_hours`` key, which takes priority over the JSON file.
    """
    enabled:     bool
    filter_json: Path


@dataclass(frozen=True)
class SpeciesFilterConfig:
    """Controls which BOU-listed species are included based on their status.

    Species whose ``british_list_status`` contains any token from *exclude_status*
    (case-insensitive) are removed from the allowlist before matching.

    Examples::

        exclude_status = ["Accidental"]            # drop extreme vagrants
        exclude_status = ["Accidental", "Escaped"] # also drop escaped species

    Leave empty to accept all BOU-listed species.
    """
    exclude_status: tuple[str, ...]   # tuple for hashability


@dataclass(frozen=True)
class InferenceConfig:
    """Selects the bird classification model to use.

    ``"birdnet"`` (default) uses the bundled BirdNET GLOBAL 6K V2.4 model.
    No extra setup required. Species names are translated from BirdNET's IOC
    labels to BTO British names by the species filter.

    ``"perch"`` uses Google Perch v2 (TensorFlow), downloaded from Kaggle on
    first run (~400 MB). Requires ``perch-hoplite[tf]`` and Kaggle credentials;
    see requirements.txt for details.
    """
    model: str   # "birdnet" | "perch"


@dataclass(frozen=True)
class WeatherPwsMeteobridgeConfig:
    """Connection settings for a Meteobridge personal weather station.

    Meteobridge exposes an HTTP template API where bracketed variable names are
    expanded into sensor readings. The *template* string uses semicolons as
    separators; values are parsed in this order: temp, humidity, wind_speed,
    wind_direction, pressure, rain_rate.

    If your Meteobridge reports wind speed in km/h, set ``wind_speed_unit = "kmh"``
    and the plugin will convert to m/s automatically.
    """
    host:            str    # IP address or hostname of the Meteobridge device
    port:            int    # HTTP port (default 80)
    username:        str    # HTTP Basic Auth username
    password:        str    # HTTP Basic Auth password
    template:        str    # Meteobridge template string (semicolon-separated values)
    wind_speed_unit: str    # "ms" (default) or "kmh"


@dataclass(frozen=True)
class WeatherPwsTempestConfig:
    """Credentials for a Tempest WeatherFlow personal weather station.

    Get your *station_id* and *token* from tempestwx.com under
    Settings → Data Authorizations.

    Uses the ``better_forecast`` endpoint, which returns named JSON fields and
    a human-readable conditions string (e.g. "Clear", "Light Rain"). Units are
    metric (°C, m/s, hPa, mm).
    """
    station_id: int   # numeric ID from the tempestwx.com URL
    token:      str   # personal access token from tempestwx.com


@dataclass(frozen=True)
class WeatherConfig:
    """Controls fetching and storing weather data with each detection.

    When enabled, a weather snapshot is taken at detection time and saved
    alongside the record in the ``detections`` table. Results are cached for
    *cache_seconds* to avoid redundant API calls during bursts of detections.

    *provider* options:

    * ``"open_meteo"``     — free, no API key needed.
    * ``"yr_no"``          — free, no API key needed.
    * ``"openweathermap"`` — free tier, requires *api_key*.
    * ``"pws"``            — personal weather station; *pws_plugin* names the
                             module to use (``weather_pws_<plugin>.py``).

    Built-in PWS plugins:

    * ``weather_pws_meteobridge.py`` — configure in ``[weather.pws_meteobridge]``.
    * ``weather_pws_tempest.py``     — configure in ``[weather.pws_tempest]``.
    """
    enabled:         bool
    provider:        str   # "open_meteo" | "yr_no" | "openweathermap" | "pws"
    api_key:         str   # required for openweathermap; unused by other providers
    cache_seconds:   int   # reuse the same reading for this many seconds
    pws_plugin:      str   # plugin name when provider = "pws"
    pws_meteobridge: WeatherPwsMeteobridgeConfig
    pws_tempest:     WeatherPwsTempestConfig


@dataclass(frozen=True)
class AdminConfig:
    """Credentials and session settings for the dashboard admin interface.

    password_hash and session_secret are written by install.sh; do not edit
    these manually.  Leave both empty to disable admin auth entirely.
    """
    password_hash:         str    # bcrypt hash of the admin password
    session_secret:        str    # random secret for signing HTTP-only session cookies
    session_ttl:           int    # session cookie lifetime in seconds (default 86400 = 24h)
    auto_verify_threshold: float  # confidence >= this value sets verification_status to 'auto'


@dataclass(frozen=True)
class PrivacyFilterConfig:
    """Discards clips that contain audible human speech before saving.

    Uses silero-vad (a lightweight neural voice detector) to scan each
    confirmed detection clip. If the fraction of voiced speech in the clip
    reaches *min_voiced_fraction*, the clip is dropped entirely — no file,
    no database row, no publish.

    Bird song does not trigger this filter; a typical Robin clip scores ~0%
    voiced, while a clip with audible human speech scores ~30%+.

    * *threshold* — per-frame speech probability cutoff for silero-vad (0.5
      is the recommended default).
    * *min_voiced_fraction* — how much of the clip (0–1) must be voiced to
      trigger a drop. 0.10 means 10% voiced speech is enough to discard it.
      Lower values are more sensitive; higher values require more speech.
    """
    enabled:            bool
    threshold:          float  # per-frame probability cutoff [0, 1]
    min_voiced_fraction: float  # fraction of clip that triggers a drop


@dataclass(frozen=True)
class DeduplicationConfig:
    """Suppresses duplicate detections when the same species is heard on multiple sources.

    Only applies in multi-source mode (``[[audio.sources]]``). Ignored in
    single-source mode.

    If the same species is detected from a different source within
    *window_seconds* of the first detection, it is treated as a duplicate.

    *on_duplicate* controls what happens:
    - ``"flag"`` — saves the detection with ``deduplicated = true`` for review (recommended).
    - ``"skip"`` — silently discards it (no clip, no database row).
    """
    enabled:        bool = False
    window_seconds: int  = 10
    on_duplicate:   str  = "flag"   # "flag" | "skip"


@dataclass(frozen=True)
class CrossValidationConfig:
    """Re-checks detections using a second model to reduce false positives.

    When enabled, every detection confirmed by the primary model is also run
    through the other model (BirdNET or Perch, whichever is not primary). The
    two models' top species are compared by BTO-resolved name.

    *skip_threshold*: if the primary model's confidence is at or above this
    value, skip the second model entirely and save the detection as-is. This
    avoids the overhead of a second inference when the primary is highly confident.

    *on_disagree*: what to do when the models identify different species:
    - ``"drop"`` — discard the detection silently (maximises precision; default).
    - ``"flag"`` — save it with ``flagged = True`` for manual review.

    Per-species overrides can be set in ``[species."<name>"]`` blocks.

    When models agree, ``detections.confidence`` is the average of both scores.
    When CV is skipped, the primary score is used. The raw primary score is
    always stored in ``detections.primary_confidence`` for reference.
    """
    enabled:           bool
    skip_threshold:    float   # skip second model if primary confidence >= this
    on_disagree:       str     # "drop" | "flag"
    # Minimum score for the secondary model to count as a valid candidate.
    # BirdNET scores range [0, 1]; Perch softmax probabilities over ~10k classes
    # are much smaller, so keep this low (~0.01) to avoid filtering out Perch results.
    cv_min_confidence: float


@dataclass(frozen=True)
class Config:
    paths:            PathsConfig
    audio:            AudioConfig
    inference:        InferenceConfig
    cross_validation: CrossValidationConfig
    privacy_filter:   PrivacyFilterConfig
    deduplication:    DeduplicationConfig
    filter:           FilterConfig
    retention:        RetentionConfig
    log:              LogConfig
    database:         DatabaseConfig
    mqtt:             MqttConfig
    birdmap:          BirdmapConfig
    birdweather:      BirdweatherConfig
    seasonal_filter:  SeasonalFilterConfig
    nocturnal_filter: NocturnalFilterConfig
    species_filter:   SpeciesFilterConfig
    defaults:         SpeciesConfig
    general:          GeneralConfig
    location:         LocationConfig
    weather:          WeatherConfig
    admin:            AdminConfig
    exclude:          frozenset[str]   # species names to always suppress (case-insensitive)
    # Per-species override dicts from [species."Name"] blocks, keyed by common name.
    _species_overrides: dict[str, dict] = field(default_factory=dict, repr=False)

    def bou_override_species(self) -> frozenset[str]:
        """Return species names that have ``species_status_override = true`` set.

        These species are force-included in the BOU allowlist and name map even
        if their BOU status would normally exclude them (e.g. "Accidental").
        Names should match the BirdNET common name or BTO British name — both
        are tried during matching.
        """
        return frozenset(
            name
            for name, overrides in self._species_overrides.items()
            if overrides.get("species_status_override", False)
        )

    def get_species_config(self, species: str) -> SpeciesConfig:
        """Return detection settings for *species*, with per-species overrides applied.

        Falls back to [defaults] for any value not overridden. Lookup is
        case-insensitive.
        """
        overrides: dict = {}
        for key, val in self._species_overrides.items():
            if key.lower() == species.lower():
                overrides = val
                break

        d = self.defaults
        return SpeciesConfig(
            min_confidence              = overrides.get("min_confidence",              d.min_confidence),
            cooldown_seconds            = overrides.get("cooldown_seconds",            d.cooldown_seconds),
            min_detections              = overrides.get("min_detections",              d.min_detections),
            confirmation_window_seconds = overrides.get("confirmation_window_seconds", d.confirmation_window_seconds),
            on_disagree                 = overrides.get("on_disagree",                 None),
        )


def _load() -> Config:
    with open(_CONFIG_PATH, "rb") as fh:
        raw = tomllib.load(fh)

    g = raw.get("general", {})
    general_cfg = GeneralConfig(
        timezone     = str(g.get("timezone",     "UTC")),
        station_name = str(g.get("station_name", "")),
    )

    loc = raw.get("location", {})
    location_cfg = LocationConfig(
        lat = float(loc.get("lat", 0.0)),
        lon = float(loc.get("lon", 0.0)),
    )
    if not (-90 <= location_cfg.lat <= 90):
        raise ValueError(
            f"[location] lat must be between -90 and 90, got {location_cfg.lat}"
        )
    if not (-180 <= location_cfg.lon <= 180):
        raise ValueError(
            f"[location] lon must be between -180 and 180, got {location_cfg.lon}"
        )

    p = raw["paths"]
    paths = PathsConfig(
        detections_dir   = Path(p["detections_dir"]),
        db_path          = Path(p["db_path"]),
        spectrograms_dir = Path(p.get("spectrograms_dir", "data/spectrograms")),
    )

    a = raw["audio"]
    _clip      = int(a.get("clip_seconds",        15))
    _pre       = int(a.get("pre_capture_seconds",  0))
    _clip_mode = str(a.get("clip_mode", "full"))
    if _clip_mode not in ("window", "full"):
        raise ValueError(
            f"[audio] clip_mode must be 'window' or 'full', got: {_clip_mode!r}"
        )
    _pad = float(a.get("window_pad_seconds", 0.5))
    if not (0.0 <= _pad <= 10.0):
        raise ValueError(
            f"[audio] window_pad_seconds must be between 0.0 and 10.0, got: {_pad}"
        )

    # Two mutually-exclusive ways to define audio sources:
    #
    #   Legacy single-source:
    #       source = "sounddevice"   or   source = "rtsp"
    #
    #   Multi-source (each runs independently):
    #       [[audio.sources]]
    #       name = "garden-north"
    #       type = "sounddevice"
    #       device = 0
    #
    #       [[audio.sources]]
    #       name = "garden-south"
    #       type = "rtsp"
    #       ...
    #
    _sources_raw = a.get("sources")   # list[dict] when [[audio.sources]] is present
    _has_legacy  = "source" in a

    if _sources_raw is not None and _has_legacy:
        raise ValueError(
            "[audio] Cannot combine 'source = ...' and '[[audio.sources]]'. "
            "Remove the 'source = ...' line when using [[audio.sources]]."
        )

    if _sources_raw is not None:
        # Multi-source mode
        if not _sources_raw:
            raise ValueError(
                "[audio] [[audio.sources]] is empty — define at least one source block."
            )
        _audio_sources: list[AudioSourceConfig] = []
        for i, s in enumerate(_sources_raw):
            _src_type = str(s.get("type", "")).strip().lower()
            if _src_type not in ("sounddevice", "rtsp"):
                raise ValueError(
                    f"[audio.sources[{i}]] type must be 'sounddevice' or 'rtsp', "
                    f"got: {_src_type!r}"
                )
            _src_name = str(s.get("name", f"source-{i}"))
            if not re.match(r'^[A-Za-z0-9_\-]+$', _src_name):
                raise ValueError(
                    f"[audio.sources[{i}]] name {_src_name!r} contains invalid characters. "
                    "Use only letters, digits, hyphens, and underscores."
                )
            _audio_sources.append(AudioSourceConfig(
                name                    = _src_name,
                type                    = _src_type,
                device                  = s.get("device"),
                url                     = str(s.get("url",                     "")),
                transport               = str(s.get("transport",               "tcp")),
                reconnect_delay_seconds = int(s.get("reconnect_delay_seconds", 5)),
                ffmpeg_path             = str(s.get("ffmpeg_path",             "ffmpeg")),
            ))
        _sources_tuple: tuple[AudioSourceConfig, ...] | None = tuple(_audio_sources)
        _source = ""   # not used in multi-source mode
    else:
        # Legacy single-source mode
        _source = str(a.get("source", "sounddevice")).strip().lower()
        if _source not in ("sounddevice", "rtsp"):
            raise ValueError(
                f"[audio] source must be 'sounddevice' or 'rtsp', got: {_source!r}"
            )
        _sources_tuple = None

    _rtsp = a.get("rtsp", {})
    rtsp_cfg = AudioRtspConfig(
        url                     = str(_rtsp.get("url",                     "")),
        transport               = str(_rtsp.get("transport",               "tcp")),
        reconnect_delay_seconds = int(_rtsp.get("reconnect_delay_seconds", 5)),
        ffmpeg_path             = str(_rtsp.get("ffmpeg_path",             "ffmpeg")),
    )
    audio = AudioConfig(
        sample_rate            = int(a["sample_rate"]),
        hop_seconds            = int(a["hop_seconds"]),
        device                 = a.get("device"),  # None or int
        source                 = _source,
        rtsp                   = rtsp_cfg,
        clip_seconds           = _clip,
        pre_capture_seconds    = _pre,
        capture_buffer_seconds = int(a.get("capture_buffer_seconds", 30)),
        clip_mode              = _clip_mode,
        window_pad_seconds     = _pad,
        sources                = _sources_tuple,
    )

    d = raw["defaults"]
    defaults = SpeciesConfig(
        min_confidence              = float(d["min_confidence"]),
        cooldown_seconds            = int(d["cooldown_seconds"]),
        min_detections              = int(d.get("min_detections",              3)),
        confirmation_window_seconds = float(d.get("confirmation_window_seconds", 9.0)),
    )
    if defaults.min_detections < 1:
        raise ValueError(
            f"[defaults] min_detections must be >= 1, got {defaults.min_detections}"
        )
    exclude = frozenset(s.lower() for s in d.get("exclude", []))

    f = raw.get("filter", {})
    filter_cfg = FilterConfig(
        enabled   = bool(f.get("enabled",   False)),
        cutoff_hz = float(f.get("cutoff_hz", 150.0)),
        order     = int(f.get("order",       5)),
    )

    r = raw.get("retention", {})
    retention_cfg = RetentionConfig(
        enabled                  = bool(r.get("enabled",                  True)),
        max_age_days             = int(r.get("max_age_days",              30)),
        max_usage_percent        = float(r.get("max_usage_percent",       90.0)),
        min_clips_per_species    = int(r.get("min_clips_per_species",     5)),
        run_interval_seconds     = int(r.get("run_interval_seconds",      3600)),
        spectrogram_max_age_days = int(r.get("spectrogram_max_age_days",  365)),
    )

    log_raw = raw.get("log", {})
    log_cfg = LogConfig(
        enabled        = bool(log_raw.get("enabled",        False)),
        path           = Path(log_raw.get("path",           "data/bird_detector.log")),
        rotation       = str(log_raw.get("rotation",        "daily")),
        max_size_bytes = int(log_raw.get("max_size_bytes",  10 * 1024 * 1024)),
        backup_count   = int(log_raw.get("backup_count",    7)),
        level          = str(log_raw.get("level",           "INFO")).upper(),
    )

    db = raw.get("database", {})
    database_cfg = DatabaseConfig(
        type        = str(db.get("type",        "sqlite")),
        host        = str(db.get("host",        "localhost")),
        port        = int(db.get("port",        5432)),
        name        = str(db.get("name",        "birds")),
        username    = str(db.get("username",    "")),
        password    = str(db.get("password",    "")),
        timescaledb = bool(db.get("timescaledb", False)),
    )

    m = raw.get("mqtt", {})
    mqtt_cfg = MqttConfig(
        enabled  = bool(m.get("enabled",  False)),
        broker   = str(m.get("broker",   "localhost")),
        port     = int(m.get("port",     1883)),
        topic    = str(m.get("topic",    "birds/detections")),
        username = str(m.get("username", "")),
        password = str(m.get("password", "")),
        retain   = bool(m.get("retain",  False)),
    )

    bm = raw.get("birdmap", {})
    birdmap_cfg = BirdmapConfig(
        enabled      = bool(bm.get("enabled",      False)),
        api_url      = str(bm.get("api_url",       "https://api.birdmap.co.uk")),
        api_key      = str(bm.get("api_key",       "")),
        station_id   = int(bm.get("station_id",    0)),
        upload_audio = bool(bm.get("upload_audio", True)),
    )

    bw = raw.get("birdweather", {})
    birdweather_cfg = BirdweatherConfig(
        enabled      = bool(bw.get("enabled",      False)),
        token        = str(bw.get("token",         "")),
        upload_audio = bool(bw.get("upload_audio", True)),
    )

    sf = raw.get("seasonal_filter", {})
    seasonal_filter_cfg = SeasonalFilterConfig(
        enabled     = bool(sf.get("enabled",     False)),
        filter_json = Path(sf.get("filter_json", "uk_seasonal_filter.json")),
    )

    nf = raw.get("nocturnal_filter", {})
    nocturnal_filter_cfg = NocturnalFilterConfig(
        enabled     = bool(nf.get("enabled",     True)),
        filter_json = Path(nf.get("filter_json", "uk_nocturnal_filter.json")),
    )

    sf = raw.get("species_filter", {})
    species_filter_cfg = SpeciesFilterConfig(
        exclude_status = tuple(str(s) for s in sf.get("exclude_status", [])),
    )

    inf = raw.get("inference", {})
    inference_cfg = InferenceConfig(
        model = str(inf.get("model", "birdnet")),
    )

    cv = raw.get("cross_validation", {})
    _cv_on_disagree = str(cv.get("on_disagree", "drop"))
    if _cv_on_disagree not in ("drop", "flag", "save"):
        raise ValueError(
            f"[cross_validation] on_disagree must be 'drop', 'flag', or 'save', "
            f"got: {_cv_on_disagree!r}"
        )
    cross_validation_cfg = CrossValidationConfig(
        enabled           = bool(cv.get("enabled",           False)),
        skip_threshold    = float(cv.get("skip_threshold",    0.90)),
        on_disagree       = _cv_on_disagree,
        cv_min_confidence = float(cv.get("cv_min_confidence", 0.01)),
    )

    pf = raw.get("privacy_filter", {})
    privacy_filter_cfg = PrivacyFilterConfig(
        enabled             = bool(pf.get("enabled",             False)),
        threshold           = float(pf.get("threshold",           0.5)),
        min_voiced_fraction = float(pf.get("min_voiced_fraction", 0.10)),
    )

    _ded = raw.get("deduplication", {})
    _ded_on_dup = str(_ded.get("on_duplicate", "flag"))
    if _ded_on_dup not in ("flag", "skip"):
        raise ValueError(
            f"[deduplication] on_duplicate must be 'flag' or 'skip', "
            f"got: {_ded_on_dup!r}"
        )
    deduplication_cfg = DeduplicationConfig(
        enabled        = bool(_ded.get("enabled",        False)),
        window_seconds = int(_ded.get("window_seconds",  10)),
        on_duplicate   = _ded_on_dup,
    )

    adm = raw.get("admin", {})
    _session_secret = str(adm.get("session_secret", ""))
    if _session_secret and len(_session_secret) < 32:
        raise ValueError("admin.session_secret must be at least 32 characters")
    admin_cfg = AdminConfig(
        password_hash         = str(adm.get("password_hash",         "")),
        session_secret        = _session_secret,
        session_ttl           = int(adm.get("session_ttl",           86400)),
        auto_verify_threshold = float(adm.get("auto_verify_threshold", 0.9)),
    )

    w  = raw.get("weather", {})
    mb = w.get("pws_meteobridge", {})
    _default_mb_template = (
        "[th0temp-act];[th0hum-act];[wind0avgspd-act];"
        "[wind0dir-act];[msl0press-act];[rain0rate-act]"
    )
    tempest = w.get("pws_tempest", {})
    weather_cfg = WeatherConfig(
        enabled        = bool(w.get("enabled",       False)),
        provider       = str(w.get("provider",       "open_meteo")),
        api_key        = str(w.get("api_key",        "")),
        cache_seconds  = int(w.get("cache_seconds",  300)),
        pws_plugin     = str(w.get("pws_plugin",     "meteobridge")),
        pws_meteobridge = WeatherPwsMeteobridgeConfig(
            host            = str(mb.get("host",            "192.168.1.100")),
            port            = int(mb.get("port",            80)),
            username        = str(mb.get("username",        "meteobridge")),
            password        = str(mb.get("password",        "meteobridge")),
            template        = str(mb.get("template",        _default_mb_template)),
            wind_speed_unit = str(mb.get("wind_speed_unit", "ms")),
        ),
        pws_tempest = WeatherPwsTempestConfig(
            station_id = int(tempest.get("station_id", 0)),
            token      = str(tempest.get("token",      "")),
        ),
    )

    return Config(
        paths              = paths,
        audio              = audio,
        inference          = inference_cfg,
        cross_validation   = cross_validation_cfg,
        privacy_filter     = privacy_filter_cfg,
        deduplication      = deduplication_cfg,
        filter             = filter_cfg,
        retention          = retention_cfg,
        log                = log_cfg,
        database           = database_cfg,
        mqtt               = mqtt_cfg,
        birdmap            = birdmap_cfg,
        birdweather        = birdweather_cfg,
        seasonal_filter    = seasonal_filter_cfg,
        nocturnal_filter   = nocturnal_filter_cfg,
        species_filter     = species_filter_cfg,
        defaults           = defaults,
        general            = general_cfg,
        location           = location_cfg,
        weather            = weather_cfg,
        admin              = admin_cfg,
        exclude            = exclude,
        _species_overrides = raw.get("species", {}),
    )


# Loaded once at import time; all other modules import this directly.
cfg: Config = _load()


def get_species_config(species: str) -> SpeciesConfig:
    """Convenience wrapper around ``cfg.get_species_config``."""
    return cfg.get_species_config(species)
