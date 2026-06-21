from aiogram.fsm.state import State, StatesGroup


class ManualContributionStates(StatesGroup):
    choosing_player = State()
    entering_points = State()
    entering_comment = State()
    confirming = State()
    saved = State()
