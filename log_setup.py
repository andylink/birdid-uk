"""
log_setup.py — configure Python logging for bird-detector.

Call ``setup_logging()`` once at the very start of ``detector.main()`` before
any log messages are emitted.  All other modules obtain their logger via::

    import logging
    logger = logging.getLogger(__name__)

Console behaviour is unchanged whether logging is enabled or not: a
StreamHandler is always attached so output continues to appear on stdout in the
same format as the previous ``print()`` calls.  When ``enabled = true`` in the
``[log]`` config section a rotating file handler is added alongside it.

Rotation modes (set via ``rotation`` in config.toml):
    ``"daily"`` — rotate at midnight; keeps ``backup_count`` previous files.
    ``"size"``  — rotate when the file exceeds ``max_size_bytes``; keeps
                  ``backup_count`` previous files.
"""

from __future__ import annotations

import logging
import logging.handlers

from config import cfg

# Shared format strings — kept consistent between both handlers so log files
# can be grepped without surprises.
_CONSOLE_FMT = "%(asctime)s  %(message)s"
_FILE_FMT    = "%(asctime)s  %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"
_FILE_DATEFMT    = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """
    Configure the root logger once.

    * A ``StreamHandler`` (stdout) is **always** added so console output is
      preserved identically to the old ``print()`` behaviour.
    * When ``cfg.log.enabled`` is ``True`` a rotating file handler is added.
    * Third-party loggers that are excessively chatty (``birdnet_analyzer``,
      ``sounddevice``) are capped at WARNING so they don't pollute the output.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # ── Console handler (always active) ───────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(_CONSOLE_FMT, datefmt=_CONSOLE_DATEFMT)
    )
    console_handler.setLevel(logging.INFO)
    root.addHandler(console_handler)

    # ── File handler (opt-in) ─────────────────────────────────────────────────
    lc = cfg.log
    if lc.enabled:
        lc.path.parent.mkdir(parents=True, exist_ok=True)

        if lc.rotation == "size":
            file_handler: logging.Handler = logging.handlers.RotatingFileHandler(
                lc.path,
                maxBytes=lc.max_size_bytes,
                backupCount=lc.backup_count,
                encoding="utf-8",
            )
        else:  # "daily" (default)
            file_handler = logging.handlers.TimedRotatingFileHandler(
                lc.path,
                when="midnight",
                backupCount=lc.backup_count,
                encoding="utf-8",
            )

        file_handler.setFormatter(
            logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT)
        )
        file_handler.setLevel(logging.INFO)
        root.addHandler(file_handler)

    # ── Suppress noisy third-party loggers ────────────────────────────────────
    for noisy in ("birdnet_analyzer", "numba", "sounddevice", "tensorflow", "absl"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
