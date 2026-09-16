from aiogram.fsm.state import State, StatesGroup


class VideoCreation(StatesGroup):
    character = State()
    description = State()
