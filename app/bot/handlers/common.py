from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.container import AppContext
from app.services.clan_chat import ClanChatService

router = Router(name="common")


@router.message(F.text == "🔗 Ссылка на чат клана")
async def clan_chat_link(message: Message, app_context: AppContext) -> None:
    async with app_context.session_maker() as session:
        url = await ClanChatService(session, app_context.config).get_chat_url()
    if url:
        await message.answer(f"🔗 Ссылка на чат клана:\n{url}")
    else:
        await message.answer("Ссылка на чат клана пока не настроена.")
