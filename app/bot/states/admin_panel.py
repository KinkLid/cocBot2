from aiogram.fsm.state import State, StatesGroup


class AdminPanelStates(StatesGroup):
    waiting_custom_period_start = State()
    waiting_custom_period_end = State()
    waiting_adjustment_points = State()
    waiting_adjustment_comment = State()
