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
