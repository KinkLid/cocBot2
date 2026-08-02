from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool, is_registered: bool) -> ReplyKeyboardMarkup:
    rows = []
    if not is_registered:
        rows.append([KeyboardButton(text="📝 Регистрация")])
    rows.extend(
        [
            [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="📋 Мой вклад")],
            [KeyboardButton(text="🏆 Общий вклад"), KeyboardButton(text="🔗 Ссылка на чат клана")],
        ]
    )
    if is_admin:
        rows.append([KeyboardButton(text="🛡 Админка")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
    )


def violation_reset_amount_keyboard(
    active_count: int,
) -> ReplyKeyboardMarkup:
    amount = min(max(active_count, 1), 3)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=str(value)) for value in range(1, amount + 1)],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )
