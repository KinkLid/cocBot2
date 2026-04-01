from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool, is_registered: bool) -> ReplyKeyboardMarkup:
    rows = []
    if not is_registered:
        rows.append([KeyboardButton(text="📝 Регистрация")])
    rows.extend(
        [
            [KeyboardButton(text="🔗 Ссылка на чат клана")],
            [KeyboardButton(text="📊 Моя статистика")],
        ]
    )
    if is_admin:
        rows.extend(
            [
                [KeyboardButton(text="👥 Список игроков")],
                [KeyboardButton(text="📈 Статистика клана")],
                [KeyboardButton(text="📦 Выгрузка JSON")],
                [KeyboardButton(text="🧪 Dev-вклад")],
                [KeyboardButton(text="✏️ Обновить ссылку на чат")],
                [KeyboardButton(text="📜 Последние логи")],
                [KeyboardButton(text="🗂 Скачать лог-файл")],
            ]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
