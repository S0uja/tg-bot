from aiogram.fsm.state import State, StatesGroup


class CharacterCreation(StatesGroup):
    photo = State()
    name = State()


class CharacterEdit(StatesGroup):
    value = State()


class CharacterProfileEdit(StatesGroup):
    weight = State()
    bust = State()
    age = State()
    hairstyle = State()
    hair_color = State()
