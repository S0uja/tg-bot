from __future__ import annotations

import json
import re
from typing import Any

WEIGHT_OPTIONS = {"Очень худая", "Худая", "Нормальная", "Пышная", "Толстая"}
BUST_OPTIONS = {1, 2, 3, 4}
AGE_OPTIONS = {"Молодая", "Милф", "Зрелая"}
HAIRSTYLE_OPTIONS = {
    "Длинные прямые", "Длинные волнистые", "Длинные кудрявые", "Каре",
    "Удлинённое каре", "Каскад", "Пикси", "Высокий хвост", "Низкий хвост",
    "Коса", "Пучок",
}
HAIR_COLOR_OPTIONS = {
    "Чёрные", "Тёмно-каштановые", "Каштановые", "Светло-каштановые",
    "Блонд", "Платиновый блонд", "Рыжие", "Тёмно-рыжие", "Седые",
}


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() in {"unknown", "unclear", "not visible", "not_visible", "null", "none"}:
        return None
    return value


def _match_option(value: Any, options: set[str], aliases: dict[str, str] | None = None) -> str | None:
    value = _clean(value)
    if value is None:
        return None
    if value in options:
        return value
    normalized = value.casefold().replace("ё", "е")
    for option in options:
        if option.casefold().replace("ё", "е") == normalized:
            return option
    if aliases:
        for key, result in aliases.items():
            if key in normalized:
                return result
    return None


def _normalize_bust(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number in BUST_OPTIONS else None


def normalize_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the five profile parameters returned by Vision LLM.

    Character creation intentionally does not build or store a free-form face
    description. The reference image itself is the visual identity source.
    """
    params = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else raw

    weight = _match_option(params.get("weight_profile"), WEIGHT_OPTIONS, {
        "очень худа": "Очень худая", "very slim": "Очень худая", "slim": "Худая",
        "skinny": "Худая", "норм": "Нормальная", "average": "Нормальная", "normal": "Нормальная",
        "curvy": "Пышная", "plus": "Пышная", "пыш": "Пышная", "heavy": "Толстая",
    })
    age = _match_option(params.get("age_category"), AGE_OPTIONS, {
        "молод": "Молодая", "young": "Молодая", "20s": "Молодая",
        "милф": "Милф", "mature": "Милф", "30": "Милф", "40": "Милф",
        "зрел": "Зрелая", "older": "Зрелая", "55": "Зрелая", "60": "Зрелая",
    })
    hairstyle = _match_option(params.get("hairstyle"), HAIRSTYLE_OPTIONS, {
        "long straight": "Длинные прямые", "длинн.*прям": "Длинные прямые",
        "long wavy": "Длинные волнистые", "длинн.*волнист": "Длинные волнистые",
        "long curly": "Длинные кудрявые", "длинн.*кудр": "Длинные кудрявые",
        "bob": "Каре", "каре": "Каре", "long bob": "Удлинённое каре", "lob": "Удлинённое каре",
        "layer": "Каскад", "каскад": "Каскад", "pixie": "Пикси", "пикси": "Пикси",
        "high pony": "Высокий хвост", "высок.*хвост": "Высокий хвост",
        "low pony": "Низкий хвост", "низк.*хвост": "Низкий хвост",
        "braid": "Коса", "кос": "Коса", "bun": "Пучок", "пуч": "Пучок",
    })
    if hairstyle is None:
        raw_hair = _clean(params.get("hairstyle"))
        if raw_hair:
            text = raw_hair.casefold().replace("ё", "е")
            if ("long" in text and "straight" in text) or ("длин" in text and "прям" in text):
                hairstyle = "Длинные прямые"
            elif ("long" in text and "wavy" in text) or ("длин" in text and "волнист" in text):
                hairstyle = "Длинные волнистые"
            elif ("long" in text and "curly" in text) or ("длин" in text and "кудр" in text):
                hairstyle = "Длинные кудрявые"
            elif "long bob" in text or "lob" in text or "удлин" in text:
                hairstyle = "Удлинённое каре"
            elif "bob" in text or "каре" in text:
                hairstyle = "Каре"
            elif "layer" in text or "каскад" in text:
                hairstyle = "Каскад"
            elif "pixie" in text or "пикси" in text:
                hairstyle = "Пикси"
            elif "high pony" in text or ("высок" in text and "хвост" in text):
                hairstyle = "Высокий хвост"
            elif "low pony" in text or ("низк" in text and "хвост" in text):
                hairstyle = "Низкий хвост"
            elif "braid" in text or "кос" in text:
                hairstyle = "Коса"
            elif "bun" in text or "пуч" in text:
                hairstyle = "Пучок"

    hair_color = _match_option(params.get("hair_color"), HAIR_COLOR_OPTIONS, {
        "black": "Чёрные", "черн": "Чёрные", "dark brown": "Тёмно-каштановые", "темно-каштан": "Тёмно-каштановые",
        "chestnut": "Каштановые", "medium brown": "Каштановые", "каштан": "Каштановые",
        "light brown": "Светло-каштановые", "светло-каштан": "Светло-каштановые",
        "platinum": "Платиновый блонд", "платин": "Платиновый блонд", "blonde": "Блонд", "блонд": "Блонд",
        "red": "Рыжие", "рыж": "Рыжие", "auburn": "Тёмно-рыжие", "темно-рыж": "Тёмно-рыжие",
        "gray": "Седые", "grey": "Седые", "сер": "Седые",
    })

    confidence = raw.get("confidence") if isinstance(raw.get("confidence"), dict) else {}
    return {
        "weight_profile": weight,
        "bust_size": _normalize_bust(params.get("bust_size")),
        "age_category": age,
        "hairstyle": hairstyle,
        "hair_color": hair_color,
        "confidence": {
            key: confidence.get(key) for key in
            ("weight_profile", "bust_size", "age_category", "hairstyle", "hair_color")
            if key in confidence
        },
    }

