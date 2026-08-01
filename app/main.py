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
from app.services.startup_sync import StartupSyncService
from app.utils.logging import configure_logging
from app.security.audit import JsonlAudit, SecurityState
from app.security.monitor import SecurityAlerts, TelegramSecurityMonitor

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings()
    config = settings.load_yaml_config()
    configure_logging(settings.log_file, config.log_level)
    engine, session_maker = create_engine_and_sessionmaker(settings)
    app_context = build_context(settings, config, session_maker)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    audit = JsonlAudit(settings.security_audit_file, settings.bot_token)
    update_audit = JsonlAudit(settings.update_audit_file, settings.bot_token, max_bytes=20_000_000)
    security_state = SecurityState(settings.security_state_file)
    sentinel = None
    if settings.sentinel_bot_token:
        if settings.sentinel_bot_token == settings.bot_token:
            raise RuntimeError("Sentinel bot token must differ from primary bot token")
        sentinel = Bot(token=settings.sentinel_bot_token)
    sentinel_ids = [int(value) for value in settings.sentinel_admin_chat_ids.split(",") if value.strip()]
    alerts = SecurityAlerts(bot, audit, config.admin_telegram_ids, sentinel, sentinel_ids)
    security_monitor = TelegramSecurityMonitor(bot, config, audit, security_state, alerts)
    dp = create_dispatcher(app_context, update_audit, security_state)
    sender = lambda chat_id, text: send_text_via_bot(bot, chat_id, text)
    scheduler = create_scheduler(app_context, sender)

    try:
        # This gate runs before potentially long startup synchronization and polling.
        await security_monitor.check(startup=True)
        monitor_task = asyncio.create_task(security_monitor.run_forever(), name="telegram-security-monitor")
        startup_report = await StartupSyncService(app_context, sender).run()
        if not startup_report.clan_sync_ok:
            logger.warning("Bot starts without fully synced clan roster; player stats may be incomplete")
        scheduler.start()
        logger.info("Bot started")
        await dp.start_polling(bot)
    finally:
        if "monitor_task" in locals():
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
        scheduler.shutdown(wait=False)
        await app_context.clash_client.close()
        await engine.dispose()
        await bot.session.close()
        if sentinel is not None:
            await sentinel.session.close()


if __name__ == "__main__":
    asyncio.run(run())
