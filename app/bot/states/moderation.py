from aiogram.fsm.state import State, StatesGroup


class AdminModerationStates(StatesGroup):
    waiting_unmute_user_id = State()
