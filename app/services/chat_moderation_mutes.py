from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatModerationMute


class ChatModerationMuteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_mute(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        username: str | None,
        display_name: str | None,
        rule_id: str,
        muted_at: datetime,
        muted_until: datetime,
    ) -> ChatModerationMute:
        row = await self.session.scalar(
            select(ChatModerationMute).where(
                ChatModerationMute.chat_id == chat_id,
                ChatModerationMute.telegram_user_id == telegram_user_id,
            )
        )
        if row is None:
            row = ChatModerationMute(
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                username=username,
                display_name=display_name,
                rule_id=rule_id,
                muted_at=muted_at,
                muted_until=muted_until,
            )
            self.session.add(row)
        else:
            row.username = username
            row.display_name = display_name
            row.rule_id = rule_id
            row.muted_at = muted_at
            row.muted_until = muted_until
        await self.session.flush()
        return row

    async def active_mutes(self, *, chat_ids: list[int], now: datetime) -> list[ChatModerationMute]:
        if not chat_ids:
            return []
        rows = await self.session.scalars(
            select(ChatModerationMute)
            .where(
                ChatModerationMute.chat_id.in_(chat_ids),
                ChatModerationMute.muted_until > now,
            )
            .order_by(ChatModerationMute.muted_until.asc(), ChatModerationMute.id.asc())
        )
        return list(rows.all())

    async def get(self, mute_id: int) -> ChatModerationMute | None:
        return await self.session.get(ChatModerationMute, mute_id)

    async def remove(self, mute_id: int) -> bool:
        result = await self.session.execute(delete(ChatModerationMute).where(ChatModerationMute.id == mute_id))
        return bool(result.rowcount)

    async def remove_for_user(self, *, chat_id: int, telegram_user_id: int) -> bool:
        result = await self.session.execute(
            delete(ChatModerationMute).where(
                ChatModerationMute.chat_id == chat_id,
                ChatModerationMute.telegram_user_id == telegram_user_id,
            )
        )
        return bool(result.rowcount)
