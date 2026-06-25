from aiogram.fsm.state import State, StatesGroup


class AdminPlayerLinkStates(StatesGroup):
    waiting_for_telegram_id = State()
    choosing_player = State()
