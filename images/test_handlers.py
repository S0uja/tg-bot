from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import re
import uuid

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from PIL import Image, ImageDraw, ImageFont

from main.core.context import TelegramContext
from main.domain.errors import AppError, ProviderError
from main.domain.models import Character, ImagePromptContext
from main.prompts.service import AGE_PROMPTS, BUST_PROMPTS, HAIR_COLOR_PROMPTS, HAIRSTYLE_PROMPTS, WEIGHT_PROMPTS
from poses.config import pose_category_root

TESTS = {"body": ("Телосложение", list(WEIGHT_PROMPTS)), "boobs": ("Грудь", [1, 2, 3, 4]), "age": ("Возраст", list(AGE_PROMPTS)), "hair": ("Прическа", list(HAIRSTYLE_PROMPTS)), "color": ("Цвет волос", list(HAIR_COLOR_PROMPTS)), "consistency": ("Consistency", ["low", "medium", "high", "maximum"])}
SCENE = "photorealistic full-body portrait of one adult woman, wearing a simple fitted neutral outfit, head to toe visible, simple neutral studio background, natural soft lighting, front three-quarter camera view"
POSE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _font(size: int):
    candidates = [Path(r"C:\Windows\Fonts\arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for path in candidates:
        if path.is_file(): return ImageFont.truetype(str(path), size)
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
    output = BytesIO(); sheet.save(output, format="JPEG", quality=92, optimize=True); return output.getvalue()


def _pose_generation_size(pose_path: Path) -> tuple[int, int]:
    try:
        with Image.open(pose_path) as image:
            width, height = image.size
    except Exception as exc:
        raise ProviderError(f"Не удалось прочитать размер OpenPose скелета: {pose_path}: {exc}") from exc
    if (width, height) not in ((512, 768), (768, 512)):
        raise ProviderError(f"Неподдерживаемый размер OpenPose: {width}x{height}. Разрешены только 512x768 и 768x512.")
    return width, height


def _variant_character(character: Character, parameter: str, value) -> Character:
    data = {"weight_profile": character.weight_profile, "bust_size": character.bust_size, "age_category": character.age_category, "hairstyle": character.hairstyle, "hair_color": character.hair_color, "consistency_strength": character.consistency_strength}
    if parameter == "body": data["weight_profile"] = value
    elif parameter == "boobs": data["bust_size"] = value
    elif parameter == "age": data["age_category"] = value
    elif parameter == "hair": data["hairstyle"] = value
    elif parameter == "color": data["hair_color"] = value
    elif parameter == "consistency": data["consistency_strength"] = value
    return Character(id=character.id, user_id=character.user_id, name=character.name, face_file_id=character.face_file_id, description=character.description, created_at=character.created_at, updated_at=character.updated_at, body_reference_file_id=None, weight=character.weight, bust=character.bust, age=character.age, weight_profile=data["weight_profile"], body_shape=character.body_shape, bust_size=data["bust_size"], bust_shape=character.bust_shape, age_category=data["age_category"], hairstyle=data["hairstyle"], hair_color=data["hair_color"], consistency_strength=data["consistency_strength"])


def _make_face_weight_workflow(source_path: Path, face_weight: float) -> Path:
    workflow = json.loads(source_path.read_text(encoding="utf-8"))
    face_node = workflow.get("9")
    if not isinstance(face_node, dict) or face_node.get("class_type") != "IPAdapterAdvanced":
        raise ProviderError("В start-frame workflow отсутствует Face IPAdapterAdvanced node 9.")
    face_node.setdefault("inputs", {})["weight"] = float(face_weight)
    output_path = source_path.parent / f".face_weight_test_{face_weight:.2f}_{uuid.uuid4().hex}.json"
    output_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


async def _run_test(message: types.Message, ctx: TelegramContext, parameter: str) -> None:
    character_service, image_service = ctx.character_service, ctx.image_service
    items = await character_service.list(message.from_user.id)
    if not items: await message.answer("❌ Сначала создай персонажа."); return
    character = max(items, key=lambda item: item.id); _, values = TESTS[parameter]; total = len(values); results = []; failures = []
    test_seed = (1900000000 + int(character.id)) % (2**32)
    face = await character_service.read_face(character.face_file_id); reference_dir = pose_category_root("reference")
    openpose_path, depth_path = reference_dir / "reference_openpose.png", reference_dir / "reference_depth.png"
    if not openpose_path.is_file(): raise ProviderError(f"Не найден Reference OpenPose: {openpose_path}")
    if not depth_path.is_file(): raise ProviderError(f"Не найден Reference Depth: {depth_path}")
    if not image_service.video_start_frame_workflow_path: raise ProviderError("Не настроен Reference/start-frame workflow.")
    pose_image, depth_image = openpose_path.read_bytes(), depth_path.read_bytes()
    progress = await message.answer(f"🧪 <b>Тест: {TESTS[parameter][0]}</b>\nГенерация 0 из {total}", parse_mode="HTML")
    for index, value in enumerate(values, 1):
        try: await progress.edit_text(f"🧪 <b>Тест: {TESTS[parameter][0]}</b>\nГенерация {index} из {total}: <b>{value}</b>", parse_mode="HTML")
        except Exception: pass
        variant = _variant_character(character, parameter, value)
        try:
            context = ImagePromptContext(character_description=variant.description, scene=SCENE, pose="reference", clothing="", weight_profile=variant.weight_profile, bust_size=variant.bust_size, age_category=variant.age_category, hairstyle=variant.hairstyle, hair_color=variant.hair_color, consistency_strength=variant.consistency_strength)
            prompt = await image_service.prompt_service.build_image_prompt(context)
            effective_prompt = f"{prompt.positive}, exactly one adult woman, one single person only, one body only, one head only, one face only, exactly two arms, exactly two legs, exactly two hands, exactly two feet, one continuous anatomically connected body, complete head and face, head fully inside frame, full body, single view, no triptych, no collage, do not reproduce multiple reference views"
            if parameter == "boobs": effective_prompt += ", preserve the exact same body weight and body proportions across all variants, same waist, same hips, same abdomen, same shoulders, same arms and legs; change only bust size"
            result = await image_service.image_provider.generate(character=variant, prompt=effective_prompt, reference_image=face, body_reference_image=face, workflow_path=image_service.video_start_frame_workflow_path, pose_image=pose_image, depth_image=depth_image, depth_strength=0.05, generation_size=(512, 768), generation_seed=test_seed)
            if face: result = await image_service.image_provider.reface(image=result, face_reference=face)
            results.append((str(value), result))
        except Exception as exc: failures.append(f"{value}: {exc}")
    try: await progress.delete()
    except Exception: pass
    if not results: await message.answer("❌ Не удалось создать ни одного тестового изображения."); return
    title, _ = TESTS[parameter]; caption = f"🧪 <b>Тест: {title}</b>\nПерсонаж: <b>{character.name}</b>\nГенерация: {len(results)} из {total}" + (f"\nОшибок: {len(failures)}" if failures else "")
    await message.answer_photo(types.BufferedInputFile(_make_sheet(results), filename=f"test_{parameter}.jpg"), caption=caption, parse_mode="HTML")


async def _run_pose_folder_test(message: types.Message, ctx: TelegramContext, folder_name: str) -> None:
    if not POSE_NAME_RE.fullmatch(folder_name): await message.answer("❌ Некорректное имя папки. Разрешены только латинские буквы, цифры, _ и -."); return
    folder = Path("data/media/poses") / folder_name
    if not folder.is_dir(): await message.answer(f"❌ Папка не найдена: <code>{folder}</code>", parse_mode="HTML"); return
    pairs = []
    for bone_path in sorted(folder.glob("*_bone_structure.*")):
        stem = bone_path.name.rsplit("_bone_structure", 1)[0]
        depth_path = next((folder / f"{stem}_depth{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") if (folder / f"{stem}_depth{ext}").is_file()), None)
        if depth_path is not None: pairs.append((bone_path, depth_path, stem))
    if not pairs: await message.answer(f"❌ В <code>{folder}</code> не найдено пар *_bone_structure + *_depth.", parse_mode="HTML"); return
    items = await ctx.character_service.list(message.from_user.id)
    if not items: await message.answer("❌ Сначала создай персонажа."); return
    character = max(items, key=lambda item: item.id); face = await ctx.character_service.read_face(character.face_file_id); image_service = ctx.image_service
    if not image_service.video_start_frame_workflow_path: raise ProviderError("Не настроен Reference/start-frame workflow.")
    seed_base = (2100000000 + int(character.id)) % (2**32)
    base_workflow_path = Path(image_service.video_start_frame_workflow_path)
    if not base_workflow_path.is_file(): raise ProviderError(f"Не найден workflow: {base_workflow_path}")
    progress = await message.answer(f"🧪 <b>Тест лица: {folder_name}</b>\nНайдено поз: {len(pairs)}\nГенерация 0 из {len(pairs)}", parse_mode="HTML")
    variants = (("A", 0.50), ("B", 0.35))
    for index, (bone_path, depth_path, stem) in enumerate(pairs, 1):
        try: await progress.edit_text(f"🧪 <b>Тест лица: {folder_name}</b>\nПоза {index} из {len(pairs)}: <code>{stem}</code>\nГенерации: Face A/B", parse_mode="HTML")
        except Exception: pass
        try:
            generation_size = _pose_generation_size(bone_path)
        except ProviderError as exc:
            await message.answer(f"❌ <code>{stem}</code>: {exc}", parse_mode="HTML")
            continue
        for variant_name, face_weight in variants:
            temp_workflow = None
            try:
                temp_workflow = _make_face_weight_workflow(base_workflow_path, face_weight)
                context = ImagePromptContext(character_description=character.description, scene=SCENE, pose=folder_name, clothing="", weight_profile=character.weight_profile, bust_size=character.bust_size, age_category=character.age_category, hairstyle=character.hairstyle, hair_color=character.hair_color, consistency_strength=character.consistency_strength)
                prompt = await image_service.prompt_service.build_image_prompt(context)
                effective_prompt = f"{prompt.positive}, exactly one adult woman, one single person only, one body only, one head only, one face only, exactly two arms, exactly two legs, exactly two hands, exactly two feet, one continuous anatomically connected body, complete head and face, head fully inside frame, full body, single view, no triptych, no collage, do not reproduce multiple reference views"
                result = await image_service.image_provider.generate(character=character, prompt=effective_prompt, reference_image=face, body_reference_image=face, workflow_path=str(temp_workflow), pose_image=bone_path.read_bytes(), depth_image=depth_path.read_bytes(), depth_strength=0.05, generation_size=generation_size, generation_seed=(seed_base + index) % (2**32), pose_body_ipadapter_weight=0.15, pose_body_ipadapter_end=0.35, pose_openpose_strength=0.8)
                if face: result = await image_service.image_provider.reface(image=result, face_reference=face)
                await message.answer_media_group([types.InputMediaPhoto(media=types.BufferedInputFile(depth_path.read_bytes(), filename=depth_path.name), caption=f"🗺 Depth: {stem}"), types.InputMediaPhoto(media=types.BufferedInputFile(result, filename=f"{stem}_face_{variant_name}.png"), caption=f"🧪 Результат {variant_name}: Face IPAdapter {face_weight:.2f}\nBody IPAdapter 0.15 → 0.35\nOpenPose 0.8\nDepth 0.05\nCanvas {generation_size[0]}x{generation_size[1]}\n{stem}")])
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить позу", callback_data=f"testpose_delete:{folder_name}:{stem}")]])
                await message.answer("Управление позой:", reply_markup=keyboard)
            except Exception as exc: await message.answer(f"❌ <code>{stem} [Face {face_weight:.2f}]</code>: {exc}", parse_mode="HTML")
            finally:
                if temp_workflow is not None:
                    try: temp_workflow.unlink(missing_ok=True)
                    except Exception: pass
    try: await progress.delete()
    except Exception: pass
    await message.answer(f"✅ <b>Тест лица завершён</b>\nПапка: <code>{folder_name}</code>\nПоз: {len(pairs)}\nСравнение Face IPAdapter: A=0.50 / B=0.35\nBody IPAdapter: 0.15→0.35\nOpenPose: 0.8\nDepth: 0.05\nРазмер каждого canvas берётся из OpenPose: 512x768 или 768x512", parse_mode="HTML")


async def _delete_pose_pair(callback: types.CallbackQuery, folder_name: str, stem: str) -> None:
    if not POSE_NAME_RE.fullmatch(folder_name) or not POSE_NAME_RE.fullmatch(stem): await callback.answer("Некорректное имя позы", show_alert=True); return
    folder = Path("data/media/poses") / folder_name
    bone_path = next((folder / f"{stem}_bone_structure{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") if (folder / f"{stem}_bone_structure{ext}").is_file()), None)
    depth_path = next((folder / f"{stem}_depth{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") if (folder / f"{stem}_depth{ext}").is_file()), None)
    if bone_path is None and depth_path is None: await callback.answer("Поза уже удалена", show_alert=True); return
    for path in (bone_path, depth_path):
        if path is not None: path.unlink()
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await callback.answer(f"Поза {stem} удалена")


def register(router: Router, ctx: TelegramContext) -> None:
    commands = {"body": "test_body", "boobs": "test_boobs", "age": "test_age", "hair": "test_hair", "color": "test_color", "consistency": "test_consistency"}
    for parameter, command in commands.items():
        async def handler(message: types.Message, _parameter=parameter):
            try: await _run_test(message, ctx, _parameter)
            except AppError as exc: await message.answer(f"❌ {exc}")
            except Exception as exc: await message.answer(f"❌ Тест завершился с ошибкой: {exc}")
        router.message.register(handler, Command(command))
    @router.message(Command("test_poses"))
    async def test_poses_handler(message: types.Message):
        args = (message.text or "").split(maxsplit=1)
        if len(args) != 2 or not args[1].strip(): await message.answer("Использование: <code>/test_poses название_папки</code>", parse_mode="HTML"); return
        try: await _run_pose_folder_test(message, ctx, args[1].strip())
        except AppError as exc: await message.answer(f"❌ {exc}")
        except Exception as exc: await message.answer(f"❌ Тест поз завершился с ошибкой: {exc}")
    @router.callback_query(F.data.startswith("testpose_delete:"))
    async def test_pose_delete_handler(callback: types.CallbackQuery):
        _, folder_name, stem = callback.data.split(":", 2)
        try: await _delete_pose_pair(callback, folder_name, stem)
        except Exception as exc: await callback.answer(f"Ошибка удаления: {exc}", show_alert=True)
