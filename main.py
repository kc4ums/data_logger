"""
Data Logger — entry point.

Starts:
  1. APScheduler (AsyncIOScheduler) in an asyncio event loop for Modbus polling.
  2. Flask web server in a background daemon thread.
Graceful shutdown on SIGINT / KeyboardInterrupt.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading

from logger.config import load_config
from logger.database import init_db
from logger.poller import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def start_flask(port: int) -> None:
    from web.app import app
    log.info("Web dashboard  →  http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


async def async_main() -> None:
    config = load_config("config.yaml")

    # Initialise database (creates tables + seed PLC/tag rows)
    init_db(config)
    log.info("Database initialised.")

    # Flask in background thread
    flask_thread = threading.Thread(
        target=start_flask, args=(config.web_port,), daemon=True
    )
    flask_thread.start()

    # Build and start APScheduler
    scheduler, pollers = build_scheduler(config)
    scheduler.start()
    log.info(
        "Polling %d PLC(s) every %ds — press Ctrl+C to stop.",
        len(config.plcs),
        config.poll_interval_seconds,
    )

    stop_event = asyncio.Event()

    def _signal_handler(*_):
        stop_event.set()

    # Register SIGINT handler (works on Windows too via asyncio)
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
    except NotImplementedError:
        # Windows: fall back — KeyboardInterrupt will propagate naturally
        pass

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

    log.info("Shutting down…")
    scheduler.shutdown(wait=False)
    for p in pollers:
        await p.close()
    log.info("Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(0)
