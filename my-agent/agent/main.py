"""Entrypoint: init DB, start Telegram bot + web server in a single event loop."""

import asyncio
import signal
import logging

from agent.config import cfg
from agent.db import init_db, close as close_db
from agent.telegram import start_bot
from agent.server import start_server


logger = logging.getLogger(__name__)


def main():
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Init database
    init_db()

    # Import tools to trigger registration
    import agent.tools.exec  # noqa: F401
    import agent.tools.files  # noqa: F401
    if cfg.brave_api_key:
        import agent.tools.web  # noqa: F401
    else:
        # Still register web_fetch even without Brave key
        import agent.tools.web  # noqa: F401

    logger.info("Tools registered, starting services...")

    # Run everything
    asyncio.run(run_all())


async def run_all():
    loop = asyncio.get_event_loop()

    # Graceful shutdown handler
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    # Start Telegram bot
    app = start_bot()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Telegram bot started (polling)")

    # Start web server
    server_task = asyncio.create_task(start_server())
    logger.info("Web dashboard started on port %s", cfg.ingress_port)

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Cleanup
    logger.info("Shutting down...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    server_task.cancel()
    close_db()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
