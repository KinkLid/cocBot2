from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from app.bot.app import create_dispatcher
from app.config.settings import Settings
from app.container import build_context, send_text_via_bot
from app.db.session import create_engine_and_sessionmaker
from app.jobs.scheduler import create_scheduler
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings()
    config = settings.load_yaml_config()
    configure_logging(settings.log_file, config.log_level)
    engine, session_maker = create_engine_and_sessionmaker(settings)
    app_context = build_context(settings, config, session_maker)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher(app_context)
    scheduler = create_scheduler(app_context, lambda chat_id, text: send_text_via_bot(bot, chat_id, text))

    try:
        scheduler.start()
        logger.info("Bot started")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await app_context.clash_client.close()
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
