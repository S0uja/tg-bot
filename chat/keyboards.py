from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


EXIT_CHAT_TEXT = "🚪 Выйти из чата"


def chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=EXIT_CHAT_TEXT)]],
        resize_keyboard=True,
        is_persistent=False,
    )
