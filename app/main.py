from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.app import create_dispatcher
from app.config.settings import Settings
from app.container import build_context, send_text_via_bot
from app.conversations import ConversationLogger, OutgoingConversationMiddleware
from app.db.session import create_engine_and_sessionmaker
from app.jobs.scheduler import create_scheduler
from app.security.audit import JsonlAudit, SecurityState
from app.security.monitor import SecurityAlerts
from app.security.resilient_monitor import ResilientTelegramSecurityMonitor
from app.services.startup_sync import StartupSyncService
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

# Kept as a module-level seam for startup tests and operator overrides.
TelegramSecurityMonitor = ResilientTelegramSecurityMonitor


async def _await_while_monitoring(
    awaitable: Awaitable[Any],
    monitor_task: asyncio.Task[None],
    *,
    task_name: str,
) -> Any:
    operation = asyncio.create_task(awaitable, name=task_name)
    try:
        done, _pending = await asyncio.wait(
            {monitor_task, operation},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if monitor_task in done:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
            await monitor_task
            raise RuntimeError("Telegram security monitor stopped unexpectedly")
        return await operation
    finally:
        if not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)


async def run() -> None:
    settings = Settings()
    config = settings.load_yaml_config()
    configure_logging(settings.log_file, config.log_level)
    engine, session_maker = create_engine_and_sessionmaker(settings)

    audit = JsonlAudit(settings.security_audit_file, settings.bot_token)
    app_context = build_context(settings, config, session_maker, security_audit=audit)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    update_audit = JsonlAudit(settings.update_audit_file, settings.bot_token, max_bytes=20_000_000)
    security_state = SecurityState(settings.security_state_file)
    conversation_logger: ConversationLogger | None = None
    if settings.conversation_log_enabled:
        conversation_logger = ConversationLogger(
            settings.conversation_log_dir,
            max_bytes=settings.conversation_log_max_bytes,
            backup_count=settings.conversation_log_backups,
        )
        bot.session.middleware(OutgoingConversationMiddleware(conversation_logger))
        logger.info("Conversation logging enabled: %s", conversation_logger.directory)

    sentinel = None
    if settings.sentinel_bot_token:
        if settings.sentinel_bot_token == settings.bot_token:
            raise RuntimeError("Sentinel bot token must differ from primary bot token")
        sentinel = Bot(token=settings.sentinel_bot_token)
    sentinel_ids = [int(value.strip()) for value in settings.sentinel_admin_chat_ids.split(",") if value.strip()]
    alerts = SecurityAlerts(bot, audit, config.admin_telegram_ids, sentinel, sentinel_ids, security_state)
    security_monitor = TelegramSecurityMonitor(bot, config, audit, security_state, alerts)
    dp = create_dispatcher(app_context, update_audit, security_state, conversation_logger)
    sender = lambda chat_id, text: send_text_via_bot(bot, chat_id, text)
    scheduler = create_scheduler(app_context, sender)
    scheduler_started = False
    monitor_task: asyncio.Task[None] | None = None

    try:
        await security_monitor.check(startup=True)
        monitor_task = asyncio.create_task(security_monitor.run_forever(), name="telegram-security-monitor")
        startup_report = await _await_while_monitoring(
            StartupSyncService(app_context, sender).run(),
            monitor_task,
            task_name="startup-sync",
        )
        if not startup_report.clan_sync_ok:
            logger.warning("Bot starts without fully synced clan roster; player stats may be incomplete")
        scheduler.start()
        scheduler_started = True
        logger.info("Bot started")
        await _await_while_monitoring(
            dp.start_polling(bot),
            monitor_task,
            task_name="telegram-polling",
        )
    finally:
        if monitor_task is not None and not monitor_task.done():
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
        if scheduler_started:
            scheduler.shutdown(wait=False)
        await app_context.clash_client.close()
        await engine.dispose()
        await bot.session.close()
        if sentinel is not None:
            await sentinel.session.close()


if __name__ == "__main__":
    asyncio.run(run())
