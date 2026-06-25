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
            [KeyboardButton(text="🏆 Общий вклад")],
            [KeyboardButton(text="📋 Мой вклад")],
        ]
    )
    if is_admin:
        rows.extend(
            [
                [KeyboardButton(text="👥 Список игроков")],
                [KeyboardButton(text="🔗 Привязать игрока")],
                [KeyboardButton(text="🧾 Разбор вклада")],
                [KeyboardButton(text="📈 Статистика клана")],
                [KeyboardButton(text="📦 Выгрузка JSON")],
                [KeyboardButton(text="🏰 Столица"), KeyboardButton(text="🧪 Dev вклад в столицу"), KeyboardButton(text="🧪 Dev-донаты")],
                [KeyboardButton(text="🚨 Нарушения"), KeyboardButton(text="♻️ Сбросить счетчик нарушений")],
                [KeyboardButton(text="🚩 Чужой флажок"), KeyboardButton(text="➕ Начислить баллы")],
                [KeyboardButton(text="✏️ Обновить ссылку на чат")],
                [KeyboardButton(text="📜 Последние логи")],
                [KeyboardButton(text="🗂 Скачать лог-файл")],
            ]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
    )
