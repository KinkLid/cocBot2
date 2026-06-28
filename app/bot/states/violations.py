from aiogram.fsm.state import State, StatesGroup


class ViolationStates(StatesGroup):
    awaiting_violation_player_number = State()
    awaiting_all_violations_player_number = State()
    awaiting_reset_player_number = State()
    awaiting_reset_amount = State()
