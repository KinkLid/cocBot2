from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.states.registration import RegistrationStates
from app.container import AppContext
from app.services.registration import RegistrationService

router = Router(name="registration")


@router.message(F.text == "📝 Регистрация")
async def start_registration(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(RegistrationStates.waiting_for_player_tag)
    await message.answer("Введите игровой тег аккаунта, например #GJ0C2GUGJ")


@router.message(RegistrationStates.waiting_for_player_tag)
async def registration_player_tag(message: Message, state: FSMContext) -> None:
    await state.update_data(player_tag=message.text.strip())
    await state.set_state(RegistrationStates.waiting_for_player_token)
    await message.answer("Теперь введите player token из игры")


@router.message(RegistrationStates.waiting_for_player_token)
async def registration_player_token(message: Message, state: FSMContext, app_context: AppContext) -> None:
    data = await state.get_data()
    async with app_context.session_maker() as session:
        service = RegistrationService(session, app_context.clash_client)
        try:
            result = await service.register_player(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                player_tag=data["player_tag"],
                player_token=message.text.strip(),
            )
        except ValueError:
            await message.answer("❌ Регистрация не удалась: неверный player token")
            return
    await state.clear()
    suffix = "Аккаунт уже был привязан." if result.already_linked else "Аккаунт успешно привязан."
    await message.answer(f"✅ {result.player_name} {result.player_tag}\n{suffix}")
