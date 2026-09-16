from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def library_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕘 Последние", callback_data="library:recent")],
        [InlineKeyboardButton(text="⭐ Избранное", callback_data="library:favorites")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:open")],
    ])


def library_items(items) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        icon = "🖼" if item.kind.value == "image" else "🎬"
        star = "⭐ " if item.favorite else ""
        label = f"{icon} {star}#{item.id} {item.prompt[:42].replace(chr(10), ' ')}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"library:item:{item.id}")])
    rows.append([InlineKeyboardButton(text="⭐ Избранное", callback_data="library:favorites")])
    rows.append([InlineKeyboardButton(text="🕘 Последние", callback_data="library:recent")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
