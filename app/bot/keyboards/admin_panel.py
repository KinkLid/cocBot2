from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


REPORT_LABELS = {
    "clan_stats": "📈 Статистика клана",
    "contribution": "🏆 Общий вклад",
    "breakdown": "🧾 Разбор вклада",
    "violations": "🚨 Нарушения",
    "donations": "🎁 Донаты",
    "capital": "🏰 Столица",
    "capital_score": "🏅 Вклад в столицу",
    "export": "📦 Выгрузка JSON",
    "adjustments": "🧮 История баллов",
}


def _controls(back_to: str = "root") -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_panel:{back_to}"),
            InlineKeyboardButton(text="🏠 Админка", callback_data="admin_panel:root"),
        ],
        [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_panel:close")],
    ]


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ Война", callback_data="admin_panel:war"),
                InlineKeyboardButton(text="👥 Игроки", callback_data="admin_panel:players"),
            ],
            [
                InlineKeyboardButton(text="🚨 Нарушения", callback_data="admin_panel:violations"),
                InlineKeyboardButton(text="🏆 Вклад", callback_data="admin_panel:contribution"),
            ],
            [
                InlineKeyboardButton(text="🏰 Столица", callback_data="admin_panel:capital"),
                InlineKeyboardButton(text="📊 Отчёты", callback_data="admin_panel:reports"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Система", callback_data="admin_panel:system"),
                InlineKeyboardButton(text="🔐 Безопасность", callback_data="admin_panel:security"),
            ],
            [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_panel:close")],
        ]
    )


def war_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Текущая война", callback_data="admin_action:current_war")],
            [InlineKeyboardButton(text="🗡 Кто не атаковал", callback_data="admin_action:missing_attacks")],
            [InlineKeyboardButton(text="🔄 Синхронизировать сейчас", callback_data="admin_action:sync_confirm")],
            *_controls(),
        ]
    )


def players_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Список игроков", callback_data="admin_action:players_list")],
            [InlineKeyboardButton(text="👤 Непривязанные", callback_data="admin_action:unlinked_players")],
            [InlineKeyboardButton(text="🔗 Все привязки", callback_data="admin_action:all_links")],
            [
                InlineKeyboardButton(text="➕ Привязать", callback_data="admin_action:link_player"),
                InlineKeyboardButton(text="➖ Отвязать", callback_data="admin_action:unlink_players"),
            ],
            [InlineKeyboardButton(text="🚪 Выходы и возвраты", callback_data="admin_action:membership_events")],
            *_controls(),
        ]
    )


def violations_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚨 Отчёт по нарушениям", callback_data="admin_report:violations")],
            [
                InlineKeyboardButton(text="♻️ Списать", callback_data="admin_action:reduce_violations"),
                InlineKeyboardButton(text="↩️ Вернуть", callback_data="admin_action:restore_violations"),
            ],
            [
                InlineKeyboardButton(text="🚩 Поставить ручное", callback_data="admin_action:add_manual_violation"),
                InlineKeyboardButton(text="✅ Снять ручное", callback_data="admin_action:remove_manual_violations"),
            ],
            [InlineKeyboardButton(text="🔄 Пересчитать текущий цикл", callback_data="admin_action:recalculate")],
            *_controls(),
        ]
    )


def contribution_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏆 Общий вклад", callback_data="admin_report:contribution")],
            [InlineKeyboardButton(text="🧾 Разбор вклада", callback_data="admin_report:breakdown")],
            [InlineKeyboardButton(text="🎁 Донаты", callback_data="admin_report:donations")],
            [InlineKeyboardButton(text="🧮 История ручных баллов", callback_data="admin_report:adjustments")],
            [
                InlineKeyboardButton(text="➕ Начислить", callback_data="admin_points:start:add"),
                InlineKeyboardButton(text="➖ Снять", callback_data="admin_points:start:subtract"),
            ],
            *_controls(),
        ]
    )


def capital_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏰 Статистика столицы", callback_data="admin_report:capital")],
            [InlineKeyboardButton(text="🏅 Вклад в столицу", callback_data="admin_report:capital_score")],
            *_controls(),
        ]
    )


def reports_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Статистика клана", callback_data="admin_report:clan_stats")],
            [InlineKeyboardButton(text="📦 Выгрузка JSON", callback_data="admin_report:export")],
            *_controls(),
        ]
    )


def system_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🩺 Состояние бота", callback_data="admin_action:bot_status")],
            [InlineKeyboardButton(text="💬 Переписки с ботом", callback_data="admin_action:conversations")],
            [
                InlineKeyboardButton(text="📜 Последние логи", callback_data="admin_action:logs"),
                InlineKeyboardButton(text="⚠️ Только ошибки", callback_data="admin_action:error_logs"),
            ],
            [InlineKeyboardButton(text="🗂 Скачать лог", callback_data="admin_action:download_log")],
            [
                InlineKeyboardButton(text="✏️ Изменить чат", callback_data="admin_action:update_chat"),
                InlineKeyboardButton(text="🗑 Удалить чат", callback_data="admin_action:clear_chat_confirm"),
            ],
            *_controls(),
        ]
    )


def security_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Состояние защиты", callback_data="admin_action:security_status")],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_action:security_status")],
            *_controls(),
        ]
    )


def period_keyboard(report: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📆 Текущий цикл", callback_data=f"admin_period:{report}:current")],
            [InlineKeyboardButton(text="📚 Прошлый цикл", callback_data=f"admin_period:{report}:previous")],
            [InlineKeyboardButton(text="🗂 Выбрать конкретный цикл", callback_data=f"admin_period:{report}:cycles")],
            [InlineKeyboardButton(text="♾ За всё время", callback_data=f"admin_period:{report}:all")],
            [InlineKeyboardButton(text="🗓 Указать даты", callback_data=f"admin_period:{report}:custom")],
            *_controls(_report_section(report)),
        ]
    )


def cycles_keyboard(report: str, cycles: Sequence, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    page = max(0, page)
    start = page * page_size
    end = start + page_size
    rows: list[list[InlineKeyboardButton]] = []
    for index, period in enumerate(cycles[start:end], start=start):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{period.start:%d.%m.%Y} — {period.end:%d.%m.%Y}",
                    callback_data=f"admin_cycle:{report}:{index}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_cycles:{report}:{page - 1}"))
    if end < len(cycles):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_cycles:{report}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ К периодам", callback_data=f"admin_report:{report}")])
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_panel:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def selectable_players_keyboard(prefix: str, players: Sequence, page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    page = max(0, page)
    start = page * page_size
    end = start + page_size
    rows: list[list[InlineKeyboardButton]] = []
    for player in players[start:end]:
        player_id = getattr(player, "player_id", getattr(player, "id", None))
        player_name = getattr(player, "player_name", getattr(player, "name", str(player_id)))
        rank = getattr(player, "clan_rank", getattr(player, "current_clan_rank", None))
        label = f"{rank}. {player_name}" if rank is not None else player_name
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=f"{prefix}:player:{player_id}")])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:page:{page - 1}"))
    if end < len(players):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def entities_keyboard(prefix: str, entities: Sequence[tuple[str, str]], page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    page = max(0, page)
    start = page * page_size
    end = start + page_size
    rows = [
        [InlineKeyboardButton(text=label[:60], callback_data=f"{prefix}:select:{entity_id}")]
        for entity_id, label in entities[start:end]
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:page:{page - 1}"))
    if end < len(entities):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(confirm_data: str, cancel_data: str, *, confirm_text: str = "✅ Подтвердить") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=confirm_text, callback_data=confirm_data)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_data)],
        ]
    )


def amount_keyboard(prefix: str, max_amount: int = 3) -> InlineKeyboardMarkup:
    max_amount = min(max(max_amount, 1), 3)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(value), callback_data=f"{prefix}:{value}") for value in range(1, max_amount + 1)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel:violations")],
        ]
    )


def _report_section(report: str) -> str:
    if report in {"contribution", "breakdown", "donations", "adjustments"}:
        return "contribution"
    if report in {"capital", "capital_score"}:
        return "capital"
    if report == "violations":
        return "violations"
    return "reports"
