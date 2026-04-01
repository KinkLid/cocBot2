from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.container import AppContext, send_text_via_bot
from app.services.clan_sync import ClanSyncService
from app.services.notifications import AdminNotifier
from app.services.war_sync import WarSyncService

logger = logging.getLogger(__name__)


async def sync_clan_members(app_context: AppContext, sender: Callable[[int, str], Awaitable[None]]) -> None:
    async with app_context.session_maker() as session:
        notifier = AdminNotifier(session, app_context.config, sender)
        await ClanSyncService(session, app_context.clash_client, app_context.config, notifier).sync_members()


async def sync_wars(app_context: AppContext, sender: Callable[[int, str], Awaitable[None]]) -> None:
    async with app_context.session_maker() as session:
        notifier = AdminNotifier(session, app_context.config, sender)
        await WarSyncService(session, app_context.clash_client, app_context.config, notifier).sync_all()


async def housekeeping(app_context: AppContext) -> None:
    logger.info("Housekeeping tick")


def create_scheduler(app_context: AppContext, sender: Callable[[int, str], Awaitable[None]]) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(sync_wars, "interval", seconds=app_context.config.polling.active_war_seconds, args=[app_context, sender], id="sync_wars", max_instances=1, coalesce=True)
    scheduler.add_job(sync_clan_members, "interval", seconds=app_context.config.polling.clan_members_seconds, args=[app_context, sender], id="sync_clan_members", max_instances=1, coalesce=True)
    scheduler.add_job(housekeeping, "interval", seconds=app_context.config.polling.housekeeping_seconds, args=[app_context], id="housekeeping", max_instances=1, coalesce=True)
    return scheduler
