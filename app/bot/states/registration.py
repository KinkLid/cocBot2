from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_for_player_tag = State()
    waiting_for_player_token = State()
