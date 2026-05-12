"""
main.py — unified single-process entrypoint for development and SBC deployments.

Runs the detector daemon and the FastAPI dashboard in a single Python process:

  * Detector: started as a daemon thread so it dies automatically if the main
    thread exits unexpectedly.
  * Dashboard: uvicorn runs on the main thread (its signal handlers work correctly
    on the main thread; running it on a worker thread would suppress Ctrl-C).

Shutdown sequence (Ctrl-C or SIGTERM):
  1. uvicorn catches the signal and returns from ``uvicorn.run()``.
  2. The ``finally`` block sets ``detector.stop_event`` (which signals the
     recording thread and classify loop to exit).
  3. We join the detector thread for up to 30 seconds, then exit.

For production deployments where crash isolation matters, use the two independent
systemd services in ``systemd/`` instead of this file.

Usage::

    python main.py [--host HOST] [--port PORT]

    python main.py                      # 0.0.0.0:8080
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
    # Configure logging once, before either component emits any messages.
    # Pass log_config=None to uvicorn.run() below so uvicorn's dictConfig
    # call doesn't clobber the file handler we set up here.
    setup_logging()

    args = _parse_args()

    logger.info(
        "Starting bird detector + dashboard (host=%s, port=%d)",
        args.host, args.port,
    )

    # Start the detector on a daemon thread so it does not prevent interpreter
    # exit if main() returns unexpectedly.
    t = threading.Thread(target=detector.main, name="detector", daemon=True)
    t.start()

    try:
        uvicorn.run(
            "dashboard.app:app",
            host=args.host,
            port=args.port,
            log_config=None,   # preserve our logging config; suppress uvicorn's dictConfig
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
