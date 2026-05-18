from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards.common import admin_sort_keyboard
from app.bot.keyboards.main import main_menu
from app.bot.states.capital import CapitalRaidStates
from app.bot.utils.telegram_text import edit_or_send_long_message, send_long_message
from app.bot.states.chat_link import ChatLinkStates
from app.container import AppContext
from app.services.clan_chat import ClanChatService
from app.services.capital_raid_report import CapitalRaidReportService
from app.services.dev_contribution import ContributionDataUnavailableError, DevContributionService
from app.services.donations import DonationService
from app.services.export import ExportService
from app.services.period import PeriodService
from app.services.registration import RegistrationService
from app.services.stats import StatsService

router = Router(name="admin")
logger = logging.getLogger(__name__)

CONTRIBUTION_BUILD_ERROR = "⚠️ Не удалось построить отчет по общему вкладу. Попробуйте позже."
CONTRIBUTION_CYCLE_DATA_ERROR = "⚠️ Общий вклад пока недоступен: в текущем цикле еще недостаточно данных."


def _ensure_admin(app_context: AppContext, telegram_id: int) -> None:
    if not app_context.auth_service.is_admin(telegram_id):
        raise PermissionError("Недостаточно прав")


@router.message(F.text == "👥 Список игроков")
async def admin_players(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    await message.answer("Выберите сортировку списка игроков", reply_markup=admin_sort_keyboard())


@router.callback_query(F.data.startswith("admin_sort:"))
async def admin_players_sort(callback: CallbackQuery, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, callback.from_user.id)
    except PermissionError:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    sort_by = callback.data.split(":", 1)[1]
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = StatsService(session, app_context.config)
        stats = await service.clan_stats(period.start, period.end, sort_by=sort_by)
        text = service.format_compact_players_by_stars(stats.rows) if sort_by == "stars" else (service.format_compact_players_by_place(stats.rows) if sort_by == "place" else service.format_compact_players_by_clan_order(stats.rows))
    await edit_or_send_long_message(callback.message, text or "Нет данных")
    await callback.answer()


@router.message(F.text == "📈 Статистика клана")
async def admin_clan_stats(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        stats = await StatsService(session, app_context.config).clan_stats(period.start, period.end)
    await send_long_message(message, stats.text or "Нет данных")


@router.message(F.text == "📦 Выгрузка JSON")
async def export_json(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = ExportService(session, app_context.config)
        path = await service.export_to_file(period.start, period.end, app_context.export_dir / "current_cycle_export.json")
    await message.answer_document(FSInputFile(path), caption="📦 JSON за текущий цикл")


@router.message(F.text == "🏆 Общий вклад")
async def dev_contribution(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            service = DevContributionService(session, app_context.config)
            ranking = await service.build_contribution_ranking(period)
            text = service.format_contribution_ranking(ranking)
        await send_long_message(message, text)
    except ContributionDataUnavailableError as exc:
        err = str(exc)
        if "в текущем цикле" in err or "недостаточно" in err:
            await message.answer(CONTRIBUTION_CYCLE_DATA_ERROR)
            return
        await message.answer(err or CONTRIBUTION_BUILD_ERROR)
    except (ValueError, TypeError):
        logger.exception("Failed to build dev contribution report due to malformed period/datetime data")
        await message.answer(CONTRIBUTION_CYCLE_DATA_ERROR)
    except Exception:
        logger.exception("Failed to build dev contribution report")
        await message.answer(CONTRIBUTION_BUILD_ERROR)


@router.message(F.text == "✏️ Обновить ссылку на чат")
async def update_chat_link_start(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    await state.set_state(ChatLinkStates.waiting_for_chat_link)
    await message.answer("Отправьте новую ссылку на чат клана")


@router.message(ChatLinkStates.waiting_for_chat_link)
async def update_chat_link_finish(message: Message, state: FSMContext, app_context: AppContext) -> None:
    async with app_context.session_maker() as session:
        url = await ClanChatService(session, app_context.config).update_chat_url(message.text.strip())
    await state.clear()
    await message.answer(f"✅ Ссылка обновлена:\n{url}")


@router.message(F.text == "📜 Последние логи")
async def last_logs(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    text = app_context.log_service.tail(200)
    await send_long_message(message, "📜 Последние 200 строк лога:\n" + text)


@router.message(F.text == "🗂 Скачать лог-файл")
async def download_log_file(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    path = app_context.log_service.file_path()
    if not path.exists():
        path.write_text("", encoding="utf-8")
    await message.answer_document(FSInputFile(path), caption="🗂 Полный лог-файл")


@router.message(F.text == "🧪 Dev-донаты")
async def dev_donations(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        service = DonationService(session, app_context.config)
        ranking = await service.build_current_cycle_donation_ranking()
        text = service.format_donation_ranking(ranking)
    await send_long_message(message, text)


@router.message(F.text == "🚨 Нарушения")
async def current_cycle_violations(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = StatsService(session, app_context.config)
        text = await service.violations_ranking_current_cycle(period.start, period.end)
    await send_long_message(message, text)


@router.message(F.text == "🏰 Столица")
async def capital_raid_report_start(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    await state.set_state(CapitalRaidStates.awaiting_capital_raid_count)
    await message.answer("🏰 Столица\nВведите, за сколько последних рейдов показать отчет.\nДопустимое число: от 1 до 10.")


@router.message(CapitalRaidStates.awaiting_capital_raid_count)
async def capital_raid_report_finish(message: Message, state: FSMContext, app_context: AppContext) -> None:
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        is_admin = app_context.auth_service.is_admin(message.from_user.id)
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(message.from_user.id)
        await message.answer("Главное меню", reply_markup=main_menu(is_admin, is_registered))
        return
    try:
        count = int(text)
    except ValueError:
        await message.answer("⚠️ Введите целое число от 1 до 10.")
        return
    if count < 1:
        await message.answer("⚠️ Число должно быть от 1 до 10.")
        return
    if count > 10:
        await message.answer("⚠️ Максимум можно запросить 10 последних рейдов.")
        return
    try:
        async with app_context.session_maker() as session:
            report = await CapitalRaidReportService(session, app_context.config).build_recent_weekends_report(count)
        await send_long_message(message, report)
    except Exception:
        logger.exception("Failed to build capital raid report")
        await message.answer("⚠️ Не удалось построить отчет по клановой столице. Попробуйте позже.")
    finally:
        await state.clear()
