from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.container import AppContext
from app.services.clan_sync import ClanSyncService
from app.services.notifications import AdminNotifier
from app.services.war_sync import WarSyncService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StartupSyncReport:
    clan_sync_ok: bool
    war_sync_ok: bool
    members_processed: int


class StartupSyncService:
    def __init__(
        self,
        app_context: AppContext,
        sender: Callable[[int, str], Awaitable[None]],
        *,
        max_attempts: int = 3,
        base_backoff_seconds: float = 1.5,
    ) -> None:
        self.app_context = app_context
        self.sender = sender
        self.max_attempts = max(1, max_attempts)
        self.base_backoff_seconds = max(0.1, base_backoff_seconds)

    async def run(self) -> StartupSyncReport:
        clan_sync_ok = False
        members_processed = 0

        logger.info("Startup clan sync started")
        for attempt in range(1, self.max_attempts + 1):
            try:
                async with self.app_context.session_maker() as session:
                    notifier = AdminNotifier(session, self.app_context.config, self.sender)
                    members_processed = await ClanSyncService(
                        session,
                        self.app_context.clash_client,
                        self.app_context.config,
                        notifier,
                    ).sync_members()
                clan_sync_ok = True
                logger.info("Startup clan sync completed: %s members processed", members_processed)
                break
            except Exception as exc:
                logger.warning(
                    "Startup clan sync failed: attempt %s/%s (%s)",
                    attempt,
                    self.max_attempts,
                    exc,
                    exc_info=True,
                )
                if attempt < self.max_attempts:
                    delay = self.base_backoff_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

        if not clan_sync_ok:
            logger.error("Startup clan sync failed: exhausted retries")

        war_sync_ok = await self._run_optional_war_sync()
        return StartupSyncReport(clan_sync_ok=clan_sync_ok, war_sync_ok=war_sync_ok, members_processed=members_processed)

    async def _run_optional_war_sync(self) -> bool:
        logger.info("Startup war sync started")
        try:
            async with self.app_context.session_maker() as session:
                notifier = AdminNotifier(session, self.app_context.config, self.sender)
                await WarSyncService(
                    session,
                    self.app_context.clash_client,
                    self.app_context.config,
                    notifier,
                ).sync_all()
            logger.info("Startup war sync completed")
            return True
        except Exception as exc:
            logger.warning("Startup war sync failed: %s", exc, exc_info=True)
            return False
