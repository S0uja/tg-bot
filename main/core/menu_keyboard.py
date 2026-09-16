from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from main.config import settings


def menu() -> InlineKeyboardMarkup:
    rows = []
    if settings.feature_characters_enabled:
        rows.append([InlineKeyboardButton(text="👤 Создать персонажа", callback_data="menu:create")])
        rows.append([InlineKeyboardButton(text="📚 Мои персонажи", callback_data="menu:list")])
    if settings.feature_chat_enabled:
        rows.append([InlineKeyboardButton(text="💬 Чат", callback_data="menu:chat")])
    if settings.feature_images_enabled:
        rows.append([InlineKeyboardButton(text="🎨 Создать изображение", callback_data="menu:image")])
    if settings.feature_videos_enabled:
        rows.append([InlineKeyboardButton(text="🎬 Создать видео", callback_data="menu:video")])
    if settings.feature_library_enabled and settings.feature_images_enabled:
        rows.append([InlineKeyboardButton(text="📚 Библиотека", callback_data="menu:library")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
