from aiogram.fsm.state import State, StatesGroup


class ContributionBreakdownStates(StatesGroup):
    awaiting_player_number = State()
    awaiting_my_contribution_player_number = State()
