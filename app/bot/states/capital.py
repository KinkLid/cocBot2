from aiogram.fsm.state import State, StatesGroup


class CapitalRaidStates(StatesGroup):
    awaiting_capital_raid_count = State()
