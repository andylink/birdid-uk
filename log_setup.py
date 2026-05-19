"""
Configures Python logging for the bird detector.

Call setup_logging() once at startup before any log messages are emitted.
All other modules should get their logger with:

    import logging
    logger = logging.getLogger(__name__)

A console (stdout) handler is always active. A rotating file handler is added
when enabled = true in the [log] section of config.toml.

Rotation modes (set via 'rotation' in config.toml):
    "daily" — rotate at midnight; keeps backup_count previous files.
    "size"  — rotate when the file exceeds max_size_bytes; keeps backup_count files.
"""

from __future__ import annotations

import logging
import logging.handlers

from config import cfg

# Console uses short timestamps; file uses full date-time for easier searching.
_CONSOLE_FMT = "%(asctime)s  %(message)s"
_FILE_FMT    = "%(asctime)s  %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"
_FILE_DATEFMT    = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """
    Set up the root logger with console and (optionally) file output.

    Safe to call more than once — does nothing if handlers are already set up,
    so both detector.main() and main.py can call it without duplicating output.

    Set level = "DEBUG" in [log] to see filter decisions during development.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    level = getattr(logging, cfg.log.level, logging.INFO)
    root.setLevel(level)

    # Console handler — always active
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(_CONSOLE_FMT, datefmt=_CONSOLE_DATEFMT)
    )
    console_handler.setLevel(level)
    root.addHandler(console_handler)

    # File handler — only added when enabled in config
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
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    # Silence noisy third-party libraries
    for noisy in (
        "birdnet_analyzer", "numba", "sounddevice", "tensorflow", "absl",
        "aiosqlite",    # otherwise logs every SQL call at DEBUG
        "sse_starlette",  # otherwise logs every SSE keep-alive ping
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
