from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.container import AppContext
from app.services.conversation_history import ConversationHistoryService, ConversationPage, ConversationUser

router = Router(name="conversation_admin")
_USERS_PER_PAGE = 8
_MAX_RECORD_TEXT = 420


def _is_admin(app_context: AppContext, telegram_id: int) -> bool:
    return app_context.auth_service.is_admin(telegram_id)


def _service(app_context: AppContext) -> ConversationHistoryService:
    return ConversationHistoryService(app_context.settings.conversation_log_dir)


def _short(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _user_label(user: ConversationUser) -> str:
    parts = [user.display_name]
    if user.username and f"@{user.username}" not in user.display_name:
        parts.append(f"@{user.username}")
    parts.append(str(user.telegram_id))
    return _short(" · ".join(parts), 58)


def _users_keyboard(users: list[ConversationUser], page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(users) + _USERS_PER_PAGE - 1) // _USERS_PER_PAGE)
    page = min(max(page, 0), total_pages - 1)
    start = page * _USERS_PER_PAGE
    end = start + _USERS_PER_PAGE
    rows = [
        [
            InlineKeyboardButton(
                text=_user_label(user),
                callback_data=f"conversation:view:{user.telegram_id}:0",
            )
        ]
        for user in users[start:end]
    ]
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️", callback_data=f"conversation:users:{page - 1}"))
    if page + 1 < total_pages:
        navigation.append(InlineKeyboardButton(text="➡️", callback_data=f"conversation:users:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data="conversation:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _history_keyboard(page: ConversationPage) -> InlineKeyboardMarkup:
    navigation: list[InlineKeyboardButton] = []
    if page.page + 1 < page.total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️ Старее",
                callback_data=f"conversation:view:{page.user.telegram_id}:{page.page + 1}",
            )
        )
    if page.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="Новее ➡️",
                callback_data=f"conversation:view:{page.user.telegram_id}:{page.page - 1}",
            )
        )
    rows: list[list[InlineKeyboardButton]] = []
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="👥 К списку", callback_data="conversation:users:0")])
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data="conversation:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_time(value: Any) -> str:
    if not isinstance(value, str):
        return "время неизвестно"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _short(value, 24)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.strftime("%d.%m.%Y %H:%M UTC")


def _record_text(record: dict[str, Any]) -> str:
    state = record.get("fsm_state")
    if record.get("secret_redacted") or (isinstance(state, str) and state.endswith(":waiting_for_player_token")):
        return "[секрет скрыт]"

    text = record.get("text")
    if isinstance(text, str) and text.strip():
        if record.get("content_type") == "callback_query":
            return f"Нажатие кнопки: {text.strip()}"
        return text.strip()

    media = record.get("media")
    if isinstance(media, dict):
        kind = media.get("kind") or "вложение"
        file_name = media.get("file_name")
        return f"[{kind}]" + (f" {file_name}" if isinstance(file_name, str) and file_name else "")
    if record.get("contact"):
        return "[контакт]"
    if record.get("location"):
        return "[геолокация]"

    method = record.get("bot_method")
    if method in {"DeleteMessage", "DeleteMessages"}:
        return "[бот удалил сообщение]"
    content_type = record.get("content_type")
    return f"[{content_type}]" if isinstance(content_type, str) and content_type else "[событие без текста]"


def _format_history(page: ConversationPage) -> str:
    user = page.user
    username = f"\nUsername: @{html.escape(user.username)}" if user.username else ""
    header = (
        f"💬 <b>{html.escape(user.display_name)}</b>"
        f"\nTelegram ID: <code>{user.telegram_id}</code>{username}"
        f"\nСтраница {page.page + 1}/{page.total_pages} · записей: {page.total_records}"
    )
    blocks = [header]
    for record in page.records:
        direction = "👤" if record.get("direction") == "incoming" else "🤖"
        timestamp = html.escape(_format_time(record.get("recorded_at")))
        text = html.escape(_short(_record_text(record), _MAX_RECORD_TEXT))
        blocks.append(f"{direction} <b>{timestamp}</b>\n{text}")
    return "\n\n".join(blocks)


async def _deny_message(message: Message) -> None:
    await message.answer("⛔ Недостаточно прав")


async def _deny_callback(callback: CallbackQuery) -> None:
    await callback.answer("Недостаточно прав", show_alert=True)


@router.message(F.text == "💬 Переписки с ботом")
async def conversation_users(message: Message, app_context: AppContext) -> None:
    if not _is_admin(app_context, message.from_user.id):
        await _deny_message(message)
        return
    if not app_context.settings.conversation_log_enabled:
        await message.answer("⚠️ Журналирование переписок выключено в конфигурации.")
        return
    users = _service(app_context).list_users()
    if not users:
        await message.answer("Переписок пока нет.")
        return
    await message.answer(
        "💬 <b>Переписки с ботом</b>\n\nВыберите пользователя:",
        reply_markup=_users_keyboard(users, 0),
    )


@router.callback_query(F.data.startswith("conversation:users:"))
async def conversation_users_page(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _is_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        page = 0
    users = _service(app_context).list_users()
    if not users:
        await callback.message.edit_text("Переписок пока нет.")
        await callback.answer()
        return
    total_pages = max(1, (len(users) + _USERS_PER_PAGE - 1) // _USERS_PER_PAGE)
    page = min(max(page, 0), total_pages - 1)
    await callback.message.edit_text(
        f"💬 <b>Переписки с ботом</b>\n\nВыберите пользователя · страница {page + 1}/{total_pages}:",
        reply_markup=_users_keyboard(users, page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("conversation:view:"))
async def conversation_view(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _is_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    parts = (callback.data or "").split(":")
    try:
        telegram_id = int(parts[2])
        page_number = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    page = _service(app_context).get_page(telegram_id, page_number)
    if page is None:
        await callback.answer("Переписка не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        _format_history(page),
        reply_markup=_history_keyboard(page),
    )
    await callback.answer()


@router.callback_query(F.data == "conversation:close")
async def conversation_close(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _is_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        await callback.answer("Не удалось удалить сообщение", show_alert=True)
        return
    await callback.answer()
