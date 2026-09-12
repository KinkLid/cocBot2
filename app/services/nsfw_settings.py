from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nsfw_moderation_settings import NsfwModerationSettings


@dataclass(frozen=True, slots=True)
class NsfwRuntimeSettings:
    enabled: bool
    scan_interval_seconds: int


class NsfwSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        *,
        default_enabled: bool,
        default_scan_interval_seconds: int,
    ) -> NsfwModerationSettings:
        row = await self.session.scalar(select(NsfwModerationSettings).where(NsfwModerationSettings.id == 1))
        if row is not None:
            return row
        row = NsfwModerationSettings(
            id=1,
            enabled=default_enabled,
            scan_interval_seconds=default_scan_interval_seconds,
            updated_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self,
        *,
        enabled: bool | None = None,
        scan_interval_seconds: int | None = None,
        default_enabled: bool,
        default_scan_interval_seconds: int,
    ) -> NsfwModerationSettings:
        row = await self.get_or_create(
            default_enabled=default_enabled,
            default_scan_interval_seconds=default_scan_interval_seconds,
        )
        if enabled is not None:
            row.enabled = enabled
        if scan_interval_seconds is not None:
            row.scan_interval_seconds = scan_interval_seconds
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return row


def as_runtime(row: NsfwModerationSettings) -> NsfwRuntimeSettings:
    return NsfwRuntimeSettings(
        enabled=row.enabled,
        scan_interval_seconds=row.scan_interval_seconds,
    )
