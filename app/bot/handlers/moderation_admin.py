from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.admin_panel import admin_panel_keyboard, confirm_keyboard, moderation_keyboard
from app.bot.keyboards.main import back_keyboard
from app.bot.states.moderation import AdminModerationStates
from app.container import AppContext
from app.services.chat_moderation_mutes import ChatModerationMuteService

router = Router(name="moderation_admin")


def _ensure_admin(app_context: AppContext, telegram_id: int) -> bool:
    return app_context.auth_service.is_admin(telegram_id)


async def _deny_callback(callback: CallbackQuery) -> None:
    await callback.answer("Недостаточно прав", show_alert=True)


def _display_name(row) -> str:
    if row.display_name:
        return row.display_name
    if row.username:
        return f"@{row.username}"
    return str(row.telegram_user_id)


def _with_manual_button(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows = list(markup.inline_keyboard)
    rows.insert(0, [InlineKeyboardButton(text="🔢 Снять мут по Telegram ID", callback_data="admin_moderation:manual")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _active_mute_entities(app_context: AppContext) -> list[tuple[str, str]]:
    async with app_context.session_maker() as session:
        rows = await ChatModerationMuteService(session).active_mutes(
            chat_ids=app_context.config.text_moderation.chat_ids,
            now=datetime.now(UTC),
        )
    return [
        (
            str(row.id),
            f"🔇 {_display_name(row)} · до {row.muted_until:%d.%m %H:%M UTC}",
        )
        for row in rows
    ]


async def _show_moderation(callback: CallbackQuery, app_context: AppContext, *, page: int = 0) -> None:
    entities = await _active_mute_entities(app_context)
    text = "🛡 <b>Модерация чата</b>\n\n"
    if entities:
        text += "Выберите пользователя, чтобы снять мут."
    else:
        text += "Активных мутов, сохранённых ботом, сейчас нет."
    markup = _with_manual_button(moderation_keyboard(entities, page=page))
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)


async def _restore_permissions(bot: Bot, *, chat_id: int, telegram_user_id: int) -> None:
    chat = await bot.get_chat(chat_id)
    permissions = chat.permissions
    if permissions is None:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=telegram_user_id,
        permissions=permissions,
    )


@router.callback_query(F.data == "admin_moderation:list")
async def moderation_list(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    await state.clear()
    await _show_moderation(callback, app_context)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_moderation:page:"))
async def moderation_page(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    page = max(0, int((callback.data or "").rsplit(":", 1)[1]))
    await _show_moderation(callback, app_context, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_moderation:select:"))
async def moderation_select(callback: CallbackQuery, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    mute_id = int((callback.data or "").rsplit(":", 1)[1])
    async with app_context.session_maker() as session:
        row = await ChatModerationMuteService(session).get(mute_id)
    if row is None:
        await callback.answer("Этот мут уже отсутствует", show_alert=True)
        return
    await callback.message.edit_text(
        f"Снять мут с {_display_name(row)}?\n\nTelegram ID: <code>{row.telegram_user_id}</code>",
        reply_markup=confirm_keyboard(
            f"admin_moderation:confirm:{row.id}",
            "admin_moderation:list",
            confirm_text="🔊 Снять мут",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_moderation:confirm:"))
async def moderation_confirm(callback: CallbackQuery, app_context: AppContext, bot: Bot) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    mute_id = int((callback.data or "").rsplit(":", 1)[1])
    async with app_context.session_maker() as session:
        service = ChatModerationMuteService(session)
        row = await service.get(mute_id)
        if row is None:
            await callback.answer("Этот мут уже отсутствует", show_alert=True)
            return
        await _restore_permissions(
            bot,
            chat_id=row.chat_id,
            telegram_user_id=row.telegram_user_id,
        )
        name = _display_name(row)
        await service.remove(row.id)
        await session.commit()
    await callback.message.edit_text(
        f"✅ Мут снят: {name}",
        reply_markup=admin_panel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_moderation:manual")
async def moderation_manual(callback: CallbackQuery, state: FSMContext, app_context: AppContext) -> None:
    if not _ensure_admin(app_context, callback.from_user.id):
        await _deny_callback(callback)
        return
    if len(app_context.config.text_moderation.chat_ids) != 1:
        await callback.answer("Ручное снятие по ID доступно, когда настроен один чат модерации", show_alert=True)
        return
    await state.set_state(AdminModerationStates.waiting_unmute_user_id)
    await callback.message.answer(
        "Отправьте Telegram ID пользователя, с которого нужно снять мут.",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@router.message(AdminModerationStates.waiting_unmute_user_id)
async def moderation_manual_user_id(
    message: Message,
    state: FSMContext,
    app_context: AppContext,
    bot: Bot,
) -> None:
    if not _ensure_admin(app_context, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Недостаточно прав")
        return
    text = (message.text or "").strip()
    if text == "⬅️ Назад":
        await state.clear()
        await message.answer("🛡 Модерация отменена.", reply_markup=admin_panel_keyboard())
        return
    try:
        telegram_user_id = int(text)
        if telegram_user_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Нужен числовой Telegram ID пользователя.")
        return

    chat_id = app_context.config.text_moderation.chat_ids[0]
    await _restore_permissions(bot, chat_id=chat_id, telegram_user_id=telegram_user_id)
    async with app_context.session_maker() as session:
        await ChatModerationMuteService(session).remove_for_user(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
        )
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Мут снят с Telegram ID <code>{telegram_user_id}</code>.",
        reply_markup=admin_panel_keyboard(),
    )
