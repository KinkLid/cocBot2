from aiogram.fsm.state import State, StatesGroup


class ManualViolationStates(StatesGroup):
    awaiting_claimed_target_player = State()
    awaiting_claimed_target_attack = State()
