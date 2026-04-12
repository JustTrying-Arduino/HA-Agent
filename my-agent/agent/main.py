"""Entrypoint: init DB, start Telegram bot + web server in a single event loop."""

import asyncio
import signal
import logging

from agent.config import cfg
from agent.db import init_db, close as close_db
from agent.scheduler import run_scheduler
from agent.telegram import start_bot
from agent.server import start_server


logger = logging.getLogger(__name__)


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Keep addon logs visible while silencing noisy library request logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)


def main():
    # Configure logging
    configure_logging()

    # Init database
    init_db()

    logger.info("SUPERVISOR_TOKEN present: %s", bool(cfg.supervisor_token))

    # Import tools to trigger registration
    import agent.tools.exec  # noqa: F401
    import agent.tools.files  # noqa: F401
    import agent.tools.reminders  # noqa: F401
    import agent.tools.router  # noqa: F401
    if cfg.brave_api_key:
        import agent.tools.web  # noqa: F401
    else:
        # Still register web_fetch even without Brave key
        import agent.tools.web  # noqa: F401
    if cfg.supervisor_token:
        import agent.tools.homeassistant  # noqa: F401

    from agent.tools import TOOLS
    logger.info("Tools registered (%d): %s", len(TOOLS), ", ".join(sorted(TOOLS.keys())))

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

    scheduler_task = asyncio.create_task(run_scheduler(app.bot))
    logger.info("Reminder scheduler started")

    # Start web server
    server_task = asyncio.create_task(start_server())
    logger.info("Web dashboard started on port %s", cfg.ingress_port)

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Cleanup
    logger.info("Shutting down...")
    scheduler_task.cancel()
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    server_task.cancel()
    await asyncio.gather(scheduler_task, server_task, return_exceptions=True)
    if cfg.supervisor_token:
        from agent import ha_client

        await ha_client.close()
    close_db()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
