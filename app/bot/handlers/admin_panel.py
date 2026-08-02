from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.bot.keyboards.admin_panel import (
    REPORT_LABELS,
    admin_panel_keyboard,
    amount_keyboard,
    capital_keyboard,
    confirm_keyboard,
    contribution_keyboard,
    cycles_keyboard,
    entities_keyboard,
    period_keyboard,
    players_keyboard,
    reports_keyboard,
    security_keyboard,
    selectable_players_keyboard,
    system_keyboard,
    violations_keyboard,
    war_keyboard,
)
from app.bot.keyboards.common import (
    admin_player_link_keyboard,
    admin_sort_keyboard,
    violation_recalculation_confirm_keyboard,
)
from app.bot.keyboards.main import back_keyboard
from app.bot.states.admin_panel import AdminPanelStates
from app.bot.states.admin_player_link import AdminPlayerLinkStates
from app.bot.states.chat_link import ChatLinkStates
from app.bot.states.manual_violation import ManualViolationStates
from app.bot.states.violations import ViolationStates
from app.bot.utils.telegram_text import edit_or_send_long_message, send_long_message
from app.container import AppContext
from app.domain.period import PeriodRange
from app.models import ManualContributionAdjustment, PlayerAccount, TelegramPlayerLink, Violation, ViolationCounterReset
from app.repositories.manual_contribution import ManualContributionRepository
from app.repositories.telegram_user import TelegramUserRepository
from app.services.admin_player_link import AdminPlayerLinkService
from app.services.capital_raid_contribution import CapitalRaidContributionService
from app.services.capital_raid_report import CapitalRaidStatsService
from app.services.clan_chat import ClanChatService
from app.services.contribution_breakdown import ContributionBreakdownService
from app.services.dev_contribution import ContributionDataUnavailableError, DevContributionService
from app.services.donations import DonationRankingRow, DonationService
from app.services.export import ExportService
from app.services.manual_violation import ManualViolationService
from app.services.period import PeriodService
from app.services.stats import StatsService
from app.utils.time import utcnow

router = Router(name="admin_panel")
logger = logging.getLogger(__name__)

_SECTION_TEXT = {
    "root": "🛡 <b>Админ-панель</b>\n\nВыберите раздел.",
    "war": "⚔️ <b>Война</b>\n\nТекущая война, оставшиеся атаки и синхронизация.",
    "players": "👥 <b>Игроки</b>\n\nСостав клана и привязки Telegram.",
    "violations": "🚨 <b>Нарушения</b>\n\nОтчёты, ручные нарушения и активный счётчик.",
    "contribution": "🏆 <b>Вклад</b>\n\nРейтинги, подробности и ручные корректировки.",
    "capital": "🏰 <b>Столица</b>\n\nСтатистика рейдов и вклад игроков.",
    "reports": "📊 <b>Отчёты</b>\n\nСтатистика клана и выгрузки.",
    "system": "⚙️ <b>Система</b>\n\nСостояние, журналы и настройки.",
    "security": "🔐 <b>Безопасность</b>\n\nСостояние защитного контура Telegram.",
}

_SECTION_KEYBOARDS = {
    "root": admin_panel_keyboard,
    "war": war_keyboard,
    "players": players_keyboard,
    "violations": violations_keyboard,
    "contribution": contribution_keyboard,
    "capital": capital_keyboard,
    "reports": reports_keyboard,
    "system": system_keyboard,
    "security": security_keyboard,
}


def _ensure_admin(app_context: AppContext, telegram_id: int) -> bool:
    return app_context.auth_service.is_admin(telegram_id)


async def _deny_callback(callback: CallbackQuery) -> None:
    await callback.answer("Недостаточно прав", show_alert=True)


async def _edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await callback.message.answer(text, reply_markup=reply_markup)


def _serialize_period(period: PeriodRange) -> dict[str, str]:
    return {"start": period.start.isoformat(), "end": period.end.isoformat(), "label": period.label}


def _deserialize_period(value: dict[str, str]) -> PeriodRange:
    return PeriodRange(
        start=datetime.fromisoformat(value["start"]),
        end=datetime.fromisoformat(value["end"]),
        label=value["label"],
    )


def _is_historical(period: PeriodRange) -> bool:
    return period.label != "Текущий цикл"


@router.message(F.text == "🛡 Админка")
async def open_admin_panel(message: Message, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, message.from_user.id):
        await message.answer("⛔ Недостаточно прав")
        return
    await state.clear()
    await message.answer(_SECTION_TEXT["root"], reply_markup=admin_panel_keyboard())


@router.callback_query(F.data.startswith("admin_panel:"))
async def navigate_admin_panel(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    section = (callback.data or "").split(":", 1)[1]
    if section == "close":
        await state.clear()
        await callback.message.delete()
        await callback.answer()
        return
    if section not in _SECTION_KEYBOARDS:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await state.clear()
    await _edit(callback, _SECTION_TEXT[section], _SECTION_KEYBOARDS[section]())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report:"))
async def choose_report_period(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    report = (callback.data or "").split(":", 1)[1]
    if report not in REPORT_LABELS:
        await callback.answer("Отчёт не найден", show_alert=True)
        return
    await state.clear()
    await _edit(
        callback,
        f"{REPORT_LABELS[report]}\n\nВыберите период:",
        period_keyboard(report),
    )
    await callback.answer()


async def _resolve_period(session, mode: str) -> PeriodRange:
    service = PeriodService(session)
    if mode == "current":
        return await service.current_cycle()
    if mode == "previous":
        return await service.previous_cycle()
    if mode == "all":
        return service.all_time()
    raise ValueError("Неизвестный период")


@router.callback_query(F.data.startswith("admin_period:"))
async def report_period_selected(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректный период", show_alert=True)
        return
    _, report, mode = parts
    if mode == "cycles":
        async with app_context.session_maker() as session:
            cycles = await PeriodService(session).completed_cycles()
        if not cycles:
            await callback.answer("В базе нет завершённых циклов", show_alert=True)
            return
        await state.update_data(admin_cycles=[_serialize_period(period) for period in cycles])
        await _edit(callback, f"{REPORT_LABELS[report]}\n\nВыберите цикл:", cycles_keyboard(report, cycles))
        await callback.answer()
        return
    if mode == "custom":
        await state.update_data(admin_report=report)
        await state.set_state(AdminPanelStates.waiting_custom_period_start)
        await callback.message.answer(
            "Введите дату начала периода в формате ДД.ММ.ГГГГ.",
            reply_markup=back_keyboard(),
        )
        await callback.answer()
        return
    try:
        async with app_context.session_maker() as session:
            period = await _resolve_period(session, mode)
        await _run_report(callback.message, app_context, report, period, state=state)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cycles:"))
async def cycle_page(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    _, report, raw_page = (callback.data or "").split(":")
    data = await state.get_data()
    cycles = [_deserialize_period(item) for item in data.get("admin_cycles", [])]
    page = max(0, int(raw_page))
    await _edit(callback, f"{REPORT_LABELS[report]}\n\nВыберите цикл:", cycles_keyboard(report, cycles, page))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cycle:"))
async def cycle_selected(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    _, report, raw_index = (callback.data or "").split(":")
    data = await state.get_data()
    cycles = data.get("admin_cycles", [])
    index = int(raw_index)
    if index < 0 or index >= len(cycles):
        await callback.answer("Цикл больше недоступен", show_alert=True)
        return
    await _run_report(callback.message, app_context, report, _deserialize_period(cycles[index]), state=state)
    await callback.answer()


def _parse_date(text: str) -> datetime:
    parsed = datetime.strptime(text.strip(), "%d.%m.%Y").date()
    return datetime.combine(parsed, time.min, tzinfo=UTC)


@router.message(AdminPanelStates.waiting_custom_period_start)
async def custom_period_start(message: Message, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Недостаточно прав")
        return
    if (message.text or "").strip() == "⬅️ Назад":
        data = await state.get_data()
        report = data.get("admin_report", "clan_stats")
        await state.clear()
        await message.answer(f"{REPORT_LABELS[report]}\n\nВыберите период:", reply_markup=period_keyboard(report))
        return
    try:
        start = _parse_date(message.text or "")
    except ValueError:
        await message.answer("⚠️ Нужна дата в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(admin_custom_start=start.isoformat())
    await state.set_state(AdminPanelStates.waiting_custom_period_end)
    await message.answer("Введите дату окончания периода в формате ДД.ММ.ГГГГ.", reply_markup=back_keyboard())


@router.message(AdminPanelStates.waiting_custom_period_end)
async def custom_period_end(message: Message, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Недостаточно прав")
        return
    data = await state.get_data()
    if (message.text or "").strip() == "⬅️ Назад":
        await state.set_state(AdminPanelStates.waiting_custom_period_start)
        await message.answer("Введите дату начала периода в формате ДД.ММ.ГГГГ.", reply_markup=back_keyboard())
        return
    try:
        end_day = _parse_date(message.text or "")
        start = datetime.fromisoformat(data["admin_custom_start"])
        end = end_day + timedelta(days=1) - timedelta(microseconds=1)
        period = PeriodService(None).custom_period(start, end)
    except (ValueError, KeyError):
        await message.answer("⚠️ Проверьте дату и убедитесь, что окончание не раньше начала.")
        return
    report = data.get("admin_report", "clan_stats")
    await state.clear()
    await _run_report(message, app_context, report, period, state=state)


async def _run_report(message: Message, app_context: AppContext, report: str, period: PeriodRange, *, state: FSMContext) -> None:
    try:
        async with app_context.session_maker() as session:
            if report == "clan_stats":
                result = await StatsService(session, app_context.config).clan_stats(period.start, period.end)
                text = f"📈 Статистика клана\nПериод: {period.label}\n\n{result.text or 'Нет данных'}"
            elif report == "contribution":
                service = DevContributionService(session, app_context.config)
                ranking = await service.build_contribution_ranking(
                    period,
                    include_historical_members=_is_historical(period),
                )
                text = service.format_contribution_ranking(
                    ranking,
                    title=f"🏆 Общий вклад — {period.label}",
                    period=period,
                )
            elif report == "violations":
                service = StatsService(session, app_context.config)
                if period.label == "За всё время":
                    text = await service.all_time_violations()
                else:
                    text = await service.violations_ranking_current_cycle(period.start, period.end)
                    text = text.replace("за текущий цикл", f"— {period.label}")
            elif report == "donations":
                stats = await StatsService(session, app_context.config).repo.aggregated_player_stats(
                    clan_tag=app_context.config.main_clan_tag,
                    period_start=period.start,
                    period_end=period.end,
                    include_historical_members=_is_historical(period),
                )
                service = DonationService(session, app_context.config)
                ranking = [
                    DonationRankingRow(
                        row.player_name,
                        row.player_tag,
                        await service.calculate_player_donations_for_period(row.player_tag, period.start, period.end),
                    )
                    for row in stats
                ]
                ranking.sort(key=lambda row: (-row.donations, row.player_name))
                text = "\n".join(
                    [f"🎁 Донаты — {period.label}", ""]
                    + [f"{index}. {row.player_name} — {row.donations}" for index, row in enumerate(ranking, 1)]
                )
            elif report == "capital":
                service = CapitalRaidStatsService(session, app_context.config)
                rows, stats = await service.build_current_cycle_stats(period)
                text = service.format_current_cycle_stats(period, rows, stats).replace("текущий цикл", period.label.lower())
            elif report == "capital_score":
                service = CapitalRaidContributionService(session, app_context.config)
                ranking, stats = await service.build_current_cycle_ranking(period)
                text = service.format_current_cycle_ranking(period, ranking, stats).replace("🧪 Dev вклад в столицу", "🏅 Вклад в столицу")
            elif report == "adjustments":
                rows = await ManualContributionRepository(session).adjustments_in_period(
                    app_context.config.main_clan_tag,
                    period.start,
                    period.end,
                )
                lines = [f"🧮 История ручных баллов — {period.label}", ""]
                if not rows:
                    lines.append("Корректировок нет.")
                for index, row in enumerate(rows, 1):
                    author = f"@{row.created_by_username}" if row.created_by_username else str(row.created_by_telegram_id)
                    lines.extend(
                        [
                            f"{index}. {row.player.name if row.player else row.player_id}: {row.points:+d}",
                            f"Причина: {row.comment}",
                            f"Администратор: {author} · {row.created_at:%d.%m.%Y %H:%M UTC}",
                            "",
                        ]
                    )
                text = "\n".join(lines)
            elif report == "export":
                path = await ExportService(session, app_context.config).export_to_file(
                    period.start,
                    period.end,
                    app_context.export_dir / f"export_{period.start:%Y%m%d}_{period.end:%Y%m%d}.json",
                )
                await message.answer_document(FSInputFile(path), caption=f"📦 JSON — {period.label}")
                return
            elif report == "breakdown":
                ranking = await DevContributionService(session, app_context.config).build_contribution_ranking(
                    period,
                    include_historical_members=_is_historical(period),
                )
                players = [
                    {"player_tag": row.player_tag, "player_name": row.player_name}
                    for row in ranking
                ]
                await state.update_data(
                    admin_breakdown_period=_serialize_period(period),
                    admin_breakdown_players=players,
                )
                entities = [(str(index), row["player_name"]) for index, row in enumerate(players)]
                await message.answer(
                    f"🧾 Разбор вклада — {period.label}\n\nВыберите игрока:",
                    reply_markup=entities_keyboard("admin_breakdown", entities),
                )
                return
            else:
                raise ValueError("Неизвестный отчёт")
        await send_long_message(message, text)
    except ContributionDataUnavailableError as exc:
        await message.answer(f"⚠️ {exc}")
    except Exception:
        logger.exception("Failed to build admin period report: %s", report)
        await message.answer("⚠️ Не удалось построить отчёт. Подробности записаны в журнал.")


@router.callback_query(F.data.startswith("admin_breakdown:"))
async def breakdown_player(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    data = await state.get_data()
    players = data.get("admin_breakdown_players", [])
    if len(parts) == 3 and parts[1] == "select":
        index = int(parts[2])
        if index < 0 or index >= len(players):
            await callback.answer("Игрок недоступен", show_alert=True)
            return
        period = _deserialize_period(data["admin_breakdown_period"])
        selected = players[index]
        async with app_context.session_maker() as session:
            service = ContributionBreakdownService(session, app_context.config)
            breakdown = await service.build_player_breakdown(selected["player_tag"], period)
            text = service.format_detailed_breakdown(breakdown)
        await edit_or_send_long_message(callback.message, text)
        await callback.answer()
        return
    if len(parts) == 3 and parts[1] == "page":
        page = int(parts[2])
        entities = [(str(index), row["player_name"]) for index, row in enumerate(players)]
        await callback.message.edit_reply_markup(reply_markup=entities_keyboard("admin_breakdown", entities, page))
        await callback.answer()
        return
    await state.clear()
    await _edit(callback, _SECTION_TEXT["contribution"], contribution_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_points:start:"))
async def points_start(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    mode = (callback.data or "").rsplit(":", 1)[1]
    async with app_context.session_maker() as session:
        players = await ManualContributionRepository(session).current_main_clan_players(app_context.config.main_clan_tag)
    await state.clear()
    await state.update_data(admin_points_mode=mode, admin_points_players=[player.__dict__ for player in players])
    title = "начисления" if mode == "add" else "списания"
    await _edit(callback, f"Выберите игрока для {title} баллов:", selectable_players_keyboard("admin_points", players))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_points:"))
async def points_callback(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    data = await state.get_data()
    players = data.get("admin_points_players", [])
    if len(parts) >= 2 and parts[1] == "cancel":
        await state.clear()
        await _edit(callback, _SECTION_TEXT["contribution"], contribution_keyboard())
        await callback.answer()
        return
    if len(parts) == 3 and parts[1] == "page":
        async with app_context.session_maker() as session:
            live_players = await ManualContributionRepository(session).current_main_clan_players(app_context.config.main_clan_tag)
        await callback.message.edit_reply_markup(reply_markup=selectable_players_keyboard("admin_points", live_players, int(parts[2])))
        await callback.answer()
        return
    if len(parts) == 3 and parts[1] == "player":
        player_id = int(parts[2])
        selected = next((player for player in players if int(player["player_id"]) == player_id), None)
        if selected is None:
            await callback.answer("Игрок недоступен", show_alert=True)
            return
        await state.update_data(admin_points_player=selected)
        await state.set_state(AdminPanelStates.waiting_adjustment_points)
        verb = "начислить" if data.get("admin_points_mode") == "add" else "снять"
        await callback.message.answer(
            f"Игрок: {selected['player_name']}\nСколько баллов {verb}? Введите число от 1 до 10000.",
            reply_markup=back_keyboard(),
        )
        await callback.answer()
        return
    if len(parts) == 2 and parts[1] == "confirm":
        if await state.get_state() != AdminPanelStates.waiting_adjustment_confirmation.state:
            await callback.answer("Операция устарела", show_alert=True)
            return
        player = data["admin_points_player"]
        signed_points = int(data["admin_points_signed"])
        try:
            async with app_context.session_maker() as session:
                repo = ManualContributionRepository(session)
                await repo.add_manual_adjustment(
                    player_id=int(player["player_id"]),
                    clan_tag=app_context.config.main_clan_tag,
                    points=signed_points,
                    comment=data["admin_points_comment"],
                    created_by_telegram_id=callback.from_user.id,
                    created_by_username=callback.from_user.username,
                    created_at=utcnow(),
                    operation_token=uuid4().hex,
                )
                await session.commit()
            await state.clear()
            await _edit(
                callback,
                f"✅ Корректировка сохранена\n\nИгрок: {player['player_name']}\nБаллы: {signed_points:+d}\nПричина: {data['admin_points_comment']}",
                contribution_keyboard(),
            )
        except Exception:
            logger.exception("Failed to save signed manual adjustment")
            await callback.answer("Не удалось сохранить корректировку", show_alert=True)
            return
        await callback.answer()
        return
    if len(parts) == 2 and parts[1] == "abort":
        await state.clear()
        await _edit(callback, _SECTION_TEXT["contribution"], contribution_keyboard())
        await callback.answer()


@router.message(AdminPanelStates.waiting_adjustment_points)
async def points_amount(message: Message, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        await message.answer(_SECTION_TEXT["contribution"], reply_markup=contribution_keyboard())
        return
    if not text.isdigit() or not 1 <= int(text) <= 10_000:
        await message.answer("⚠️ Введите целое число от 1 до 10000.")
        return
    data = await state.get_data()
    points = int(text) * (1 if data.get("admin_points_mode") == "add" else -1)
    await state.update_data(admin_points_signed=points)
    await state.set_state(AdminPanelStates.waiting_adjustment_comment)
    await message.answer("Укажите причину корректировки (от 3 до 500 символов).", reply_markup=back_keyboard())


@router.message(AdminPanelStates.waiting_adjustment_comment)
async def points_comment(message: Message, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.set_state(AdminPanelStates.waiting_adjustment_points)
        await message.answer("Введите количество баллов от 1 до 10000.", reply_markup=back_keyboard())
        return
    if not 3 <= len(text) <= 500:
        await message.answer("⚠️ Причина должна содержать от 3 до 500 символов.")
        return
    data = await state.get_data()
    player = data["admin_points_player"]
    points = int(data["admin_points_signed"])
    await state.update_data(admin_points_comment=text)
    await state.set_state(AdminPanelStates.waiting_adjustment_confirmation)
    await message.answer(
        f"Подтвердите корректировку:\n\nИгрок: {player['player_name']} ({player['player_tag']})\nБаллы: {points:+d}\nПричина: {text}",
        reply_markup=confirm_keyboard("admin_points:confirm", "admin_points:abort"),
    )


@router.callback_query(F.data == "admin_action:players_list")
async def players_list(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    await _edit(callback, "Выберите сортировку списка игроков:", admin_sort_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:link_player")
async def link_player(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    await state.clear()
    await state.set_state(AdminPlayerLinkStates.waiting_for_telegram_id)
    await callback.message.answer("Введите числовой Telegram ID пользователя.", reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data.in_({"admin_action:all_links", "admin_action:unlink_players"}))
async def links_report(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        links = await TelegramUserRepository(session).list_all_links()
    if not links:
        await _edit(callback, "Привязок пока нет.", players_keyboard())
        await callback.answer()
        return
    if callback.data == "admin_action:all_links":
        lines = ["🔗 <b>Все привязки</b>", ""]
        for index, link in enumerate(links, 1):
            username = f"@{link.username}" if link.username else "без username"
            suffix = "" if link.current_in_clan else " · вне клана"
            lines.append(f"{index}. {link.player_name} ({link.player_tag}) → {username}, ID {link.telegram_id}{suffix}")
        await _edit(callback, "\n".join(lines), players_keyboard())
    else:
        entities = [
            (str(link.link_id), f"{link.player_name} → {('@' + link.username) if link.username else link.telegram_id}")
            for link in links
        ]
        await _edit(callback, "➖ Выберите привязку для удаления:", entities_keyboard("admin_unlink", entities))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_unlink:"))
async def unlink_callback(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    if len(parts) == 3 and parts[1] == "select":
        link_id = int(parts[2])
        await _edit(
            callback,
            "Удалить выбранную привязку? Игрок сможет зарегистрироваться заново.",
            confirm_keyboard(f"admin_unlink:confirm:{link_id}", "admin_panel:players", confirm_text="➖ Отвязать"),
        )
    elif len(parts) == 3 and parts[1] == "confirm":
        async with app_context.session_maker() as session:
            removed = await TelegramUserRepository(session).remove_link(int(parts[2]))
            await session.commit()
        await _edit(callback, "✅ Привязка удалена." if removed else "ℹ️ Привязка уже отсутствует.", players_keyboard())
    elif len(parts) >= 2 and parts[1] == "cancel":
        await _edit(callback, _SECTION_TEXT["players"], players_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:unlinked_players")
async def unlinked_players(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        linked_tags = select(TelegramPlayerLink.player_tag)
        rows = await session.scalars(
            select(PlayerAccount)
            .where(
                PlayerAccount.current_in_clan.is_(True),
                PlayerAccount.current_clan_tag == app_context.config.main_clan_tag,
                PlayerAccount.player_tag.not_in(linked_tags),
            )
            .order_by(PlayerAccount.current_clan_rank.asc().nulls_last(), PlayerAccount.name.asc())
        )
        players = list(rows.all())
    text = "👤 <b>Непривязанные игроки</b>\n\n" + (
        "\n".join(f"{index}. {player.name} ({player.player_tag})" for index, player in enumerate(players, 1))
        if players else "Все действующие игроки привязаны."
    )
    await _edit(callback, text, players_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:add_manual_violation")
async def add_manual_violation(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        service = ManualViolationService(session, app_context.config)
        players = await service.list_players_with_attacks_for_current_cycle()
    if not players:
        await callback.answer("В текущем цикле нет игроков с атаками", show_alert=True)
        return
    await state.clear()
    await state.update_data(player_options=[{"player_tag": row.player_tag, "player_name": row.player_name} for row in players])
    await state.set_state(ManualViolationStates.awaiting_claimed_target_player)
    await callback.message.answer(service.format_players_for_selection(players), reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:remove_manual_violations")
async def remove_manual_violations(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        rows = await session.scalars(
            select(Violation)
            .where(
                Violation.is_manual.is_(True),
                Violation.detected_at >= period.start,
                Violation.detected_at <= period.end,
            )
            .order_by(Violation.detected_at.desc(), Violation.id.desc())
        )
        violations = list(rows.all())
    entities = [
        (str(row.id), f"{row.player_tag} · {row.reason_text} · {row.detected_at:%d.%m}")
        for row in violations
    ]
    if not entities:
        await callback.answer("В текущем цикле нет ручных нарушений", show_alert=True)
        return
    await _edit(callback, "✅ Выберите ручное нарушение, которое нужно снять:", entities_keyboard("admin_manual_violation_remove", entities))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_manual_violation_remove:"))
async def remove_manual_violation_callback(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    if len(parts) == 3 and parts[1] == "select":
        await _edit(
            callback,
            "Снять выбранное ручное нарушение? Автоматические нарушения эта операция не затрагивает.",
            confirm_keyboard(
                f"admin_manual_violation_remove:confirm:{parts[2]}",
                "admin_panel:violations",
                confirm_text="✅ Снять нарушение",
            ),
        )
    elif len(parts) == 3 and parts[1] == "confirm":
        async with app_context.session_maker() as session:
            result = await session.execute(
                delete(Violation).where(Violation.id == int(parts[2]), Violation.is_manual.is_(True))
            )
            await session.commit()
        await _edit(callback, "✅ Ручное нарушение снято." if result.rowcount else "ℹ️ Нарушение уже отсутствует.", violations_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:reduce_violations")
async def reduce_violations(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = StatsService(session, app_context.config)
        options = await service.violation_counter_reset_options(period.start, period.end)
    if not options:
        await callback.answer("Нет активных нарушений для списания", show_alert=True)
        return
    await state.clear()
    await state.update_data(reset_player_options=options)
    await state.set_state(ViolationStates.awaiting_reset_player_number)
    text = service.format_violation_counter_reset_options(options)
    await callback.message.answer(text + "\n\nВведите номер игрока.", reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:restore_violations")
async def restore_violations(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        rows = await session.scalars(
            select(ViolationCounterReset)
            .where(
                ViolationCounterReset.cycle_start == period.start,
                ViolationCounterReset.reset_amount.is_not(None),
            )
            .order_by(ViolationCounterReset.reset_at.desc(), ViolationCounterReset.id.desc())
        )
        resets = list(rows.all())
    entities = [
        (str(row.id), f"{row.player_tag} · вернуть {row.reset_amount} · {row.reset_at:%d.%m %H:%M}")
        for row in resets
    ]
    if not entities:
        await callback.answer("В текущем цикле нет списаний для возврата", show_alert=True)
        return
    await _edit(callback, "↩️ Выберите списание, которое нужно отменить:", entities_keyboard("admin_reset_restore", entities))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_reset_restore:"))
async def restore_reset_callback(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    if len(parts) == 3 and parts[1] == "select":
        await _edit(
            callback,
            "Вернуть нарушения, ранее списанные этой операцией? История самих нарушений не меняется.",
            confirm_keyboard(f"admin_reset_restore:confirm:{parts[2]}", "admin_panel:violations", confirm_text="↩️ Вернуть"),
        )
    elif len(parts) == 3 and parts[1] == "confirm":
        async with app_context.session_maker() as session:
            result = await session.execute(
                delete(ViolationCounterReset).where(
                    ViolationCounterReset.id == int(parts[2]),
                    ViolationCounterReset.reset_amount.is_not(None),
                )
            )
            await session.commit()
        await _edit(callback, "✅ Списание отменено." if result.rowcount else "ℹ️ Операция уже отсутствует.", violations_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:recalculate")
async def recalculate(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    await _edit(
        callback,
        "Пересчитать автоматические нарушения обычных войн текущего цикла?",
        violation_recalculation_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_action:update_chat")
async def update_chat(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    await state.clear()
    await state.set_state(ChatLinkStates.waiting_for_chat_link)
    await callback.message.answer("Отправьте новую ссылку на чат клана.", reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:clear_chat_confirm")
async def clear_chat_confirm(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    await _edit(
        callback,
        "Удалить сохранённую ссылку на чат клана?",
        confirm_keyboard("admin_action:clear_chat", "admin_panel:system", confirm_text="🗑 Удалить ссылку"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_action:clear_chat")
async def clear_chat(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    async with app_context.session_maker() as session:
        await ClanChatService(session, app_context.config).update_chat_url("")
    await _edit(callback, "✅ Ссылка на чат удалена.", system_keyboard())
    await callback.answer()


@router.callback_query(F.data.in_({"admin_action:logs", "admin_action:error_logs"}))
async def logs(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    text = app_context.log_service.tail(300)
    if callback.data == "admin_action:error_logs":
        lines = [line for line in text.splitlines() if " ERROR " in line or " CRITICAL " in line or "Traceback" in line]
        text = "\n".join(lines[-100:]) or "Ошибок в последних строках журнала нет."
    await send_long_message(callback.message, text)
    await callback.answer()


@router.callback_query(F.data == "admin_action:download_log")
async def download_log(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    path = app_context.log_service.file_path()
    if not path.exists():
        path.write_text("", encoding="utf-8")
    await callback.message.answer_document(FSInputFile(path), caption="🗂 Полный лог-файл")
    await callback.answer()


@router.callback_query(F.data == "admin_action:bot_status")
async def bot_status(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    db_url = app_context.settings.database_url
    log_path = app_context.log_service.file_path()
    text = [
        "🩺 <b>Состояние бота</b>",
        "",
        "✅ Процесс отвечает на callback",
        f"🗄 База: {'SQLite' if str(db_url).startswith('sqlite') else 'внешняя БД'}",
        f"📜 Размер лога: {log_path.stat().st_size if log_path.exists() else 0} байт",
        f"⚔️ Интервал войн: {app_context.config.polling.war_seconds} сек.",
        f"👥 Интервал состава: {app_context.config.polling.clan_seconds} сек.",
    ]
    await _edit(callback, "\n".join(text), system_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_action:security_status")
async def security_status(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    path = Path(app_context.settings.security_state_file)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    text = [
        "🔐 <b>Состояние защиты</b>",
        "",
        f"Последняя успешная проверка: {data.get('last_successful_security_check') or 'нет данных'}",
        f"Последняя проверка пустого webhook: {data.get('last_known_empty_webhook_check') or 'нет данных'}",
        f"Наблюдаемый bot ID: {data.get('observed_bot_id') or 'нет данных'}",
        f"Username: @{data.get('observed_username') or 'нет данных'}",
        f"Git revision: {data.get('git_revision') or 'unknown'}",
        f"Инцидентов webhook: {len(data.get('incidents') or [])}",
    ]
    await _edit(callback, "\n".join(text), security_keyboard())
    await callback.answer()


@router.callback_query(F.data.in_({"admin_action:current_war", "admin_action:missing_attacks"}))
async def current_war(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    try:
        war = await app_context.clash_client.get_current_war(app_context.config.main_clan_tag)
    except Exception:
        logger.exception("Failed to fetch current war for admin panel")
        await callback.answer("Не удалось получить текущую войну", show_alert=True)
        return
    if war is None:
        await _edit(callback, "⚔️ Сейчас активной войны нет.", war_keyboard())
        await callback.answer()
        return
    clan = getattr(war, "clan", None)
    opponent = getattr(war, "opponent", None)
    members = list(getattr(clan, "members", []) or [])
    attacks_per_member = int(getattr(war, "attacks_per_member", 2) or 2)
    if callback.data == "admin_action:missing_attacks":
        missing = []
        for member in members:
            used = len(getattr(member, "attacks", []) or [])
            left = max(0, attacks_per_member - used)
            if left:
                missing.append((getattr(member, "map_position", 999), getattr(member, "name", "Игрок"), left))
        missing.sort()
        text = "🗡 <b>Оставшиеся атаки</b>\n\n" + (
            "\n".join(f"{position}. {name} — осталось {left}" for position, name, left in missing)
            if missing else "Все доступные атаки использованы."
        )
    else:
        text = "\n".join(
            [
                "⚔️ <b>Текущая война</b>",
                "",
                f"Состояние: {getattr(war, 'state', 'неизвестно')}",
                f"Соперник: {getattr(opponent, 'name', 'неизвестно')}",
                f"Счёт: {getattr(clan, 'stars', 0)} ⭐ — {getattr(opponent, 'stars', 0)} ⭐",
                f"Участников: {getattr(war, 'team_size', len(members))}",
            ]
        )
    await _edit(callback, text, war_keyboard())
    await callback.answer()


@router.callback_query(F.data.in_({"admin_action:sync_confirm", "admin_action:membership_events", "admin_action:conversations"}))
async def delegated_placeholder(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    labels = {
        "admin_action:sync_confirm": "Ручная синхронизация будет подключена после переноса scheduler-состояния в AppContext.",
        "admin_action:membership_events": "Раздел выходов и возвратов готовится на основе сохранённых событий членства.",
        "admin_action:conversations": "Откройте старую кнопку «💬 Переписки с ботом» до переноса просмотрщика в общую панель.",
    }
    await callback.answer(labels[callback.data], show_alert=True)
