"""
Runs the bird detector and web dashboard together in a single process.

The detector runs on a daemon thread; the dashboard (uvicorn) runs on the main
thread so that Ctrl-C is handled correctly. On shutdown, the detector is given
up to 30 seconds to stop cleanly before the process exits.

For crash-isolated deployments, use the separate systemd services in systemd/
instead of this file.

Usage:
    python main.py [--host HOST] [--port PORT]

    python main.py                       # 0.0.0.0:8080
    python main.py --host 127.0.0.1 --port 9000
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading

import uvicorn

import detector
from log_setup import setup_logging

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bird detector + dashboard unified process",
    )
    p.add_argument(
        "--host",
        default="0.0.0.0",
        help="Address for the dashboard to listen on (default: 0.0.0.0)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the dashboard to listen on (default: 8080)",
    )
    return p.parse_args()


def main() -> None:
    # Set up logging before anything else emits messages.
    # log_config=None below prevents uvicorn from overwriting this config.
    setup_logging()

    args = _parse_args()

    logger.info(
        "Starting bird detector + dashboard (host=%s, port=%d)",
        args.host, args.port,
    )

    # Daemon thread means it won't block the process from exiting if main() returns.
    t = threading.Thread(target=detector.main, name="detector", daemon=True)
    t.start()

    try:
        uvicorn.run(
            "dashboard.app:app",
            host=args.host,
            port=args.port,
            log_config=None,  # keep our logging config; don't let uvicorn replace it
        )
    finally:
        logger.info("Dashboard stopped — signalling detector to shut down …")
        detector.stop_event.set()
        t.join(timeout=30)
        if t.is_alive():
            logger.warning("Detector thread did not exit within 30 s — forcing exit")
            sys.exit(1)
        logger.info("Detector stopped cleanly.")


if __name__ == "__main__":
    main()
