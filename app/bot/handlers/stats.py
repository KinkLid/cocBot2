from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import account_keyboard, period_keyboard
from app.bot.states.period import PeriodSelectionStates
from app.container import AppContext
from app.repositories.telegram_user import TelegramUserRepository
from app.services.period import PeriodService
from app.services.stats import StatsService

router = Router(name="stats")


def _parse_date(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0)


@router.message(F.text == "📊 Моя статистика")
async def my_stats_entry(message: Message, app_context: AppContext, state: FSMContext) -> None:
    await state.clear()
    async with app_context.session_maker() as session:
        repo = TelegramUserRepository(session)
        user = await repo.get_by_telegram_id(message.from_user.id)
        if user is None:
            await message.answer("Сначала пройдите регистрацию через кнопку 📝 Регистрация")
            return
        links = await repo.get_links(user.id)

    if not links:
        await message.answer("У вас пока нет привязанных игровых аккаунтов")
        return
    if len(links) == 1:
        await state.update_data(selected_player_tag=links[0].player_tag)
        await message.answer("Выберите период", reply_markup=period_keyboard("my_stats_period"))
        return

    tags = [(link.player_tag, link.player_tag) for link in links]
    await message.answer("У вас несколько аккаунтов. Выберите нужный:", reply_markup=account_keyboard(tags, "my_stats_account"))


@router.callback_query(F.data.startswith("my_stats_account:"))
async def choose_my_stats_account(callback: CallbackQuery, state: FSMContext) -> None:
    player_tag = callback.data.split(":", 1)[1]
    await state.update_data(selected_player_tag=player_tag)
    await callback.message.edit_text("Выберите период", reply_markup=period_keyboard("my_stats_period"))
    await callback.answer()


@router.callback_query(F.data.startswith("my_stats_period:"))
async def choose_my_stats_period(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    mode = callback.data.split(":", 1)[1]
    if mode == "custom":
        await state.set_state(PeriodSelectionStates.waiting_for_custom_start)
        await callback.message.edit_text("Введите дату начала периода в формате YYYY-MM-DD")
        await callback.answer()
        return

    await _send_my_stats(callback.message, state, mode, app_context)
    await callback.answer()


async def _send_my_stats(message: Message, state: FSMContext, mode: str, app_context: AppContext) -> None:
    data = await state.get_data()
    player_tag = data["selected_player_tag"]
    async with app_context.session_maker() as session:
        period_service = PeriodService(session)
        if mode == "current":
            period = await period_service.current_cycle()
        else:
            period = await period_service.previous_cycle()
        stats = await StatsService(session, app_context.config).player_stats(period.start, period.end, player_tag)
        text = StatsService(session, app_context.config).format_player_card(stats, period.start.date().isoformat(), period.end.date().isoformat())
    await state.clear()
    await message.answer(text)


@router.message(PeriodSelectionStates.waiting_for_custom_start)
async def custom_period_start(message: Message, state: FSMContext) -> None:
    await state.update_data(custom_start=message.text.strip())
    await state.set_state(PeriodSelectionStates.waiting_for_custom_end)
    await message.answer("Введите дату конца периода в формате YYYY-MM-DD")


@router.message(PeriodSelectionStates.waiting_for_custom_end)
async def custom_period_end(message: Message, state: FSMContext, app_context: AppContext) -> None:
    data = await state.get_data()
    start = _parse_date(data["custom_start"])
    end = _parse_date(message.text.strip()).replace(hour=23, minute=59, second=59)
    async with app_context.session_maker() as session:
        period = PeriodService(session).custom_period(start, end)
        stats = await StatsService(session, app_context.config).player_stats(period.start, period.end, data["selected_player_tag"])
        text = StatsService(session, app_context.config).format_player_card(stats, period.start.date().isoformat(), period.end.date().isoformat())
    await state.clear()
    await message.answer(text)
