from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from main.config import settings


WEIGHT_OPTIONS = ["Очень худая", "Худая", "Нормальная", "Пышная", "Толстая"]
BUST_OPTIONS = [1, 2, 3, 4]
AGE_OPTIONS = ["Молодая", "Милф", "Зрелая"]
HAIRSTYLE_OPTIONS = [
    ("Длинные прямые", "long straight hair, reaching below shoulders, sleek, smooth texture, blunt ends"),
    ("Длинные волнистые", "long wavy hair, reaching below shoulders, loose natural waves"),
    ("Длинные кудрявые", "long curly hair, reaching below shoulders, defined natural curls, voluminous"),
    ("Каре", "short blunt bob haircut, chin-length, straight hair, clean even ends"),
    ("Удлинённое каре", "long bob haircut, shoulder-length, straight hair, blunt ends"),
    ("Каскад", "long layered haircut, multiple visible layers, face-framing layers"),
    ("Пикси", "short pixie haircut, cropped sides and back, longer textured top"),
    ("Высокий хвост", "long hair pulled into a high ponytail, gathered above the crown"),
    ("Низкий хвост", "long hair tied into a low ponytail at the nape of the neck"),
    ("Коса", "long hair styled into a single braid"),
    ("Пучок", "hair gathered into a neat bun at the back of the head"),
]
HAIR_COLOR_OPTIONS = [
    ("Чёрные", "black hair"),
    ("Тёмно-каштановые", "dark brown hair"),
    ("Каштановые", "medium brown chestnut hair"),
    ("Светло-каштановые", "light brown hair"),
    ("Блонд", "blonde hair"),
    ("Платиновый блонд", "platinum blonde hair"),
    ("Рыжие", "natural red hair"),
    ("Тёмно-рыжие", "auburn hair"),
    ("Седые", "gray hair with natural silver tones"),
]


def _button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def character_list(items: list[tuple[int, str]], prefix: str) -> InlineKeyboardMarkup:
    rows = [[_button(f"👤 {name[:45]}", f"{prefix}:{character_id}")] for character_id, name in items]
    rows.append([_button("🏠 Главное меню", "menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def character_actions(character_id: int) -> InlineKeyboardMarkup:
    rows = [
        [_button("⚙️ Параметры", f"editprofile:{character_id}"), _button("✏️ Имя", f"editname:{character_id}")],
    ]
    if settings.feature_images_enabled:
        rows.append([_button("🖼 Референс", f"reference:{character_id}")])
    feature_row = []
    if settings.feature_chat_enabled:
        feature_row.append(_button("💬 Чат", f"charchar:{character_id}"))
    if settings.feature_images_enabled:
        feature_row.append(_button("🎨 Изображение", f"imagefromchar:{character_id}"))
    if feature_row:
        rows.append(feature_row)
    media_row = []
    if settings.feature_videos_enabled:
        media_row.append(_button("🎬 Видео", f"videofromchar:{character_id}"))
    media_row.append(_button("🧬 Дублировать", f"clonecharacter:{character_id}"))
    rows.append(media_row)
    rows.append([_button("🗑 Удалить", f"deletecharacter:{character_id}"), _button("◀️ Персонажи", "menu:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirmation(character_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("✅ Да, удалить", f"confirmdelete:{character_id}"), _button("❌ Отмена", f"character:{character_id}")],
    ])


def character_profile_menu(
    character_id: int,
    *,
    weight: str | None,
    bust: int | None,
    age: str | None,
    hairstyle: str | None,
    hair_color: str | None,
    consistency_strength: str | None = "medium",
    images_enabled: bool | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [_button(f"⚖️ Телосложение: {weight or 'не задано'}", f"profile:weight:{character_id}")],
        [_button(f"💗 Грудь: {bust or 'не задана'}", f"profile:bust:{character_id}")],
        [_button(f"🎂 Возраст: {age or 'не задан'}", f"profile:age:{character_id}")],
        [_button(f"💇 Прическа: {hairstyle or 'не задана'}", f"profile:hair:{character_id}")],
        [_button(f"🎨 Цвет волос: {hair_color or 'не задан'}", f"profile:color:{character_id}")],
        [_button(f"🧬 Consistency: {consistency_strength or 'medium'}", f"profile:consistency:{character_id}")],
    ]
    if settings.feature_images_enabled if images_enabled is None else images_enabled:
        rows.append([_button("🖼 Создать reference sheet", f"reference:{character_id}")])
    rows.append([_button("◀️ К персонажу", f"character:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def weight_profile_choices(character_id: int, current: str | None = None) -> InlineKeyboardMarkup:
    rows = [[_button(("✅ " if value == current else "") + value, f"profileweight:{character_id}:{value}")] for value in WEIGHT_OPTIONS]
    rows.append([_button("◀️ Назад", f"editprofile:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bust_size_choices(character_id: int, current: int | None = None) -> InlineKeyboardMarkup:
    rows = [[_button(("✅ " if value == current else "") + str(value), f"profilebust:{character_id}:{value}") for value in BUST_OPTIONS]]
    rows.append([_button("◀️ Назад", f"editprofile:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def age_category_choices(character_id: int, current: str | None = None) -> InlineKeyboardMarkup:
    rows = [[_button(("✅ " if value == current else "") + value, f"profileage:{character_id}:{value}")] for value in AGE_OPTIONS]
    rows.append([_button("◀️ Назад", f"editprofile:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hairstyle_choices(character_id: int, current: str | None = None) -> InlineKeyboardMarkup:
    rows = [[_button(("✅ " if name == current else "") + name, f"profilehair:{character_id}:{i}")] for i, (name, _) in enumerate(HAIRSTYLE_OPTIONS)]
    rows.append([_button("◀️ Назад", f"editprofile:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hair_color_choices(character_id: int, current: str | None = None) -> InlineKeyboardMarkup:
    rows = [[_button(("✅ " if name == current else "") + name, f"profilehaircolor:{character_id}:{i}")] for i, (name, _) in enumerate(HAIR_COLOR_OPTIONS)]
    rows.append([_button("◀️ Назад", f"editprofile:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("✖️ Отмена", "cancel:menu")],
    ])


def cancel_to_character(character_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("✖️ Отмена", f"cancel:character:{character_id}")],
    ])


def consistency_choices(character_id: int, current: str | None = "medium") -> InlineKeyboardMarkup:
    values = [("Low", "low"), ("Medium", "medium"), ("High", "high"), ("Maximum", "maximum")]
    rows = [[_button(("✅ " if v == current else "") + label, f"profileconsistency:{character_id}:{v}")] for label, v in values]
    rows.append([_button("◀️ Назад", f"editprofile:{character_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
