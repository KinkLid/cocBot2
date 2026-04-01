from aiogram.fsm.state import State, StatesGroup


class PeriodSelectionStates(StatesGroup):
    waiting_for_custom_start = State()
    waiting_for_custom_end = State()
