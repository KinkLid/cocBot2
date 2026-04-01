from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.keyboards.main import main_menu
from app.container import AppContext

router = Router(name="start")


@router.message(CommandStart())
async def command_start(message: Message, app_context: AppContext) -> None:
    is_admin = app_context.auth_service.is_admin(message.from_user.id)
    await message.answer(
        "Добро пожаловать в бот мониторинга клана Clash of Clans 👋\nВыберите действие кнопками ниже.",
        reply_markup=main_menu(is_admin),
    )
