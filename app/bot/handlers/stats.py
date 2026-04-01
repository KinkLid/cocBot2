from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import account_keyboard, period_keyboard
from app.bot.states.period import PeriodSelectionStates
from app.bot.utils.telegram_text import send_long_message
from app.container import AppContext
from app.repositories.telegram_user import TelegramUserRepository
from app.services.period import PeriodService
from app.services.stats import StatsService

router = Router(name="stats")
logger = logging.getLogger(__name__)

GENERIC_STATS_ERROR = "⚠️ Не удалось показать статистику. Попробуйте позже."
CYCLE_DATA_ERROR = "⚠️ Не удалось построить статистику: недостаточно данных по циклам ЛВК."
PLAYER_DATA_ERROR = "⚠️ Не удалось построить статистику: игрок сейчас не состоит в клане или данные еще не синхронизированы."
BAD_DATE_FORMAT_ERROR = "⚠️ Неверный формат даты. Используйте YYYY-MM-DD."
BAD_DATE_ORDER_ERROR = "⚠️ Дата конца периода не может быть раньше даты начала."
NO_ACCOUNTS_ERROR = "У вас пока нет привязанных игровых аккаунтов"
REGISTER_FIRST_ERROR = "Сначала пройдите регистрацию через кнопку 📝 Регистрация"
CHOOSE_ACCOUNT_FIRST_ERROR = "⚠️ Сначала выберите игровой аккаунт для статистики."


def _parse_date(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0)


@router.message(F.text == "📊 Моя статистика")
async def my_stats_entry(message: Message, app_context: AppContext, state: FSMContext) -> None:
    await state.clear()
    try:
        async with app_context.session_maker() as session:
            repo = TelegramUserRepository(session)
            user = await repo.get_by_telegram_id(message.from_user.id)
            if user is None:
                await message.answer(REGISTER_FIRST_ERROR)
                return
            links = await repo.get_links(user.id)

        if not links:
            await message.answer(NO_ACCOUNTS_ERROR)
            return
        if len(links) == 1:
            await state.update_data(selected_player_tag=links[0].player_tag)
            await message.answer("Выберите период", reply_markup=period_keyboard("my_stats_period"))
            return

        tags = [(link.player_tag, link.player_tag) for link in links]
        await message.answer("У вас несколько аккаунтов. Выберите нужный:", reply_markup=account_keyboard(tags, "my_stats_account"))
    except Exception:
        logger.exception("Ошибка в обработчике кнопки 'Моя статистика' для telegram_id=%s", message.from_user.id)
        await state.clear()
        await message.answer(GENERIC_STATS_ERROR)


@router.callback_query(F.data.startswith("my_stats_account:"))
async def choose_my_stats_account(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        player_tag = callback.data.split(":", 1)[1]
        await state.update_data(selected_player_tag=player_tag)
        await callback.message.edit_text("Выберите период", reply_markup=period_keyboard("my_stats_period"))
        await callback.answer()
    except (AttributeError, IndexError):
        await state.clear()
        await callback.message.answer(CHOOSE_ACCOUNT_FIRST_ERROR)
        await callback.answer()
    except Exception:
        logger.exception("Ошибка при выборе аккаунта статистики telegram_id=%s", callback.from_user.id)
        await state.clear()
        await callback.message.answer(GENERIC_STATS_ERROR)
        await callback.answer()


@router.callback_query(F.data.startswith("my_stats_period:"))
async def choose_my_stats_period(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    try:
        mode = callback.data.split(":", 1)[1]
        data = await state.get_data()
        if not data.get("selected_player_tag"):
            await state.clear()
            await callback.message.answer(CHOOSE_ACCOUNT_FIRST_ERROR)
            await callback.answer()
            return

        if mode == "custom":
            await state.set_state(PeriodSelectionStates.waiting_for_custom_start)
            await callback.message.edit_text("Введите дату начала периода в формате YYYY-MM-DD")
            await callback.answer()
            return

        await _send_my_stats(callback.message, state, mode, app_context)
        await callback.answer()
    except (AttributeError, IndexError):
        await state.clear()
        await callback.message.answer(CHOOSE_ACCOUNT_FIRST_ERROR)
        await callback.answer()
    except Exception:
        logger.exception("Ошибка при выборе периода статистики telegram_id=%s", callback.from_user.id)
        await state.clear()
        await callback.message.answer(GENERIC_STATS_ERROR)
        await callback.answer()


async def _send_my_stats(message: Message, state: FSMContext, mode: str, app_context: AppContext) -> None:
    try:
        data = await state.get_data()
        player_tag = data.get("selected_player_tag")
        if not player_tag:
            await state.clear()
            await message.answer(CHOOSE_ACCOUNT_FIRST_ERROR)
            return

        async with app_context.session_maker() as session:
            period_service = PeriodService(session)
            if mode == "current":
                period = await period_service.current_cycle()
                if period.start == period.end:
                    raise ValueError("Недостаточно данных по ЛВК для текущего цикла")
            else:
                period = await period_service.previous_cycle()
            stats_service = StatsService(session, app_context.config)
            stats = await stats_service.player_stats(period.start, period.end, player_tag)
            text = stats_service.format_player_card(stats, period.start.date().isoformat(), period.end.date().isoformat())
        await state.clear()
        await send_long_message(message, text)
    except ValueError as exc:
        await state.clear()
        if "Недостаточно данных" in str(exc):
            await message.answer(CYCLE_DATA_ERROR)
            return
        if "Дата конца периода меньше даты начала" in str(exc):
            await message.answer(BAD_DATE_ORDER_ERROR)
            return
        if "Игрок сейчас не состоит в клане" in str(exc):
            await message.answer(PLAYER_DATA_ERROR)
            return
        logger.exception("Необработанный ValueError при показе статистики")
        await message.answer(GENERIC_STATS_ERROR)
    except Exception:
        logger.exception("Неожиданная ошибка при показе статистики")
        await state.clear()
        await message.answer(GENERIC_STATS_ERROR)


@router.message(PeriodSelectionStates.waiting_for_custom_start)
async def custom_period_start(message: Message, state: FSMContext) -> None:
    try:
        start_raw = (message.text or "").strip()
        _parse_date(start_raw)
    except ValueError:
        await message.answer(BAD_DATE_FORMAT_ERROR)
        return
    await state.update_data(custom_start=start_raw)
    await state.set_state(PeriodSelectionStates.waiting_for_custom_end)
    await message.answer("Введите дату конца периода в формате YYYY-MM-DD")


@router.message(PeriodSelectionStates.waiting_for_custom_end)
async def custom_period_end(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        data = await state.get_data()
        custom_start = data.get("custom_start")
        player_tag = data.get("selected_player_tag")
        if not custom_start or not player_tag:
            await state.clear()
            await message.answer(CHOOSE_ACCOUNT_FIRST_ERROR)
            return

        start = _parse_date(custom_start)
        end = _parse_date((message.text or "").strip()).replace(hour=23, minute=59, second=59)

        async with app_context.session_maker() as session:
            period = PeriodService(session).custom_period(start, end)
            stats_service = StatsService(session, app_context.config)
            stats = await stats_service.player_stats(period.start, period.end, player_tag)
            text = stats_service.format_player_card(stats, period.start.date().isoformat(), period.end.date().isoformat())

        await state.clear()
        await send_long_message(message, text)
    except ValueError as exc:
        if "does not match format" in str(exc):
            await message.answer(BAD_DATE_FORMAT_ERROR)
            return
        await state.clear()
        if "Дата конца периода меньше даты начала" in str(exc):
            await message.answer(BAD_DATE_ORDER_ERROR)
            return
        if "Игрок сейчас не состоит в клане" in str(exc):
            await message.answer(PLAYER_DATA_ERROR)
            return
        logger.exception("Необработанный ValueError при пользовательском периоде")
        await message.answer(GENERIC_STATS_ERROR)
    except Exception:
        logger.exception("Неожиданная ошибка при пользовательском периоде")
        await state.clear()
        await message.answer(GENERIC_STATS_ERROR)
