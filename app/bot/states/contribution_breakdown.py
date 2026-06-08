from aiogram.fsm.state import State, StatesGroup


class ContributionBreakdownStates(StatesGroup):
    awaiting_player_number = State()
