"""
config.py — load config.toml and expose typed settings.

Usage::

    from config import cfg, get_species_config

    sc = get_species_config("European Robin")
    print(sc.min_confidence, sc.cooldown_seconds)
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Resolve config.toml relative to this file so the process can be launched
# from any working directory.
_CONFIG_PATH = Path(__file__).parent / "config.toml"


@dataclass(frozen=True)
class GeneralConfig:
    timezone: str


@dataclass(frozen=True)
class LocationConfig:
    lat: float  # WGS-84 decimal degrees (north positive)
    lon: float  # WGS-84 decimal degrees (east positive)


@dataclass(frozen=True)
class PathsConfig:
    detections_dir: Path
    db_path:        Path


@dataclass(frozen=True)
class AudioConfig:
    sample_rate:             int
    hop_seconds:             int
    window_seconds:          int
    device:                  int | None
    # Dual-buffer clip settings (see config.toml [audio] for documentation).
    clip_seconds:            int   # total saved clip length (>= window_seconds)
    pre_capture_seconds:     int   # extra audio before the analysis window
    capture_buffer_seconds:  int   # ring buffer capacity (> clip_seconds + margin)

    @property
    def post_capture_seconds(self) -> int:
        """Derived: how many seconds after the analysis window to include."""
        return self.clip_seconds - self.window_seconds - self.pre_capture_seconds


@dataclass(frozen=True)
class SpeciesConfig:
    """Merged defaults + any per-species overrides for a single species."""
    min_confidence:             float
    cooldown_seconds:           int
    top_n:                      int
    noise_labels:               frozenset[str]
    # Confirmation filter: a species must be detected at least min_detections
    # times within confirmation_window_seconds before a clip is saved.
    # Set min_detections = 1 to disable confirmation and save on the first hit.
    min_detections:             int
    confirmation_window_seconds: float


@dataclass(frozen=True)
class FilterConfig:
    enabled:   bool
    cutoff_hz: float
    order:     int


@dataclass(frozen=True)
class RetentionConfig:
    enabled:               bool
    max_age_days:          int
    max_usage_percent:     float
    min_clips_per_species: int
    run_interval_seconds:  int


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
    timescaledb: bool  # enable TimescaleDB hypertable init (postgresql only)


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
class BouFilterConfig:
    """Controls the BTO species allowlist filter.

    When *enabled* is ``True``, the detect loop discards any detection whose
    BirdNET common name could not be matched to a species in
    ``species_bto_FINAL_filtered.json``.
    """
    enabled: bool


@dataclass(frozen=True)
class SeasonalFilterConfig:
    """Controls the ISO-week-based seasonal presence filter.

    When *enabled* is ``True``, the detect loop drops any detection whose
    species has a seasonal restriction in *filter_json* and the current ISO
    8601 week (1–52) falls outside the allowed-weeks set.
    Species absent from the JSON are assumed year-round (no restriction).

    *filter_json* defaults to ``uk_seasonal_filter.json`` in the project
    root.  Copy and edit it, then point this key at the copy to customise.
    """
    enabled:     bool
    filter_json: Path


@dataclass(frozen=True)
class InferenceConfig:
    """Controls BirdNET inference behaviour.

    *label_locale* selects the common-name language used in BirdNET output and
    the labels file loaded by :func:`inference.load_label_map`.

    ``"en"`` (default) uses the bundled global English labels
    (``checkpoints/V2.4/BirdNET_GLOBAL_6K_V2.4_Labels.txt``).

    Any other value, e.g. ``"en_uk"``, loads the corresponding translated file
    from ``labels/V2.4/BirdNET_GLOBAL_6K_V2.4_Labels_{locale}.txt`` and passes
    ``locale`` to BirdNET's ``analyze()`` so inference results use the same
    common-name convention.
    """
    label_locale: str


@dataclass(frozen=True)
class Config:
    paths:           PathsConfig
    audio:           AudioConfig
    inference:       InferenceConfig
    filter:          FilterConfig
    retention:       RetentionConfig
    log:             LogConfig
    database:        DatabaseConfig
    mqtt:            MqttConfig
    birdmap:         BirdmapConfig
    bou_filter:      BouFilterConfig
    seasonal_filter: SeasonalFilterConfig
    defaults:        SpeciesConfig
    general:         GeneralConfig
    location:        LocationConfig
    exclude:         frozenset[str]   # species names to permanently suppress (case-insensitive)
    # raw per-species override dicts, keyed by species common name
    _species_overrides: dict[str, dict] = field(default_factory=dict, repr=False)

    def get_species_config(self, species: str) -> SpeciesConfig:
        """
        Return a SpeciesConfig for *species*, merging defaults with any
        per-species overrides defined in config.toml.

        Lookup is case-insensitive so minor capitalisation differences are
        handled gracefully.
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
            top_n                       = overrides.get("top_n",                       d.top_n),
            noise_labels                = frozenset(
                overrides.get("noise_labels", list(d.noise_labels))
            ),
            min_detections              = overrides.get("min_detections",              d.min_detections),
            confirmation_window_seconds = overrides.get("confirmation_window_seconds", d.confirmation_window_seconds),
        )


def _load() -> Config:
    with open(_CONFIG_PATH, "rb") as fh:
        raw = tomllib.load(fh)

    g = raw.get("general", {})
    general_cfg = GeneralConfig(
        timezone = str(g.get("timezone", "UTC")),
    )

    loc = raw.get("location", {})
    location_cfg = LocationConfig(
        lat = float(loc.get("lat", 0.0)),
        lon = float(loc.get("lon", 0.0)),
    )

    p = raw["paths"]
    paths = PathsConfig(
        detections_dir = Path(p["detections_dir"]),
        db_path        = Path(p["db_path"]),
    )

    a = raw["audio"]
    _window  = int(a["window_seconds"])
    _clip    = int(a.get("clip_seconds",           _window))  # default: clip == window (old behaviour)
    _pre     = int(a.get("pre_capture_seconds",    0))
    _post    = _clip - _window - _pre
    if _post < 0:
        raise ValueError(
            f"[audio] clip_seconds ({_clip}) must be >= "
            f"window_seconds ({_window}) + pre_capture_seconds ({_pre}); "
            f"got post_capture_seconds = {_post}"
        )
    audio = AudioConfig(
        sample_rate            = int(a["sample_rate"]),
        hop_seconds            = int(a["hop_seconds"]),
        window_seconds         = _window,
        device                 = a.get("device"),  # None or int
        clip_seconds           = _clip,
        pre_capture_seconds    = _pre,
        capture_buffer_seconds = int(a.get("capture_buffer_seconds", 30)),
    )

    d = raw["defaults"]
    defaults = SpeciesConfig(
        min_confidence              = float(d["min_confidence"]),
        cooldown_seconds            = int(d["cooldown_seconds"]),
        top_n                       = int(d["top_n"]),
        noise_labels                = frozenset(s.lower() for s in d["noise_labels"]),
        min_detections              = int(d.get("min_detections",              3)),
        confirmation_window_seconds = float(d.get("confirmation_window_seconds", 9.0)),
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
        enabled               = bool(r.get("enabled",               True)),
        max_age_days          = int(r.get("max_age_days",           30)),
        max_usage_percent     = float(r.get("max_usage_percent",    90.0)),
        min_clips_per_species = int(r.get("min_clips_per_species",  5)),
        run_interval_seconds  = int(r.get("run_interval_seconds",   3600)),
    )

    l = raw.get("log", {})
    log_cfg = LogConfig(
        enabled        = bool(l.get("enabled",        False)),
        path           = Path(l.get("path",           "data/bird_detector.log")),
        rotation       = str(l.get("rotation",        "daily")),
        max_size_bytes = int(l.get("max_size_bytes",  10 * 1024 * 1024)),
        backup_count   = int(l.get("backup_count",    7)),
        level          = str(l.get("level",           "INFO")).upper(),
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

    bf = raw.get("bou_filter", {})
    bou_filter_cfg = BouFilterConfig(
        enabled = bool(bf.get("enabled", False)),
    )

    sf = raw.get("seasonal_filter", {})
    seasonal_filter_cfg = SeasonalFilterConfig(
        enabled     = bool(sf.get("enabled",     False)),
        filter_json = Path(sf.get("filter_json", "uk_seasonal_filter.json")),
    )

    inf = raw.get("inference", {})
    inference_cfg = InferenceConfig(
        label_locale = str(inf.get("label_locale", "en")),
    )

    return Config(
        paths              = paths,
        audio              = audio,
        inference          = inference_cfg,
        filter             = filter_cfg,
        retention          = retention_cfg,
        log                = log_cfg,
        database           = database_cfg,
        mqtt               = mqtt_cfg,
        birdmap            = birdmap_cfg,
        bou_filter         = bou_filter_cfg,
        seasonal_filter    = seasonal_filter_cfg,
        defaults           = defaults,
        general            = general_cfg,
        location           = location_cfg,
        exclude            = exclude,
        _species_overrides = raw.get("species", {}),
    )


# Module-level singleton — imported by other modules as ``from config import cfg``
cfg: Config = _load()


def get_species_config(species: str) -> SpeciesConfig:
    """Convenience wrapper around ``cfg.get_species_config``."""
    return cfg.get_species_config(species)
