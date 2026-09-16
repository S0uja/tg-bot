from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from main.config import settings


def choices(prefix: str, items: list[tuple[str, str]], columns: int = 2) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{value}") for label, value in items]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    rows.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_actions(character_id: int, generation_id: int, favorite: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if settings.feature_videos_enabled:
        rows.append([InlineKeyboardButton(text="🎬 Анимировать", callback_data=f"image_animate:{character_id}:{generation_id}")])
    action_row = [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"image_change:{character_id}:{generation_id}")]
    if settings.feature_library_enabled:
        action_row.append(InlineKeyboardButton(text=("⭐ Убрать" if favorite else "⭐ В избранное"), callback_data=f"favorite:{generation_id}"))
    rows.append(action_row)
    if settings.feature_images_enabled:
        rows.append([InlineKeyboardButton(text="🎨 Новое изображение", callback_data=f"imagefromchar:{character_id}")])
    rows.append([InlineKeyboardButton(text="👤 Персонаж", callback_data=f"character:{character_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def video_actions(character_id: int, generation_id: int, favorite: bool = False) -> InlineKeyboardMarkup:
    rows = []
    action_row = [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"video_repeat:{character_id}:{generation_id}")]
    if settings.feature_videos_enabled:
        action_row.append(InlineKeyboardButton(text="➕ Продолжить", callback_data=f"video_continue:{character_id}:{generation_id}"))
    rows.append(action_row)
    if settings.feature_library_enabled:
        rows.append([InlineKeyboardButton(text=("⭐ Убрать" if favorite else "⭐ В избранное"), callback_data=f"favorite:{generation_id}")])
    if settings.feature_videos_enabled:
        rows.append([InlineKeyboardButton(text="🎬 Ещё видео", callback_data=f"videofromchar:{character_id}")])
    rows.append([InlineKeyboardButton(text="👤 Персонаж", callback_data=f"character:{character_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_input() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖️ Отмена", callback_data="cancel:menu")],
    ])
