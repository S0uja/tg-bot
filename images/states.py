from aiogram.fsm.state import State, StatesGroup


class ImageCreation(StatesGroup):
    character = State()
    prompt = State()


class AnimationCreation(StatesGroup):
    prompt = State()
