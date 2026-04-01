from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards.common import admin_sort_keyboard
from app.bot.states.chat_link import ChatLinkStates
from app.container import AppContext
from app.services.clan_chat import ClanChatService
from app.services.dev_contribution import DevContributionService
from app.services.export import ExportService
from app.services.period import PeriodService
from app.services.stats import StatsService

router = Router(name="admin")


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
        stats = await StatsService(session, app_context.config).clan_stats(period.start, period.end, sort_by=sort_by)
    await callback.message.edit_text(stats.text or "Нет данных")
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
    await message.answer(stats.text or "Нет данных")


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


@router.message(F.text == "🧪 Dev-вклад")
async def dev_contribution(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        text = await DevContributionService(session, app_context.config).report(period.start, period.end)
    await message.answer(text)


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
    await message.answer(("📜 Последние 200 строк лога:\n" + text)[-3900:])


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
