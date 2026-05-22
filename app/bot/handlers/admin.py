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
from app.bot.states.manual_violation import ManualViolationStates
from app.bot.states.violations import ViolationStates
from app.container import AppContext
from app.services.clan_chat import ClanChatService
from app.services.capital_raid_report import CapitalRaidReportService
from app.services.capital_raid_contribution import CapitalRaidContributionService
from app.services.capital_raid_sync import CapitalRaidSyncService
from app.services.dev_contribution import ContributionDataUnavailableError, DevContributionService
from app.services.donations import DonationService
from app.services.export import ExportService
from app.services.period import PeriodService
from app.services.registration import RegistrationService
from app.services.manual_violation import ManualViolationService
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


@router.message(F.text == "🧪 Dev-столица")
async def dev_capital(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            await CapitalRaidSyncService(session, app_context.clash_client, app_context.config).repair_current_cycle_missing_participants(period)
            service = CapitalRaidContributionService(session, app_context.config)
            ranking, destroy_stats_available, stats, _ = await service.build_current_cycle_ranking(period)
            text = service.format_current_cycle_ranking(period, ranking, destroy_stats_available, stats)
        await send_long_message(message, text)
    except Exception:
        logger.exception("Failed to build dev capital contribution report")
        await message.answer("⚠️ Не удалось построить отчет по Dev-столице. Попробуйте позже.")


@router.message(F.text == "🚨 Нарушения")
async def current_cycle_violations(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = StatsService(session, app_context.config)
        options = await service.violations_ranking_current_cycle_data(period.start, period.end)
        text = await service.violations_ranking_current_cycle(period.start, period.end)
    if not options:
        await send_long_message(message, text)
        return

    await state.update_data(violation_player_options=options)
    await state.set_state(ViolationStates.awaiting_violation_player_number)
    await send_long_message(message, text + "\n\nВведите номер игрока, чтобы посмотреть его нарушения.\nИли нажмите ⬅️ Назад.")


@router.message(ViolationStates.awaiting_violation_player_number)
async def violation_player_selected(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        await state.clear()
        return

    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(message.from_user.id)
        await message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        return

    try:
        idx = int(text)
    except ValueError:
        await message.answer("⚠️ Введите номер игрока из списка или нажмите ⬅️ Назад.")
        return

    data = await state.get_data()
    options = data.get("violation_player_options", [])
    if idx < 1 or idx > len(options):
        await message.answer("⚠️ Нет игрока с таким номером.")
        return

    selected = options[idx - 1]
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            service = StatsService(session, app_context.config)
            report = await service.build_player_violations_report(
                period.start,
                period.end,
                selected["player_tag"],
                selected["player_name"],
            )
        await send_long_message(message, report)
        await state.clear()
    except Exception:
        logger.exception("Failed to load player violations report")
        await state.clear()
        await message.answer("⚠️ Не удалось загрузить нарушения игрока. Попробуйте позже.")


@router.message(F.text == "🚩 Чужой флажок")
async def manual_claimed_target_start(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        service = ManualViolationService(session, app_context.config)
        players = await service.list_players_with_attacks_for_current_cycle()
        if not players:
            await message.answer("⚠️ В текущем цикле нет игроков с атаками.")
            return
        await state.update_data(player_options=[{"player_tag": p.player_tag, "player_name": p.player_name} for p in players])
        await state.set_state(ManualViolationStates.awaiting_claimed_target_player)
        await message.answer(service.format_players_for_selection(players))


@router.message(ManualViolationStates.awaiting_claimed_target_player)
async def manual_claimed_target_player_selected(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(message.from_user.id)
        await message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        return
    try:
        idx = int(text)
    except ValueError:
        await message.answer("⚠️ Введите номер игрока из списка.")
        return
    data = await state.get_data()
    options = data.get("player_options", [])
    if idx < 1 or idx > len(options):
        await message.answer("⚠️ Нет игрока с таким номером.")
        return
    try:
        selected = options[idx - 1]
        async with app_context.session_maker() as session:
            service = ManualViolationService(session, app_context.config)
            attacks = await service.list_player_attacks_for_current_cycle(selected["player_tag"])
            if not attacks:
                await message.answer("⚠️ У этого игрока нет атак в текущем цикле.")
                return
            await state.update_data(selected_player=selected, attack_options=[{"attack_id": a.id} for a, _, _ in attacks])
            await state.set_state(ManualViolationStates.awaiting_claimed_target_attack)
            await message.answer(service.format_attacks_for_selection(selected["player_name"], attacks))
    except Exception:
        logger.exception("Failed to load attacks for manual claimed_target selection")
        await message.answer("⚠️ Не удалось загрузить атаки игрока. Попробуйте позже.")


@router.message(ManualViolationStates.awaiting_claimed_target_attack)
async def manual_claimed_target_attack_selected(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == "⬅️ Назад":
        async with app_context.session_maker() as session:
            service = ManualViolationService(session, app_context.config)
            players_live = await service.list_players_with_attacks_for_current_cycle()
            await state.update_data(player_options=[{"player_tag": p.player_tag, "player_name": p.player_name} for p in players_live], attack_options=[])
            await state.set_state(ManualViolationStates.awaiting_claimed_target_player)
            if not players_live:
                await state.clear()
                await message.answer("⚠️ В текущем цикле нет игроков с атаками.")
                return
            await message.answer(service.format_players_for_selection(players_live))
        return
    try:
        idx = int(text)
    except ValueError:
        await message.answer("⚠️ Введите номер атаки из списка.")
        return
    options = data.get("attack_options", [])
    if idx < 1 or idx > len(options):
        await message.answer("⚠️ Нет атаки с таким номером.")
        return
    try:
        attack_id = options[idx - 1]["attack_id"]
        async with app_context.session_maker() as session:
            service = ManualViolationService(session, app_context.config)
            confirm_text = await service.apply_claimed_target_violation(attack_id, admin_telegram_id=message.from_user.id)
            await session.commit()
        await state.clear()
        await message.answer(confirm_text)
    except Exception:
        logger.exception("Failed to apply manual claimed_target violation")
        await state.clear()
        await message.answer("⚠️ Не удалось поставить нарушение. Попробуйте позже.")


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
