from __future__ import annotations

from io import BytesIO
from pathlib import Path

from aiogram import Router, types
from aiogram.filters import Command
from PIL import Image, ImageDraw, ImageFont

from main.core.context import TelegramContext
from main.domain.errors import AppError
from main.domain.models import Character, ImagePromptContext
from main.prompts.service import (
    AGE_PROMPTS,
    BUST_PROMPTS,
    HAIR_COLOR_PROMPTS,
    HAIRSTYLE_PROMPTS,
    WEIGHT_PROMPTS,
    profile_prompt,
)


TESTS = {
    "body": ("Телосложение", list(WEIGHT_PROMPTS)),
    "boobs": ("Грудь", [1, 2, 3, 4]),
    "age": ("Возраст", list(AGE_PROMPTS)),
    "hair": ("Прическа", list(HAIRSTYLE_PROMPTS)),
    "color": ("Цвет волос", list(HAIR_COLOR_PROMPTS)),
    "consistency": ("Consistency", ["low", "medium", "high", "maximum"]),
}


SCENE = (
    "photorealistic full-body portrait of one adult woman standing naturally, "
    "head to toe visible, simple neutral studio background, natural soft lighting, "
    "fitted neutral casual clothing, front three-quarter camera view"
)


def _font(size: int):
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _make_sheet(items: list[tuple[str, bytes]], cell_width: int = 256, cell_height: int = 416) -> bytes:
    columns = 3
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#202020")
    draw = ImageDraw.Draw(sheet)
    label_font = _font(20)

    for index, (label, data) in enumerate(items):
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGB")
            image.thumbnail((cell_width - 8, cell_height - 48), Image.Resampling.LANCZOS)
            x = (index % columns) * cell_width + (cell_width - image.width) // 2
            y = (index // columns) * cell_height + 4
            sheet.paste(image, (x, y))
        label_y = (index // columns) * cell_height + cell_height - 38
        draw.text((index % columns * cell_width + 8, label_y), label, fill="white", font=label_font)

    output = BytesIO()
    sheet.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def _variant_character(character: Character, parameter: str, value) -> Character:
    data = {
        "weight_profile": character.weight_profile,
        "bust_size": character.bust_size,
        "age_category": character.age_category,
        "hairstyle": character.hairstyle,
        "hair_color": character.hair_color,
        "consistency_strength": character.consistency_strength,
    }
    if parameter == "body":
        data["weight_profile"] = value
    elif parameter == "boobs":
        data["bust_size"] = value
    elif parameter == "age":
        data["age_category"] = value
    elif parameter == "hair":
        data["hairstyle"] = value
    elif parameter == "color":
        data["hair_color"] = value
    elif parameter == "consistency":
        data["consistency_strength"] = value
    return Character(
        id=character.id,
        user_id=character.user_id,
        name=character.name,
        face_file_id=character.face_file_id,
        description=character.description,
        created_at=character.created_at,
        updated_at=character.updated_at,
        body_reference_file_id=None,
        weight=character.weight,
        bust=character.bust,
        age=character.age,
        weight_profile=data["weight_profile"],
        body_shape=character.body_shape,
        bust_size=data["bust_size"],
        bust_shape=character.bust_shape,
        age_category=data["age_category"],
        hairstyle=data["hairstyle"],
        hair_color=data["hair_color"],
        consistency_strength=data["consistency_strength"],
    )


async def _run_test(message: types.Message, ctx: TelegramContext, parameter: str) -> None:
    """Run a parameter sweep through the exact same Reference pipeline.

    Every variant uses pose="reference", so the normal ImageGenerationService
    selects data/media/reference/reference_openpose.png + reference_depth.png,
    uses the Reference canvas 512x768, Reference Depth strength 0.15, the same
    prompt construction, Face IP-Adapter/ReActor path, and Reference-specific
    Body IP-Adapter handling as a real Reference generation.
    """
    character_service = ctx.character_service
    image_service = ctx.image_service
    items = await character_service.list(message.from_user.id)
    if not items:
        await message.answer("❌ Сначала создай персонажа.")
        return

    character = max(items, key=lambda item: item.id)
    _, values = TESTS[parameter]
    results: list[tuple[str, bytes]] = []
    failures: list[str] = []

    for value in values:
        variant = _variant_character(character, parameter, value)
        try:
            _, result, _ = await image_service.generate(
                user_id=message.from_user.id,
                character_id=variant.id,
                scene=(
                    f"{SCENE}. Generate this character using the selected reference pose. "
                    "Use the reference only for the body pose and composition. "
                    "Preserve the character identity and apply the tested profile parameter."
                ),
                pose="reference",
            )
            results.append((str(value), result))
        except Exception as exc:
            failures.append(f"{value}: {exc}")

    if not results:
        await message.answer("❌ Не удалось создать ни одного тестового изображения.")
        return

    sheet = _make_sheet(results)
    title, _ = TESTS[parameter]
    caption = f"🧪 <b>Тест: {title}</b>\nПерсонаж: <b>{character.name}</b>\nВариантов: {len(results)}/{len(values)}"
    if failures:
        caption += f"\nОшибок: {len(failures)}"
    await message.answer_photo(
        types.BufferedInputFile(sheet, filename=f"test_{parameter}.jpg"),
        caption=caption,
        parse_mode="HTML",
    )



def register(router: Router, ctx: TelegramContext) -> None:
    commands = {
        "body": "test_body",
        "boobs": "test_boobs",
        "age": "test_age",
        "hair": "test_hair",
        "color": "test_color",
        "consistency": "test_consistency",
    }
    for parameter, command in commands.items():
        async def handler(message: types.Message, _parameter=parameter):
            try:
                await _run_test(message, ctx, _parameter)
            except AppError as exc:
                await message.answer(f"❌ {exc}")
            except Exception as exc:
                await message.answer(f"❌ Тест завершился с ошибкой: {exc}")
        router.message.register(handler, Command(command))
