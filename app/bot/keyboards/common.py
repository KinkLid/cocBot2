from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def period_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📆 Текущий цикл", callback_data=f"{prefix}:current")],
            [InlineKeyboardButton(text="📚 Прошлый цикл", callback_data=f"{prefix}:previous")],
            [InlineKeyboardButton(text="🗓 Ввести даты вручную", callback_data=f"{prefix}:custom")],
        ]
    )


def account_keyboard(tags: list[tuple[str, str]], prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"{name} {tag}", callback_data=f"{prefix}:{tag}")] for tag, name in tags]
    )


def admin_sort_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↕️ По порядку клана", callback_data="admin_sort:clan_order")],
            [InlineKeyboardButton(text="⭐ По звёздам", callback_data="admin_sort:stars")],
            [InlineKeyboardButton(text="🏅 По месту", callback_data="admin_sort:place")],
        ]
    )


def manual_contribution_players_keyboard(players: list, page: int, page_size: int = 12) -> InlineKeyboardMarkup:
    total = len(players)
    start = page * page_size
    end = start + page_size
    rows = [
        [InlineKeyboardButton(text=f"{p.clan_rank or i + 1}. {p.player_name}", callback_data=f"manual_contribution:player:{p.player_id}")]
        for i, p in enumerate(players[start:end], start=start)
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"manual_contribution:page:{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"manual_contribution:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="manual_contribution:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def manual_contribution_cancel_keyboard(back: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if back:
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manual_contribution:back")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="manual_contribution:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def manual_contribution_confirm_keyboard(operation_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начислить", callback_data=f"manual_contribution:confirm:{operation_token}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manual_contribution:back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="manual_contribution:cancel")],
    ])

def admin_menu_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Административное меню", callback_data="manual_contribution:admin_menu")]])
