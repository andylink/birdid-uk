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
    timezone:     str
    station_name: str  # display name for the dashboard header; empty = default "BirdNet-UK"


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
    device:                  int | None
    # Dual-buffer clip settings (see config.toml [audio] for documentation).
    clip_seconds:            int   # total saved clip length — only used when clip_mode="full"
    pre_capture_seconds:     int   # extra audio before the analysis window (clip_mode="full" only)
    capture_buffer_seconds:  int   # ring buffer capacity (must exceed the longest clip + margin)
    # Clip mode: "window" saves the model analysis window plus window_pad_seconds of
    # leading audio.  "full" uses the legacy clip_seconds / pre_capture_seconds geometry.
    clip_mode:               str   # "window" | "full"
    window_pad_seconds:      float # seconds of leading audio before the window (clip_mode="window")
    # post_capture_seconds is NOT stored here — it depends on the active model's
    # window length, which is not known at config-load time.  Computed in
    # detector.main() once the model is selected.


@dataclass(frozen=True)
class SpeciesConfig:
    """Merged defaults + any per-species overrides for a single species."""
    min_confidence:              float
    cooldown_seconds:            int
    # Confirmation filter: species must be detected min_detections times within
    # confirmation_window_seconds before a clip is saved.  min_detections = 1
    # disables confirmation and saves on the first hit.
    min_detections:              int
    confirmation_window_seconds: float
    # Cross-validation override: None falls back to [cross_validation] on_disagree.
    # Set to "flag" for rare/nocturnal species to review disagreements rather
    # than silently dropping them.
    on_disagree:                 str | None = None


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
class NocturnalFilterConfig:
    """Controls the time-of-day filter for nocturnal and crepuscular species.

    When *enabled* is ``True``, the detect loop drops detections of listed
    species that occur outside their defined active window (i.e. in the middle
    of the day).

    Two window types are supported (see ``nocturnal_filter.py`` for details):

    * ``sunset_sunrise`` — window relative to today's sunrise/sunset, computed
      from [location] lat/lon.  Supports per-event offsets in minutes.
    * ``fixed`` — fixed local clock-time range (HH:MM strings), spanning
      midnight if start > end.

    Per-species overrides can be set in ``[species."Name"]`` blocks using the
    ``active_hours`` key (takes priority over the JSON data file).

    *filter_json* defaults to ``uk_nocturnal_filter.json``.
    """
    enabled:     bool
    filter_json: Path


@dataclass(frozen=True)
class SpeciesFilterConfig:
    """Controls status-based exclusion from the BOU allowlist.

    *exclude_status* is a list of status tokens to exclude.  Each species'
    ``british_list_status`` field is split on commas and the resulting tokens
    are compared case-insensitively against this list.  Any species whose status
    contains a listed token is dropped from the allowlist before matching.

    Examples::

        exclude_status = ["Accidental"]           # suppress extreme vagrants
        exclude_status = ["Accidental", "Escaped"] # also suppress escaped species

    Leave empty (default) to accept all BTO-listed species.
    """
    exclude_status: tuple[str, ...]   # stored as tuple for hashability


@dataclass(frozen=True)
class InferenceConfig:
    """Controls inference backend selection.

    *model* selects the active classifier:

    ``"birdnet"`` (default) uses the bundled BirdNET GLOBAL 6K V2.4 model
    shipped with *birdnet-analyzer*.  No extra dependencies required.
    BirdNET always runs with its standard global English / IOC labels; name
    translation to BTO British names is handled by ``species_filter``.

    ``"perch"`` uses Google Perch v2, a TensorFlow-based model downloaded
    from Kaggle on first run (~400 MB).  Requires ``perch-hoplite[tf]`` and
    Kaggle credentials; see requirements.txt for installation notes.
    """
    model: str   # "birdnet" | "perch"


@dataclass(frozen=True)
class CrossValidationConfig:
    """Controls dual-model cross-validation of confirmed detections.

    When *enabled* is ``True``, every detection confirmed by the primary model
    is re-evaluated by the secondary model (whichever of BirdNET / Perch is
    *not* the primary).  The two models' top species are compared via their
    BTO-resolved names; a match is counted as agreement.

    *skip_threshold*: if the primary model's best confirmation confidence is
    at or above this value, cross-validation is skipped and the detection is
    saved unconditionally.  Use this to avoid the overhead of running the
    secondary model when the primary is already highly confident.

    *on_disagree*: global action when the two models identify different species:

    * ``"drop"``  — silently discard the detection (maximises precision; default)
    * ``"flag"``  — save with ``flagged = True`` for manual review

    Per-species overrides are supported by adding ``on_disagree = "flag"``
    inside a ``[species."<name>"]`` block in config.toml.

    When models agree, ``detections.confidence`` is set to the arithmetic mean
    of both scores.  When CV is skipped (high-confidence shortcut), the primary
    score is used unchanged.  The raw primary score is always stored in
    ``detections.primary_confidence`` for auditability.
    """
    enabled:           bool
    skip_threshold:    float   # primary best_confidence >= this → skip CV
    on_disagree:       str     # "drop" | "flag"
    cv_min_confidence: float   # minimum secondary-model score to count as a candidate
                               # BirdNET scores are in [0, 1]; Perch softmax probs over
                               # ~10 k classes are much lower — keep this at ≈ 0.01 (the
                               # raw inference floor) so Perch candidates aren't filtered out


@dataclass(frozen=True)
class Config:
    paths:            PathsConfig
    audio:            AudioConfig
    inference:        InferenceConfig
    cross_validation: CrossValidationConfig
    filter:           FilterConfig
    retention:        RetentionConfig
    log:              LogConfig
    database:         DatabaseConfig
    mqtt:             MqttConfig
    birdmap:          BirdmapConfig
    seasonal_filter:  SeasonalFilterConfig
    nocturnal_filter: NocturnalFilterConfig
    species_filter:   SpeciesFilterConfig
    defaults:         SpeciesConfig
    general:          GeneralConfig
    location:         LocationConfig
    exclude:          frozenset[str]   # species names to permanently suppress (case-insensitive)
    # raw per-species override dicts, keyed by species common name
    _species_overrides: dict[str, dict] = field(default_factory=dict, repr=False)

    def bou_override_species(self) -> frozenset[str]:
        """Return the names of species with ``species_status_override = true``.

        These names are passed to :func:`species_filter.build_bou_allowed_set` and
        :func:`species_filter.build_birdnet_to_bto_map` as ``force_include`` so that
        the species are admitted even when their BOU status would normally be
        excluded by ``[species_filter] exclude_status``.

        The returned names are the keys from ``[species."Name"]`` blocks in
        ``config.toml`` and should match the BirdNET common name shown in the
        terminal (or the BTO British name — both are tried during matching).
        """
        return frozenset(
            name
            for name, overrides in self._species_overrides.items()
            if overrides.get("species_status_override", False)
        )

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

    p = raw["paths"]
    paths = PathsConfig(
        detections_dir = Path(p["detections_dir"]),
        db_path        = Path(p["db_path"]),
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
    audio = AudioConfig(
        sample_rate            = int(a["sample_rate"]),
        hop_seconds            = int(a["hop_seconds"]),
        device                 = a.get("device"),  # None or int
        clip_seconds           = _clip,
        pre_capture_seconds    = _pre,
        capture_buffer_seconds = int(a.get("capture_buffer_seconds", 30)),
        clip_mode              = _clip_mode,
        window_pad_seconds     = _pad,
    )

    d = raw["defaults"]
    defaults = SpeciesConfig(
        min_confidence              = float(d["min_confidence"]),
        cooldown_seconds            = int(d["cooldown_seconds"]),
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
    cross_validation_cfg = CrossValidationConfig(
        enabled           = bool(cv.get("enabled",           False)),
        skip_threshold    = float(cv.get("skip_threshold",    0.90)),
        on_disagree       = str(cv.get("on_disagree",        "drop")),
        cv_min_confidence = float(cv.get("cv_min_confidence", 0.01)),
    )

    return Config(
        paths              = paths,
        audio              = audio,
        inference          = inference_cfg,
        cross_validation   = cross_validation_cfg,
        filter             = filter_cfg,
        retention          = retention_cfg,
        log                = log_cfg,
        database           = database_cfg,
        mqtt               = mqtt_cfg,
        birdmap            = birdmap_cfg,
        seasonal_filter    = seasonal_filter_cfg,
        nocturnal_filter   = nocturnal_filter_cfg,
        species_filter     = species_filter_cfg,
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
