from aiogram.fsm.state import State, StatesGroup


class CharacterChat(StatesGroup):
    chatting = State()
    # Backward-compatible alias for older pose/test handlers.
    active = State()
