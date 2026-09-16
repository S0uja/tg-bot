from __future__ import annotations

from io import BytesIO
from pathlib import Path

from aiogram import Router, types
from aiogram.filters import Command
from PIL import Image, ImageDraw, ImageFont

from main.core.context import TelegramContext
from main.domain.errors import AppError, ProviderError
from main.domain.models import Character, ImagePromptContext
from main.prompts.service import (
    AGE_PROMPTS,
    BUST_PROMPTS,
    HAIR_COLOR_PROMPTS,
    HAIRSTYLE_PROMPTS,
    WEIGHT_PROMPTS,
)
from poses.config import pose_category_root


TESTS = {
    "body": ("Телосложение", list(WEIGHT_PROMPTS)),
    "boobs": ("Грудь", [1, 2, 3, 4]),
    "age": ("Возраст", list(AGE_PROMPTS)),
    "hair": ("Прическа", list(HAIRSTYLE_PROMPTS)),
    "color": ("Цвет волос", list(HAIR_COLOR_PROMPTS)),
    "consistency": ("Consistency", ["low", "medium", "high", "maximum"]),
}


SCENE = (
    "photorealistic full-body portrait of one adult woman, wearing a simple fitted neutral outfit, "
    "head to toe visible, simple neutral studio background, natural soft lighting, front three-quarter camera view"
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
    """Test one profile parameter through the real Reference generation path.

    All variants in one test use the same deterministic seed so the tested parameter
    is the primary changing variable instead of random composition/body drift.
    """
    character_service = ctx.character_service
    image_service = ctx.image_service
    items = await character_service.list(message.from_user.id)
    if not items:
        await message.answer("❌ Сначала создай персонажа.")
        return

    character = max(items, key=lambda item: item.id)
    _, values = TESTS[parameter]
    total = len(values)
    results: list[tuple[str, bytes]] = []
    failures: list[str] = []

    # One seed for the whole parameter sweep: keep composition and random latent
    # as stable as possible so only the selected profile parameter is changed.
    test_seed = (1900000000 + int(character.id)) % (2**32)

    face = await character_service.read_face(character.face_file_id)
    reference_dir = pose_category_root("reference")
    openpose_path = reference_dir / "reference_openpose.png"
    depth_path = reference_dir / "reference_depth.png"
    if not openpose_path.is_file():
        raise ProviderError(f"Не найден Reference OpenPose: {openpose_path}")
    if not depth_path.is_file():
        raise ProviderError(f"Не найден Reference Depth: {depth_path}")
    if not image_service.video_start_frame_workflow_path:
        raise ProviderError("Не настроен Reference/start-frame workflow.")

    pose_image = openpose_path.read_bytes()
    depth_image = depth_path.read_bytes()
    progress = await message.answer(
        f"🧪 <b>Тест: {TESTS[parameter][0]}</b>\n"
        f"Генерация 0 из {total}",
        parse_mode="HTML",
    )

    for index, value in enumerate(values, start=1):
        try:
            await progress.edit_text(
                f"🧪 <b>Тест: {TESTS[parameter][0]}</b>\n"
                f"Генерация {index} из {total}: <b>{value}</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        variant = _variant_character(character, parameter, value)
        try:
            context = ImagePromptContext(
                character_description=variant.description,
                scene=SCENE,
                pose="reference",
                clothing="",
                weight_profile=variant.weight_profile,
                bust_size=variant.bust_size,
                age_category=variant.age_category,
                hairstyle=variant.hairstyle,
                hair_color=variant.hair_color,
                consistency_strength=variant.consistency_strength,
            )
            prompt = await image_service.prompt_service.build_image_prompt(context)
            effective_prompt = (
                f"{prompt.positive}, exactly one adult woman, one single person only, "
                "one body only, one head only, one face only, complete head and face, "
                "head fully inside frame, full body, single view, no triptych, no collage, "
                "do not reproduce multiple reference views"
            )
            if parameter == "boobs":
                effective_prompt += (
                    ", preserve the exact same body weight and body proportions across all variants, "
                    "same waist, same hips, same abdomen, same shoulders, same arms and legs; "
                    "change only bust size"
                )
            result = await image_service.image_provider.generate(
                character=variant,
                prompt=effective_prompt,
                reference_image=face,
                body_reference_image=face,
                workflow_path=image_service.video_start_frame_workflow_path,
                pose_image=pose_image,
                depth_image=depth_image,
                depth_strength=0.15,
                generation_size=(512, 768),
                generation_seed=test_seed,
            )
            # ReActor deliberately stays disabled for the age sweep: it replaces the
            # generated face with the original face and can erase the very age cues
            # that this test is supposed to measure. Other tests keep the normal ReActor path.
            if face and parameter != "age":
                result = await image_service.image_provider.reface(image=result, face_reference=face)
            results.append((str(value), result))
        except Exception as exc:
            failures.append(f"{value}: {exc}")

    try:
        await progress.delete()
    except Exception:
        pass

    if not results:
        await message.answer("❌ Не удалось создать ни одного тестового изображения.")
        return

    sheet = _make_sheet(results)
    title, _ = TESTS[parameter]
    caption = (
        f"🧪 <b>Тест: {title}</b>\n"
        f"Персонаж: <b>{character.name}</b>\n"
        f"Генерация: {len(results)} из {total}"
    )
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
