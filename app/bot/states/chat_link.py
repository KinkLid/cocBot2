from aiogram.fsm.state import State, StatesGroup


class ChatLinkStates(StatesGroup):
    waiting_for_chat_link = State()
