from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

from aiogram import F, Router
from sqlalchemy.exc import IntegrityError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards.common import (
    admin_menu_button_keyboard,
    admin_player_link_keyboard,
    admin_sort_keyboard,
    manual_contribution_cancel_keyboard,
    manual_contribution_confirm_keyboard,
    manual_contribution_players_keyboard,
)
from app.bot.keyboards.main import back_keyboard, main_menu, violation_reset_amount_keyboard
from app.bot.utils.telegram_text import edit_or_send_long_message, send_long_message
from app.bot.states.chat_link import ChatLinkStates
from app.bot.states.contribution_breakdown import ContributionBreakdownStates
from app.bot.states.manual_contribution import ManualContributionStates
from app.bot.states.admin_player_link import AdminPlayerLinkStates
from app.bot.states.manual_violation import ManualViolationStates
from app.bot.states.violations import ViolationStates
from app.container import AppContext
from app.services.clan_chat import ClanChatService
from app.services.capital_raid_report import CapitalRaidStatsService
from app.services.capital_raid_contribution import CapitalRaidContributionService
from app.services.contribution_breakdown import ContributionBreakdownService
from app.services.dev_contribution import ContributionDataUnavailableError, DevContributionService
from app.services.donations import DonationService
from app.services.export import ExportService
from app.services.period import PeriodService
from app.services.registration import RegistrationService
from app.services.admin_player_link import (
    AdminPlayerLinkService,
    PlayerAlreadyLinkedToAnotherTelegramError,
    PlayerNotAvailableForLinkError,
)
from app.services.manual_violation import ManualViolationService
from app.services.stats import StatsService
from app.repositories.player_account import PlayerAccountRepository
from app.repositories.telegram_user import TelegramUserRepository
from app.repositories.manual_contribution import ManualContributionRepository
from app.services.active_violation_counter import ActiveViolationCounterService
from app.utils.time import utcnow

router = Router(name="admin")
logger = logging.getLogger(__name__)

CONTRIBUTION_BUILD_ERROR = "⚠️ Не удалось построить отчет по общему вкладу. Попробуйте позже."
CONTRIBUTION_CYCLE_DATA_ERROR = "⚠️ Общий вклад пока недоступен: в текущем цикле еще недостаточно данных."
PREVIOUS_CONTRIBUTION_UNAVAILABLE_ERROR = (
    "⚠️ Общий вклад за прошлый цикл недоступен: "
    "в базе недостаточно границ циклов ЛВК."
)
PREVIOUS_CONTRIBUTION_DATA_ERROR = (
    "⚠️ Общий вклад за прошлый цикл недоступен: "
    "за прошлый цикл недостаточно данных."
)
PREVIOUS_CONTRIBUTION_BUILD_ERROR = (
    "⚠️ Не удалось построить отчет по общему вкладу "
    "за прошлый цикл. Попробуйте позже."
)


def _ensure_admin(app_context: AppContext, telegram_id: int) -> None:
    if not app_context.auth_service.is_admin(telegram_id):
        raise PermissionError("Недостаточно прав")


async def _admin_is_registered(app_context: AppContext, telegram_id: int) -> bool:
    async with app_context.session_maker() as session:
        return await RegistrationService(session, app_context.clash_client).is_registered(telegram_id)


@router.message(F.text == "🔗 Привязать игрока")
async def admin_player_link_start(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    await state.clear()
    await state.set_state(AdminPlayerLinkStates.waiting_for_telegram_id)
    await message.answer(
        "🔗 Ручная привязка игрока\n\n"
        "Введите числовой Telegram ID пользователя, которому нужно привязать игровой аккаунт.\n\n"
        "Telegram ID можно узнать у пользователя через Telegram-ботов для определения ID.",
        reply_markup=back_keyboard(),
    )


@router.message(AdminPlayerLinkStates.waiting_for_telegram_id)
async def admin_player_link_receive_telegram_id(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        is_registered = await _admin_is_registered(app_context, message.from_user.id)
        await message.answer("Административное меню", reply_markup=main_menu(is_admin=True, is_registered=is_registered))
        return
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ Telegram ID должен состоять только из цифр и быть больше нуля. Попробуйте ещё раз или нажмите ⬅️ Назад.")
        return
    telegram_id = int(text)
    async with app_context.session_maker() as session:
        players = await AdminPlayerLinkService(session, app_context.config).list_active_players()
    if not players:
        await state.clear()
        await message.answer("⚠️ В основном клане нет доступных игроков для привязки.")
        return
    await state.update_data(target_telegram_id=telegram_id)
    await state.set_state(AdminPlayerLinkStates.choosing_player)
    await message.answer(
        f"Выберите игрока, которого нужно привязать к Telegram ID {telegram_id}.",
        reply_markup=admin_player_link_keyboard(players, page=0),
    )


@router.callback_query(AdminPlayerLinkStates.choosing_player, F.data.startswith("admin_player_link:page:"))
async def admin_player_link_change_page(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, callback.from_user.id)
    except PermissionError:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    data = await state.get_data()
    telegram_id = data.get("target_telegram_id")
    if telegram_id is None:
        await state.clear()
        await callback.answer("Сессия устарела. Начните привязку заново.", show_alert=True)
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        page = 0
    async with app_context.session_maker() as session:
        players = await AdminPlayerLinkService(session, app_context.config).list_active_players()
    max_page = max(0, (len(players) - 1) // 10)
    page = min(max(page, 0), max_page)
    await callback.message.edit_text(
        f"Выберите игрока, которого нужно привязать к Telegram ID {telegram_id}.",
        reply_markup=admin_player_link_keyboard(players, page=page),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_player_link:change_user")
async def admin_player_link_change_user(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, callback.from_user.id)
    except PermissionError:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminPlayerLinkStates.waiting_for_telegram_id)
    await callback.message.edit_text("Введите другой числовой Telegram ID пользователя.")
    await callback.answer()


@router.callback_query(F.data == "admin_player_link:cancel")
async def admin_player_link_cancel(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, callback.from_user.id)
    except PermissionError:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text("❌ Ручная привязка отменена.")
    is_registered = await _admin_is_registered(app_context, callback.from_user.id)
    await callback.message.answer("Административное меню", reply_markup=main_menu(is_admin=True, is_registered=is_registered))
    await callback.answer()


@router.callback_query(AdminPlayerLinkStates.choosing_player, F.data.startswith("admin_player_link:player:"))
async def admin_player_link_select_player(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, callback.from_user.id)
    except PermissionError:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    data = await state.get_data()
    telegram_id = data.get("target_telegram_id")
    if telegram_id is None:
        await state.clear()
        await callback.answer("Сессия устарела. Начните привязку заново.", show_alert=True)
        return
    player_tag = (callback.data or "").split("admin_player_link:player:", 1)[1]
    try:
        async with app_context.session_maker() as session:
            result = await AdminPlayerLinkService(session, app_context.config).link_player(
                telegram_id=int(telegram_id),
                player_tag=player_tag,
            )
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(callback.from_user.id)
    except PlayerAlreadyLinkedToAnotherTelegramError as exc:
        await callback.answer(
            "Этот игровой аккаунт уже привязан к Telegram ID: " + ", ".join(str(i) for i in exc.owner_telegram_ids),
            show_alert=True,
        )
        return
    except PlayerNotAvailableForLinkError:
        await callback.answer("Игрок больше не состоит в основном клане. Обновите список.", show_alert=True)
        return
    except Exception:
        logger.exception("Failed to manually link player")
        await state.clear()
        await callback.answer("⚠️ Не удалось выполнить ручную привязку. Попробуйте позже.", show_alert=True)
        return

    await state.clear()
    if result.already_linked:
        await callback.message.edit_text(
            f"ℹ️ Игрок {result.player_name} ({result.player_tag}) уже привязан к Telegram ID {result.telegram_id}. Изменения не требуются."
        )
    else:
        await callback.message.edit_text(
            f"✅ Игрок {result.player_name} ({result.player_tag}) привязан к Telegram ID {result.telegram_id}."
        )
        logger.info(
            "Admin %s manually linked player %s to Telegram ID %s",
            callback.from_user.id,
            result.player_tag,
            result.telegram_id,
        )
    await callback.message.answer("Административное меню", reply_markup=main_menu(is_admin=True, is_registered=is_registered))
    await callback.answer()


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


@router.message(F.text == "📚 Вклад прошлого цикла")
async def previous_cycle_contribution(
    message: Message,
    app_context: AppContext,
) -> None:
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).previous_cycle()
            service = DevContributionService(session, app_context.config)
            ranking = await service.build_contribution_ranking(
                period,
                include_historical_members=True,
            )
            text = service.format_contribution_ranking(
                ranking,
                title="🏆 Общий вклад за прошлый цикл",
                period=period,
            )

        await send_long_message(message, text)
    except ValueError as exc:
        if "Прошлый цикл недоступен" in str(exc):
            await message.answer(PREVIOUS_CONTRIBUTION_UNAVAILABLE_ERROR)
            return
        logger.exception(
            "Failed to build previous cycle contribution due to invalid period data"
        )
        await message.answer(PREVIOUS_CONTRIBUTION_DATA_ERROR)
    except ContributionDataUnavailableError:
        await message.answer(PREVIOUS_CONTRIBUTION_DATA_ERROR)
    except TypeError:
        logger.exception("Failed to build previous cycle contribution due to malformed data")
        await message.answer(PREVIOUS_CONTRIBUTION_DATA_ERROR)
    except Exception:
        logger.exception("Failed to build previous cycle contribution report")
        await message.answer(PREVIOUS_CONTRIBUTION_BUILD_ERROR)


@router.message(F.text == "📋 Мой вклад")
async def my_contribution_breakdown(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
    async with app_context.session_maker() as session:
        user_repo = TelegramUserRepository(session)
        telegram_user = await user_repo.get_by_telegram_id(message.from_user.id)
        links = await user_repo.get_links(telegram_user.id) if telegram_user is not None else []
        if not links:
            await message.answer("⚠️ Вы еще не привязаны к участнику клана.")
            return
        if len(links) > 1:
            player_repo = PlayerAccountRepository(session)
            options = []
            for link in links:
                player = await player_repo.get_by_tag(link.player_tag)
                options.append(
                    {
                        "player_tag": link.player_tag,
                        "player_name": player.name if player is not None else link.player_tag,
                    }
                )
            await state.update_data(my_contribution_options=options)
            await state.set_state(
                ContributionBreakdownStates.awaiting_my_contribution_player_number
            )
            account_lines = [
                f"{index}. {option['player_name']} ({option['player_tag']})"
                for index, option in enumerate(options, start=1)
            ]
            text = "\n".join(
                [
                    "📋 Мой вклад",
                    "У вас привязано несколько аккаунтов.",
                    "Выберите аккаунт по номеру.",
                    "",
                    *account_lines,
                    "",
                    "Введите номер аккаунта или нажмите ⬅️ Назад.",
                ]
            )
            await send_long_message(message, text, reply_markup=back_keyboard())
            return
        period = await PeriodService(session).current_cycle()
        service = ContributionBreakdownService(session, app_context.config)
        breakdown = await service.build_player_breakdown(links[0].player_tag, period)
        text = service.format_short_breakdown(breakdown)
    await send_long_message(message, text)


@router.message(ContributionBreakdownStates.awaiting_my_contribution_player_number)
async def my_contribution_breakdown_selected(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(
                session, app_context.clash_client
            ).is_registered(message.from_user.id)
        await message.answer(
            "Главное меню",
            reply_markup=main_menu(
                app_context.auth_service.is_admin(message.from_user.id), is_registered
            ),
        )
        return

    try:
        player_number = int(text)
    except ValueError:
        await message.answer(
            "⚠️ Введите номер аккаунта из списка или нажмите ⬅️ Назад."
        )
        return

    data = await state.get_data()
    options = data.get("my_contribution_options", [])
    if player_number < 1 or player_number > len(options):
        await message.answer("⚠️ Нет аккаунта с таким номером.")
        return

    selected = options[player_number - 1]
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            service = ContributionBreakdownService(session, app_context.config)
            breakdown = await service.build_player_breakdown(
                selected["player_tag"], period
            )
            report = service.format_short_breakdown(breakdown)
        await send_long_message(message, report)
        await state.clear()
    except Exception:
        logger.exception("Failed to load my contribution breakdown for selected account")
        await message.answer(
            "⚠️ Не удалось загрузить вклад по выбранному аккаунту. Попробуйте позже."
        )
        await state.clear()


@router.message(F.text == "🧾 Разбор вклада")
async def contribution_breakdown_start(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = DevContributionService(session, app_context.config)
        ranking = await service.build_contribution_ranking(period)
        text = service.format_contribution_ranking(ranking)
    await state.update_data(
        contribution_breakdown_players=[
            {"player_tag": row.player_tag, "player_name": row.player_name} for row in ranking
        ]
    )
    await state.set_state(ContributionBreakdownStates.awaiting_player_number)
    await send_long_message(
        message,
        text
        + "\n\nВведите номер игрока, чтобы посмотреть подробную расшифровку вклада."
        + "\nИли нажмите ⬅️ Назад.",
        reply_markup=back_keyboard(),
    )


@router.message(ContributionBreakdownStates.awaiting_player_number)
async def contribution_breakdown_selected(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
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
            is_registered = await RegistrationService(
                session, app_context.clash_client
            ).is_registered(message.from_user.id)
        await message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        return

    try:
        player_number = int(text)
    except ValueError:
        await message.answer("⚠️ Введите номер игрока из списка или нажмите ⬅️ Назад.")
        return

    data = await state.get_data()
    players = data.get("contribution_breakdown_players", [])
    if player_number < 1 or player_number > len(players):
        await message.answer("⚠️ Нет игрока с таким номером.")
        return

    selected = players[player_number - 1]
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = ContributionBreakdownService(session, app_context.config)
        breakdown = await service.build_player_breakdown(selected["player_tag"], period)
        report = service.format_detailed_breakdown(breakdown)
        is_registered = await RegistrationService(
            session, app_context.clash_client
        ).is_registered(message.from_user.id)
    await state.clear()
    await send_long_message(
        message, report, reply_markup=main_menu(True, is_registered)
    )


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


@router.message(F.text == "🧪 Dev вклад в столицу")
async def dev_capital(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            service = CapitalRaidContributionService(session, app_context.config)
            ranking, stats = await service.build_current_cycle_ranking(period)
            text = service.format_current_cycle_ranking(period, ranking, stats)
        await send_long_message(message, text)
    except Exception:
        logger.exception("Failed to build dev capital contribution report")
        await message.answer("⚠️ Не удалось построить отчет по вкладу в столицу. Попробуйте позже.")


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


@router.message(F.text == "🗄 Все нарушения")
async def all_time_violations(
    message: Message,
    state: FSMContext,
    app_context: AppContext,
) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    try:
        async with app_context.session_maker() as session:
            service = StatsService(session, app_context.config)
            options = await service.all_time_violations_data()
            text = await service.all_time_violations()
        if not options:
            await state.clear()
            await message.answer(text)
            return

        await state.clear()
        await state.update_data(all_violation_player_options=options)
        await state.set_state(ViolationStates.awaiting_all_violations_player_number)
        await message.answer(
            text
            + "\n\nВведите номер игрока, чтобы посмотреть всю историю его нарушений."
            + "\nИли нажмите ⬅️ Назад.",
            reply_markup=back_keyboard(),
        )
    except Exception:
        logger.exception(
            "Failed to load all-time violations ranking"
        )
        await state.clear()
        await message.answer("⚠️ Не удалось загрузить полную историю нарушений. Попробуйте позже.")


@router.message(F.text == "♻️ Сбросить счетчик нарушений")
async def reset_violation_counter_start(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        period = await PeriodService(session).current_cycle()
        service = StatsService(session, app_context.config)
        options = await service.violation_counter_reset_options(period.start, period.end)
        text = service.format_violation_counter_reset_options(options)
    if not options:
        await send_long_message(message, text)
        return

    await state.update_data(reset_player_options=options)
    await state.set_state(ViolationStates.awaiting_reset_player_number)
    await send_long_message(
        message,
        text
        + "\n\nВведите номер игрока, для которого нужно уменьшить активный счетчик."
        + "\nИли нажмите ⬅️ Назад.",
        reply_markup=back_keyboard(),
    )


@router.message(ViolationStates.awaiting_reset_player_number)
async def reset_violation_counter_selected(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
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
            is_registered = await RegistrationService(
                session, app_context.clash_client
            ).is_registered(message.from_user.id)
        await message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        return

    try:
        idx = int(text)
    except ValueError:
        await message.answer("⚠️ Введите номер игрока из списка или нажмите ⬅️ Назад.")
        return

    data = await state.get_data()
    options = data.get("reset_player_options", [])
    if idx < 1 or idx > len(options):
        await message.answer("⚠️ Нет игрока с таким номером.")
        return

    selected = options[idx - 1]
    active_count = int(selected["violations"])
    await state.update_data(
        reset_player_tag=selected["player_tag"],
        reset_player_name=selected["player_name"],
        reset_player_active_violations=active_count,
    )
    await state.set_state(ViolationStates.awaiting_reset_amount)
    await message.answer(
        f"Игрок: {selected['player_name']}\n"
        f"Активных нарушений: {active_count}\n\n"
        "Сколько нарушений списать из активного счетчика?",
        reply_markup=violation_reset_amount_keyboard(active_count),
    )


@router.message(ViolationStates.awaiting_reset_amount)
async def reset_violation_counter_amount_selected(
    message: Message, state: FSMContext, app_context: AppContext
) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        await state.clear()
        return

    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            service = StatsService(session, app_context.config)
            options = await service.violation_counter_reset_options(period.start, period.end)
            response_text = service.format_violation_counter_reset_options(options)
        if not options:
            await state.clear()
            async with app_context.session_maker() as session:
                is_registered = await RegistrationService(
                    session, app_context.clash_client
                ).is_registered(message.from_user.id)
            await message.answer(
                "✅ Нет игроков с активными нарушениями для списания.",
                reply_markup=main_menu(is_admin=True, is_registered=is_registered),
            )
            return
        await state.update_data(reset_player_options=options)
        await state.set_state(ViolationStates.awaiting_reset_player_number)
        await send_long_message(
            message,
            response_text
            + "\n\nВведите номер игрока, для которого нужно уменьшить активный счетчик."
            + "\nИли нажмите ⬅️ Назад.",
            reply_markup=back_keyboard(),
        )
        return

    data = await state.get_data()
    active_count = int(data.get("reset_player_active_violations") or 0)
    if text not in {"1", "2", "3"} or int(text) > active_count:
        await message.answer("⚠️ Выберите доступное количество нарушений кнопкой: 1, 2 или 3.")
        return

    amount = int(text)
    player_tag = data.get("reset_player_tag")
    player_name = data.get("reset_player_name")
    if not player_tag or not player_name:
        await state.clear()
        await message.answer("⚠️ Сессия устарела. Начните списание заново.")
        return

    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            remaining = await ActiveViolationCounterService(session).reduce_for_player(
                player_tag=player_tag,
                cycle_start=period.start,
                cycle_end=period.end,
                amount=amount,
                admin_telegram_id=message.from_user.id,
                reset_at=utcnow(),
            )
            await session.commit()
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(message.from_user.id)
        await state.clear()
        await message.answer(
            "✅ Активный счетчик нарушений уменьшен\n"
            f"Игрок: {player_name}\n"
            f"Списано нарушений: {amount}\n"
            f"Осталось активных нарушений: {remaining}\n\n"
            "История нарушений не удалена и доступна по кнопке 🚨 Нарушения.",
            reply_markup=main_menu(True, is_registered),
        )
    except ValueError as exc:
        await state.clear()
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(message.from_user.id)
        await message.answer(
            f"⚠️ {exc}",
            reply_markup=main_menu(True, is_registered),
        )
    except Exception:
        logger.exception("Failed to reduce player violation counter")
        await state.clear()
        await message.answer("⚠️ Не удалось изменить счетчик нарушений. Попробуйте позже.")


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


@router.message(
    ViolationStates.awaiting_all_violations_player_number
)
async def all_time_violation_player_selected(
    message: Message,
    state: FSMContext,
    app_context: AppContext,
) -> None:
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
            is_registered = await RegistrationService(
                session, app_context.clash_client
            ).is_registered(message.from_user.id)
        await message.answer(
            "Главное меню",
            reply_markup=main_menu(
                is_admin=True,
                is_registered=is_registered,
            ),
        )
        return

    try:
        idx = int(text)
    except ValueError:
        await message.answer("⚠️ Введите номер игрока из списка или нажмите ⬅️ Назад.")
        return

    data = await state.get_data()
    options = data.get("all_violation_player_options", [])
    if idx < 1 or idx > len(options):
        await message.answer("⚠️ Нет игрока с таким номером.")
        return

    selected = options[idx - 1]
    try:
        async with app_context.session_maker() as session:
            report = await StatsService(
                session,
                app_context.config,
            ).build_player_all_time_violations_report(
                player_tag=selected["player_tag"],
                player_name=selected["player_name"],
            )
        await send_long_message(message, report)
        await state.clear()
    except Exception:
        logger.exception(
            "Failed to load player all-time violations report"
        )
        await state.clear()
        await message.answer("⚠️ Не удалось загрузить полную историю нарушений игрока. Попробуйте позже.")


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
        await message.answer(service.format_players_for_selection(players), reply_markup=back_keyboard())


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
            await message.answer(
                service.format_attacks_for_selection(selected["player_name"], attacks),
                reply_markup=back_keyboard(),
            )
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
            await message.answer(service.format_players_for_selection(players_live), reply_markup=back_keyboard())
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
    except ValueError as exc:
        await state.clear()
        await message.answer(str(exc))
    except Exception:
        logger.exception("Failed to apply manual claimed_target violation")
        await state.clear()
        await message.answer("⚠️ Не удалось поставить нарушение. Попробуйте позже.")



async def _return_admin_menu(message: Message, state: FSMContext, app_context: AppContext, text: str = "Главное меню") -> None:
    await state.clear()
    async with app_context.session_maker() as session:
        is_registered = await RegistrationService(session, app_context.clash_client).is_registered(message.from_user.id)
    await message.answer(text, reply_markup=main_menu(True, is_registered))


@router.message(F.text == "➕ Начислить баллы")
async def manual_contribution_start(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    async with app_context.session_maker() as session:
        players = await ManualContributionRepository(session).current_main_clan_players(app_context.config.main_clan_tag)
    await state.set_state(ManualContributionStates.choosing_player)
    await state.update_data(manual_contribution_saved_id=None)
    if not players:
        await message.answer("⚠️ В основном клане сейчас нет игроков.", reply_markup=manual_contribution_cancel_keyboard(back=False))
        return
    await message.answer(
        "Выберите игрока для начисления баллов:",
        reply_markup=manual_contribution_players_keyboard(players, 0),
    )


@router.callback_query(F.data.startswith("manual_contribution:"))
async def manual_contribution_callback(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, callback.from_user.id)
    except PermissionError:
        await callback.answer("⛔ Недостаточно прав")
        return
    data = callback.data or ""
    parts = data.split(":")
    if len(parts) < 2:
        await callback.answer("⚠️ Некорректная операция", show_alert=True)
        return
    action = parts[1]
    if action == "admin_menu":
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(callback.from_user.id)
        await callback.message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        await callback.answer()
        return
    if action == "cancel":
        await state.clear()
        async with app_context.session_maker() as session:
            is_registered = await RegistrationService(session, app_context.clash_client).is_registered(callback.from_user.id)
        await callback.message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        await callback.answer()
        return
    if action == "page":
        try:
            page = max(0, int(parts[2]))
        except (IndexError, ValueError):
            await callback.answer("⚠️ Некорректная операция", show_alert=True)
            return
        async with app_context.session_maker() as session:
            players = await ManualContributionRepository(session).current_main_clan_players(app_context.config.main_clan_tag)
        await callback.message.edit_reply_markup(reply_markup=manual_contribution_players_keyboard(players, page))
        await callback.answer()
        return
    if action == "player":
        try:
            player_id = int(parts[2])
        except (IndexError, ValueError):
            await callback.answer("⚠️ Некорректная операция", show_alert=True)
            return
        async with app_context.session_maker() as session:
            player = await ManualContributionRepository(session).get_current_main_clan_player(player_id, app_context.config.main_clan_tag)
        if player is None:
            await callback.answer("⚠️ Игрок недоступен", show_alert=True)
            return
        await state.update_data(player_id=player.id, player_name=player.name, player_tag=player.player_tag)
        await state.set_state(ManualContributionStates.entering_points)
        await callback.message.answer(
            f"Выбран игрок: {player.name} ({player.player_tag})\nВведите количество баллов:",
            reply_markup=manual_contribution_cancel_keyboard(),
        )
        await callback.answer()
        return
    if action == "back":
        current = await state.get_state()
        if current == str(ManualContributionStates.entering_points):
            async with app_context.session_maker() as session:
                players = await ManualContributionRepository(session).current_main_clan_players(app_context.config.main_clan_tag)
            await state.set_state(ManualContributionStates.choosing_player)
            await callback.message.answer("Выберите игрока для начисления баллов:", reply_markup=manual_contribution_players_keyboard(players, 0))
        elif current == str(ManualContributionStates.entering_comment):
            await state.set_state(ManualContributionStates.entering_points)
            await callback.message.answer("Введите количество баллов:", reply_markup=manual_contribution_cancel_keyboard())
        elif current == str(ManualContributionStates.choosing_player):
            await state.clear()
            async with app_context.session_maker() as session:
                is_registered = await RegistrationService(session, app_context.clash_client).is_registered(callback.from_user.id)
            await callback.message.answer("Главное меню", reply_markup=main_menu(True, is_registered))
        else:
            await state.set_state(ManualContributionStates.entering_comment)
            await callback.message.answer("Укажите причину начисления баллов:", reply_markup=manual_contribution_cancel_keyboard())
        await callback.answer()
        return
    if action == "confirm":
        if len(parts) != 3 or not parts[2] or len(parts[2]) > 64:
            await callback.answer("⚠️ Некорректная операция", show_alert=True)
            return
        operation_token = parts[2]
        async with app_context.session_maker() as session:
            if await ManualContributionRepository(session).get_by_operation_token(operation_token):
                await callback.answer("Баллы уже были начислены.")
                return
        data_state = await state.get_data()
        if await state.get_state() != str(ManualContributionStates.confirming):
            await callback.answer("Эта операция устарела. Начните начисление заново.", show_alert=True)
            return
        if data_state.get("operation_token") != operation_token:
            await callback.answer("Эта операция устарела. Начните начисление заново.", show_alert=True)
            return
        try:
            async with app_context.session_maker() as session:
                repo = ManualContributionRepository(session)
                player = await repo.get_current_main_clan_player(data_state["player_id"], app_context.config.main_clan_tag)
                if player is None:
                    raise ValueError("player not in main clan")
                created_at = utcnow()
                period = await PeriodService(session).current_cycle(created_at)
                adj = await repo.add_manual_adjustment(
                    player_id=player.id,
                    clan_tag=app_context.config.main_clan_tag,
                    points=int(data_state["points"]),
                    comment=data_state["comment"],
                    created_by_telegram_id=callback.from_user.id,
                    created_by_username=callback.from_user.username,
                    created_at=created_at,
                    operation_token=operation_token,
                )
                await session.commit()
                total_end = max(utcnow(), created_at + timedelta(microseconds=1))
                current_total = await repo.manual_adjustment_total_for_player(
                    player.id,
                    app_context.config.main_clan_tag,
                    period.start,
                    total_end,
                )
                logger.info("Manual contribution adjustment created: player_tag=%s points=%s admin_telegram_id=%s adjustment_id=%s", player.player_tag, adj.points, callback.from_user.id, adj.id)
            await state.clear()
            await callback.message.answer(
                "✅ Баллы начислены\n\n"
                f"Игрок: {data_state['player_name']} ({data_state['player_tag']})\n"
                f"Начислено: +{int(data_state['points'])}\n"
                f"Причина: {data_state['comment']}\n\n"
                f"Ручных баллов игрока за текущий цикл: +{current_total}",
                reply_markup=admin_menu_button_keyboard(),
            )
        except IntegrityError as exc:
            async with app_context.session_maker() as session:
                existing = await ManualContributionRepository(session).get_by_operation_token(operation_token)
            if existing is not None:
                await callback.answer("Баллы уже были начислены.")
                return
            logger.exception("Failed to create manual contribution adjustment", exc_info=exc)
            await callback.message.answer("❌ Не удалось начислить баллы. Попробуйте позже.")
        except Exception:
            logger.exception("Failed to create manual contribution adjustment")
            await callback.message.answer("❌ Не удалось начислить баллы. Попробуйте позже.")
        await callback.answer()
        return


@router.message(ManualContributionStates.entering_points)
async def manual_contribution_points(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    if text == "❌ Отмена":
        await _return_admin_menu(message, state, app_context)
        return
    if text == "⬅️ Назад":
        async with app_context.session_maker() as session:
            players = await ManualContributionRepository(session).current_main_clan_players(app_context.config.main_clan_tag)
        await state.set_state(ManualContributionStates.choosing_player)
        await message.answer("Выберите игрока для начисления баллов:", reply_markup=manual_contribution_players_keyboard(players, 0))
        return
    if not text.isdigit() or not (1 <= int(text) <= 10000):
        await message.answer("Введите целое количество баллов от 1 до 10000.")
        return
    await state.update_data(points=int(text))
    await state.set_state(ManualContributionStates.entering_comment)
    await message.answer("Укажите причину начисления баллов:", reply_markup=manual_contribution_cancel_keyboard())


@router.message(ManualContributionStates.entering_comment)
async def manual_contribution_comment(message: Message, state: FSMContext, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    if text == "❌ Отмена":
        await _return_admin_menu(message, state, app_context)
        return
    if text == "⬅️ Назад":
        await state.set_state(ManualContributionStates.entering_points)
        await message.answer("Введите количество баллов:", reply_markup=manual_contribution_cancel_keyboard())
        return
    if not (3 <= len(text) <= 500):
        await message.answer("Комментарий должен содержать от 3 до 500 символов.")
        return
    operation_token = uuid4().hex
    await state.update_data(comment=text, operation_token=operation_token)
    data = await state.get_data()
    await state.set_state(ManualContributionStates.confirming)
    await message.answer(
        "Подтвердите начисление:\n\n"
        f"Игрок: {data['player_name']} ({data['player_tag']})\n"
        f"Баллы: +{int(data['points'])}\n"
        f"Причина: {text}",
        reply_markup=manual_contribution_confirm_keyboard(operation_token),
    )

@router.message(F.text == "🏰 Столица")
async def capital_raid_report_start(message: Message, app_context: AppContext) -> None:
    try:
        _ensure_admin(app_context, message.from_user.id)
    except PermissionError:
        await message.answer("⛔ Недостаточно прав")
        return
    try:
        async with app_context.session_maker() as session:
            period = await PeriodService(session).current_cycle()
            service = CapitalRaidStatsService(session, app_context.config)
            rows, stats = await service.build_current_cycle_stats(period)
            report = service.format_current_cycle_stats(period, rows, stats)
        await send_long_message(message, report)
    except Exception:
        logger.exception("Failed to build capital raid report")
        await message.answer("⚠️ Не удалось построить отчет по клановой столице. Попробуйте позже.")
