"""Standalone script invoked by crond to run a scheduled agent message."""

import sys
import asyncio
import logging

from agent.config import cfg
from agent.db import init_db
from agent.loop import run_agent

logger = logging.getLogger(__name__)


async def main():
    message = sys.argv[1]
    logger.info("Cron started: %s", message)

    # Init
    init_db()

    # Import tools to trigger registration
    import agent.tools.exec  # noqa: F401
    import agent.tools.files  # noqa: F401
    import agent.tools.web  # noqa: F401

    # Run agent with cron=True (uses Prompt_Cron.md)
    response = await run_agent(chat_id=0, user_message=message, cron=True)

    # Send response to Telegram
    if cfg.telegram_allowed_chat_ids:
        import telegram
        bot = telegram.Bot(token=cfg.telegram_bot_token)
        async with bot:
            target = cfg.telegram_allowed_chat_ids[0]
            # Split if needed
            while response:
                chunk = response[:4096]
                response = response[4096:]
                await bot.send_message(chat_id=target, text=chunk)
            logger.info("Cron response sent to chat_id=%s", target)
    else:
        logger.warning("No allowed chat IDs configured, cron response not sent")


if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
