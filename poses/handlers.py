from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import asyncio
from html import escape
import json
import random
import secrets
import re
import tempfile
from pathlib import Path

from main.config import settings
from characters.service import CharacterService
from chat.service import ChatReply, ChatService
from images.service import ImageGenerationService
from videos.service import VideoGenerationService
from poses.config import poses_root, normalize_pose_image
from main.domain.errors import AppError
from chat.keyboards import EXIT_CHAT_TEXT, chat_keyboard
from characters.keyboards import (
    HAIR_COLOR_OPTIONS, HAIRSTYLE_OPTIONS, age_category_choices, bust_size_choices,
    character_actions, character_list, cancel_to_character, cancel_to_menu,
    consistency_choices, character_profile_menu, delete_confirmation,
    hair_color_choices, hairstyle_choices, weight_profile_choices,
)
from images.generation_keyboards import cancel_input, image_actions, video_actions
from main.library.keyboards import library_menu, library_items
from main.core.menu_keyboard import menu
from characters.states import CharacterCreation, CharacterEdit, CharacterProfileEdit
from chat.states import CharacterChat
from images.states import AnimationCreation, ImageCreation
from videos.states import VideoCreation

from main.core.context import TelegramContext

def register(router: Router, ctx: TelegramContext) -> None:
    character_service = ctx.character_service
    image_service = ctx.image_service
    video_service = ctx.video_service
    chat_service = ctx.chat_service
    edit_ui = ctx.edit_ui
    render_generation_message = ctx.render_generation_message
    show_menu = ctx.show_menu
    render_character = ctx.render_character
    render_profile = ctx.render_profile
    show_image_setup = ctx.show_image_setup
    show_video_setup = ctx.show_video_setup

    # callback token -> (Telegram user id, pose original path)
    pose_delete_tokens: dict[str, tuple[int, Path]] = {}

    


    @router.message(Command("analyze_poses"))
    async def analyze_poses(message: types.Message, state: FSMContext):
        """Build an incremental, persistent semantic index for pose originals."""
        root_dir = poses_root().resolve()
        progress = await message.answer(
            "🔎 <b>Анализирую библиотеку поз…</b>\n"
            "Новые и изменённые изображения будут добавлены в индекс; "
            "уже проанализированные файлы пропускаются.",
            parse_mode="HTML",
        )

        async def update_progress(
            current: int, total: int, analyzed: int, cached: int, key: str,
        ) -> None:
            # Avoid flooding Telegram while still keeping large imports visible.
            if current != total and current % 3:
                return
            try:
                await progress.edit_text(
                    "🔎 <b>Анализирую библиотеку поз…</b>\n\n"
                    f"Обработано: <b>{current}/{total}</b>\n"
                    f"Новых/изменённых: <b>{analyzed}</b>\n"
                    f"Из кеша: <b>{cached}</b>\n"
                    f"Текущий файл: <code>{escape(key)}</code>",
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                pass

        try:
            analyzed, cached, failures = await image_service.analyze_all_poses(
                update_progress
            )
            failures_text = (
                f"\nОшибок: <b>{len(failures)}</b>"
                if failures else ""
            )
            text = (
                "✅ <b>Индекс поз обновлён.</b>\n\n"
                f"Новых/изменённых: <b>{analyzed}</b>\n"
                f"Уже было в кеше: <b>{cached}</b>\n"
                f"Индекс: <code>{root_dir / '.pose_library.json'}</code>"
                f"{failures_text}"
            )
            await progress.edit_text(text, parse_mode="HTML")
        except Exception as exc:
            await progress.edit_text(
                f"❌ Не удалось проанализировать позы: {exc}"
            )



    async def test_person_depth_ab(message: types.Message, state: FSMContext):
        """Compare normal Depth vs person-only Depth for the first five poses."""
        # Diagnostic breadcrumbs are intentionally explicit: this command is
        # experimental and should never fail silently.
        await message.answer("🟢 PERSON_DEPTH START")
        if not settings.test_poses_enabled:
            await message.answer(
                "❌ Функция /test_person_depth_ab отключена в .env "
                "(TEST_POSES_ENABLED=false)."
            )
            return

        data = await state.get_data()
        character_id = data.get("character_id")
        if not character_id:
            await message.answer("❌ Сначала откройте чат с персонажем.")
            return
        await message.answer(f"🟢 CHARACTER OK: {character_id}")

        raw = (message.text or "").strip()
        match = re.match(
            r"^/test_person_depth_ab(?:@\w+)?(?:\s+(.+?))?\s*$",
            raw, flags=re.I
        )
        folder_arg = (match.group(1) if match else "").strip()
        if len(folder_arg) >= 2 and folder_arg[0] in {'"', "'", "“", "«"} and folder_arg[-1] in {'"', "'", "”", "»"}:
            folder_arg = folder_arg[1:-1].strip()
        if not folder_arg:
            await message.answer('❌ Укажите папку с позами.\nПример: /test_person_depth_ab "doggy"')
            return

        root_dir = poses_root().resolve()
        pose_dir = (root_dir / Path(folder_arg)).resolve()
        try:
            pose_dir.relative_to(root_dir)
        except ValueError:
            await message.answer("❌ Недопустимый путь к папке поз.")
            return
        if not pose_dir.is_dir():
            await message.answer(f"❌ Папка поз не найдена: {folder_arg}")
            return
        await message.answer(f"🟢 FOLDER OK: {pose_dir}")

        exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        originals = sorted(
            (
                p for p in pose_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in exts
                and not p.stem.lower().endswith("_noise_final_openpose") and not p.stem.endswith("_depth")
                and not p.stem.lower().endswith("_depth")
                and not p.stem.lower().endswith("_person_depth")
                and not p.stem.lower().endswith("_person_mask")
            ),
            key=lambda p: p.relative_to(pose_dir).as_posix().lower(),
        )[:5]
        if not originals:
            await message.answer(f"❌ В папке «{folder_arg}» нет исходных изображений.")
            return
        await message.answer(f"🟢 ORIGINALS OK: {len(originals)}")

        try:
            character = await character_service.get(message.from_user.id, int(character_id))
        except AppError as exc:
            await message.answer(f"❌ Не удалось загрузить персонажа: {exc}")
            return

        try:
            import cv2
            import numpy as np
        except Exception as exc:
            await message.answer(
                "❌ DEPTH MASK DEPENDENCY ERROR\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "Установи в активном .venv:\n"
                "python -m pip install opencv-python-headless numpy"
            )
            return
        await message.answer("🟢 CV2 + NUMPY OK")

        def make_person_depth(original_bytes: bytes, depth_bytes: bytes) -> tuple[bytes, bytes, str]:
            """Create person-only Depth using OpenCV GrabCut only."""
            import io
            import time
            from PIL import Image

            started = time.perf_counter()
            rgb = np.array(Image.open(io.BytesIO(original_bytes)).convert("RGB"))
            depth = np.array(Image.open(io.BytesIO(depth_bytes)).convert("L"))

            if rgb.size == 0:
                raise RuntimeError("GrabCut: original image is empty.")
            if depth.size == 0:
                raise RuntimeError("GrabCut: depth image is empty.")

            if rgb.shape[:2] != depth.shape[:2]:
                rgb = cv2.resize(
                    rgb, (depth.shape[1], depth.shape[0]),
                    interpolation=cv2.INTER_AREA
                )

            h, w = depth.shape[:2]
            if w < 32 or h < 32:
                raise RuntimeError(f"GrabCut: image too small: {w}x{h}")

            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            margin_x = max(2, int(w * 0.04))
            margin_y = max(2, int(h * 0.04))
            rect_w = max(1, w - 2 * margin_x)
            rect_h = max(1, h - 2 * margin_y)

            gc_mask = np.full((h, w), cv2.GC_BGD, dtype=np.uint8)
            bgd = np.zeros((1, 65), np.float64)
            fgd = np.zeros((1, 65), np.float64)

            cv2.grabCut(
                bgr, gc_mask,
                (margin_x, margin_y, rect_w, rect_h),
                bgd, fgd, 3, cv2.GC_INIT_WITH_RECT
            )

            mask = np.where(
                (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
                255, 0
            ).astype(np.uint8)

            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

            count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            if count <= 1:
                raise RuntimeError("GrabCut: foreground mask is empty.")

            largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            area = int(stats[largest, cv2.CC_STAT_AREA])
            mask = np.where(labels == largest, 255, 0).astype(np.uint8)

            if area < int(w * h * 0.005):
                raise RuntimeError(
                    f"GrabCut: foreground too small: {area}px/{w*h}px"
                )

            alpha = cv2.GaussianBlur(mask, (0, 0), 1.0).astype(np.float32) / 255.0
            person_depth = np.rint(
                depth.astype(np.float32) * alpha
                + 128.0 * (1.0 - alpha)
            ).clip(0, 255).astype(np.uint8)

            depth_buf = io.BytesIO()
            mask_buf = io.BytesIO()
            Image.fromarray(person_depth, "L").save(depth_buf, format="PNG")
            Image.fromarray(mask, "L").save(mask_buf, format="PNG")

            elapsed = time.perf_counter() - started
            return (
                depth_buf.getvalue(),
                mask_buf.getvalue(),
                f"grabcut ({elapsed:.2f}s, foreground={area/(w*h):.1%})",
            )
        scene = (
            "Create a photorealistic image of the selected adult character. "
            "The supplied OpenPose is authoritative for body position and limb geometry. "
            "The supplied Depth map is authoritative for spatial depth. "
            "Preserve the exact camera-facing orientation and overall body configuration "
            "from the pose references. Do not invent a different pose."
        )
        results = []
        for index, original_file in enumerate(originals, start=1):
            pose_file = original_file.with_name(original_file.stem + "_noise_final_openpose.png")
            depth_file = original_file.with_name(original_file.stem + "_depth.png")
            if not pose_file.is_file() or not depth_file.is_file():
                await message.answer(
                    f"⚠️ Поза {index}: {original_file.name}\n"
                    f"Нужны: {pose_file.name} и {depth_file.name}"
                )
                continue

            original_bytes = original_file.read_bytes()
            pose_bytes = pose_file.read_bytes()
            depth_bytes = depth_file.read_bytes()
            await message.answer(f"🟡 MASK START: pose {index}")
            try:
                person_depth_bytes, mask_bytes, method = make_person_depth(
                    original_bytes, depth_bytes
                )
                await message.answer(
                    f"🟢 MASK OK: pose {index}, method={method}"
                )
                seed = random.randint(1, 2**63 - 1)

                variants = [
                    ("A — Normal Depth 0.50", depth_bytes),
                    ("B — Person-only Depth 0.50", person_depth_bytes),
                ]
                generated = []
                for label, test_depth in variants:
                    await message.answer(f"🟡 GENERATING: pose {index} / {label}")
                    _, result, _ = await image_service.generate(
                        user_id=message.from_user.id,
                        character_id=character.id,
                        scene=scene,
                        pose=folder_arg,
                        pose_reference_image=pose_bytes,
                        pose_reference_path=pose_file,
                        orientation_reference_image=original_bytes,
                        orientation_reference_path=original_file,
                        depth_reference_image=test_depth,
                        depth_reference_path=None,
                        depth_strength=0.50,
                        generation_seed=seed,
                    )
                    generated.append((label, result))

                # Four-item album: original, mask, A, B. Captions are set at
                # construction time because aiogram InputMediaPhoto is frozen.
                media = [
                    types.InputMediaPhoto(
                        media=types.BufferedInputFile(original_bytes, filename=f"original_{index}.png"),
                        caption=(
                            f"Поза {index}: {original_file.name}\n"
                            f"Mask: {method}\n"
                            f"A = Normal Depth 0.50\n"
                            f"B = Person-only Depth 0.50\n"
                            f"Seed: {seed}"
                        ),
                    ),
                    types.InputMediaPhoto(
                        media=types.BufferedInputFile(mask_bytes, filename=f"mask_{index}.png"),
                    ),
                    types.InputMediaPhoto(
                        media=types.BufferedInputFile(generated[0][1], filename=f"A_{index}.png"),
                    ),
                    types.InputMediaPhoto(
                        media=types.BufferedInputFile(generated[1][1], filename=f"B_{index}.png"),
                    ),
                ]
                await message.answer_media_group(media=media)
                await message.answer(f"🟢 ALBUM SENT: pose {index}")
                results.append(index)
            except Exception as exc:
                await message.answer(
                    f"⚠️ Поза {index}: {original_file.name}\n"
                    f"Ошибка: {exc}"
                )

        if results:
            await message.answer(
                f"✅ Person-only Depth A/B завершён: {len(results)}/{len(originals)} поз."
            )
        else:
            await message.answer("❌ Не удалось получить ни одного результата.")

    async def test_depth_ab(message: types.Message, state: FSMContext):
        """A/B test Depth ControlNet on the first pose in a folder using one fixed seed."""
        if not settings.test_poses_enabled:
            await message.answer(
                "❌ Функция /test_depth_ab отключена в .env (TEST_POSES_ENABLED=false)."
            )
            return

        data = await state.get_data()
        character_id = data.get("character_id")
        if not character_id:
            await message.answer("❌ Сначала откройте чат с персонажем.")
            return

        raw = (message.text or "").strip()
        match = re.match(r"^/test_depth_ab(?:@\w+)?(?:\s+(.+?))?\s*$", raw, flags=re.I)
        folder_arg = (match.group(1) if match else "").strip()
        if len(folder_arg) >= 2 and folder_arg[0] in {'"', "'", "“", "«"} and folder_arg[-1] in {'"', "'", "”", "»"}:
            folder_arg = folder_arg[1:-1].strip()
        if not folder_arg:
            await message.answer('❌ Укажите папку с позами.\nПример: /test_depth_ab "doggy"')
            return

        root_dir = poses_root().resolve()
        requested = Path(folder_arg)
        if requested.is_absolute():
            await message.answer("❌ Можно указывать только папку внутри poses.")
            return
        pose_dir = (root_dir / requested).resolve()
        try:
            pose_dir.relative_to(root_dir)
        except ValueError:
            await message.answer("❌ Недопустимый путь к папке поз.")
            return
        if not pose_dir.is_dir():
            await message.answer(f"❌ Папка поз не найдена: {folder_arg}")
            return

        exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        originals = sorted(
            (
                p for p in pose_dir.rglob("*")
                if p.is_file()
                and p.suffix.lower() in exts
                and not p.stem.lower().endswith("_noise_final_openpose")
                and not p.stem.lower().endswith("_depth")
            ),
            key=lambda p: p.relative_to(pose_dir).as_posix().lower(),
        )
        if not originals:
            await message.answer(f"❌ В папке «{folder_arg}» нет оригинальных изображений.")
            return

        original_file = originals[0]
        pose_file = original_file.with_name(original_file.stem + "_noise_final_openpose.png")
        depth_file = original_file.with_name(original_file.stem + "_depth.png")
        if not pose_file.is_file():
            await message.answer(f"❌ Не найден OpenPose: {pose_file.name}")
            return
        if not depth_file.is_file():
            await message.answer(f"❌ Не найдена Depth-карта: {depth_file.name}")
            return

        try:
            character = await character_service.get(message.from_user.id, int(character_id))
        except AppError as exc:
            await message.answer(f"❌ Не удалось загрузить персонажа: {exc}")
            return

        scene = (
            "Create a photorealistic image of the selected adult character using "
            "the supplied pose reference as the exact body-position and camera-orientation guide. "
            "Preserve the character identity, face, hair, body proportions and natural realistic appearance. "
            "The pose reference is authoritative for body position and subject orientation. "
            "Do not rotate the subject toward the camera and do not invent a different pose."
        )
        current_scene = (data.get("current_scene") or "").strip()
        if current_scene:
            scene += f" Maintain compatible visual continuity with the current chat scene: {current_scene}"

        original_bytes = original_file.read_bytes()
        pose_bytes = pose_file.read_bytes()
        depth_bytes = depth_file.read_bytes()

        variants = [
            ("A — OpenPose ONLY", None),
            ("B — Depth 0.35", 0.35),
            ("C — Depth 0.50", 0.50),
            ("D — Depth 0.65", 0.65),
            ("E — Depth 0.85", 0.85),
        ]
        seed = random.randint(1, 2**63 - 1)

        progress = await message.answer(
            f"🧪 <b>Depth A/B тест</b>\n"
            f"Поза: <b>{original_file.name}</b>\n"
            f"Seed: <code>{seed}</code>\n\n"
            "A: OpenPose only\nB: 0.35\nC: 0.50\nD: 0.65\nE: 0.85\n\n"
            "Генерирую 5 вариантов с одним seed…",
            parse_mode="HTML",
        )

        results = []
        for label, strength in variants:
            try:
                _, result, _ = await image_service.generate(
                    user_id=message.from_user.id,
                    character_id=character.id,
                    scene=scene,
                    pose=folder_arg,
                    pose_reference_image=pose_bytes,
                    pose_reference_path=pose_file,
                    orientation_reference_image=original_bytes,
                    orientation_reference_path=original_file,
                    depth_reference_image=depth_bytes if strength is not None else None,
                    depth_reference_path=depth_file if strength is not None else None,
                    depth_strength=strength,
                    generation_seed=seed,
                )
                results.append((label, result))
            except Exception as exc:
                await message.answer(f"⚠️ {label}: {exc}")

        if results:
            media = []
            for i, (label, image_bytes) in enumerate(results):
                media.append(types.InputMediaPhoto(
                    media=types.BufferedInputFile(image_bytes, filename=f"depth_ab_{i+1}.png"),
                    caption=label if i == 0 else None,
                ))
            await message.answer_media_group(media=media)
            await progress.edit_text(
                f"✅ <b>Depth A/B тест завершён: {len(results)}/5</b>\n"
                f"Одна поза, один seed: <code>{seed}</code>\n"
                "Сравни A–E по сохранению таза, коленей, стоп и глубины тела.",
                parse_mode="HTML",
            )
        else:
            await progress.edit_text("❌ Не удалось получить ни одного результата.")

    @router.callback_query(F.data.startswith("pose_delete:"))
    async def delete_test_pose(callback: types.CallbackQuery):
        """Delete one pose set: original + OpenPose + Depth."""
        token = (callback.data or "").split(":", 1)[1]
        record = pose_delete_tokens.get(token)
        if record is None:
            await callback.answer("Кнопка устарела.", show_alert=True)
            return

        owner_id, original_file = record
        if callback.from_user.id != owner_id:
            await callback.answer("Эта кнопка принадлежит другому пользователю.", show_alert=True)
            return

        root_dir = poses_root().resolve()
        try:
            original_path = original_file.resolve()
            original_path.relative_to(root_dir)
        except (ValueError, OSError):
            pose_delete_tokens.pop(token, None)
            await callback.answer("Недопустимый путь к позе.", show_alert=True)
            return

        skeleton = original_path.with_name(
            original_path.stem + "_noise_final_openpose.png"
        )
        depth = original_path.with_name(
            original_path.stem + "_depth.png"
        )

        deleted = []
        for path in (original_path, skeleton, depth):
            try:
                if path.is_file():
                    path.unlink()
                    deleted.append(path.name)
            except OSError as exc:
                await callback.answer(
                    f"Не удалось удалить {path.name}: {exc}",
                    show_alert=True,
                )
                return

        pose_delete_tokens.pop(token, None)

        try:
            await callback.message.edit_text(
                "🗑 <b>Поза удалена</b>\n"
                f"Удалено файлов: <b>{len(deleted)}/3</b>\n"
                + ("\n".join(f"• {name}" for name in deleted) if deleted else "Файлы уже отсутствовали."),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer("Поза удалена.")

    @router.message(CharacterChat.active, Command("test_poses"))
    async def test_poses(message: types.Message, state: FSMContext):
        """Generate one image for every pose reference in a named pose folder."""
        if not settings.test_poses_enabled:
            await message.answer(
                "❌ Функция /test_poses отключена в .env "
                "(TEST_POSES_ENABLED=false)."
            )
            return

        data = await state.get_data()
        character_id = data.get("character_id")
        if not character_id:
            await message.answer("❌ Сначала откройте чат с персонажем.")
            return

        raw = (message.text or "").strip()
        match = re.match(
            r"^/test_poses(?:@\w+)?(?:\s+(.+?))?\s*$",
            raw,
            flags=re.I,
        )
        folder_arg = (match.group(1) if match else "").strip()
        if (
            len(folder_arg) >= 2
            and folder_arg[0] in {'"', "'", "“", "«"}
            and folder_arg[-1] in {'"', "'", "”", "»"}
        ):
            folder_arg = folder_arg[1:-1].strip()

        if not folder_arg:
            await message.answer(
                '❌ Укажите папку с позами.\nПример: /test_poses "doggy"'
            )
            return

        root_dir = poses_root().resolve()
        requested = Path(folder_arg)
        if requested.is_absolute():
            await message.answer("❌ Можно указывать только папку внутри poses.")
            return

        pose_dir = (root_dir / requested).resolve()
        try:
            pose_dir.relative_to(root_dir)
        except ValueError:
            await message.answer("❌ Недопустимый путь к папке поз.")
            return

        if not pose_dir.is_dir():
            await message.answer(f"❌ Папка поз не найдена: {folder_arg}")
            return

        exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        original_files = sorted(
            (
                p for p in pose_dir.rglob("*")
                if p.is_file()
                and p.suffix.lower() in exts
                and not p.stem.lower().endswith("_noise_final_openpose")
                and not p.stem.lower().endswith("_depth")
            ),
            key=lambda p: p.relative_to(pose_dir).as_posix().lower(),
        )
        if not original_files:
            await message.answer(
                f"❌ В папке «{folder_arg}» нет оригинальных изображений поз."
            )
            return

        pose_pairs = []
        missing_openpose = []
        for original_file in original_files:
            # One pose is a 3-file set:
            #   original.ext
            #   original_noise_final_openpose.png
            #   original_depth.png
            # Depth is optional for backward compatibility, but OpenPose is required.
            skeleton = original_file.with_name(
                original_file.stem + "_noise_final_openpose.png"
            )
            depth = original_file.with_name(
                original_file.stem + "_depth.png"
            )
            if skeleton.is_file():
                pose_pairs.append((original_file, skeleton, depth if depth.is_file() else None))
            else:
                missing_openpose.append(
                    original_file.relative_to(pose_dir).as_posix()
                )

        if missing_openpose:
            preview = "\n".join(f"• {name}" for name in missing_openpose[:10])
            extra = "" if len(missing_openpose) <= 10 else f"\n… и ещё {len(missing_openpose)-10}"
            await message.answer(
                "❌ Для некоторых оригиналов не найден OpenPose-файл:\n"
                f"{preview}{extra}\n\n"
                "Ожидаемый формат: (1).jpg + (1)_noise_final_openpose.png + (1)_depth.png"
            )
            return

        try:
            character = await character_service.get(
                message.from_user.id, int(character_id)
            )
        except AppError as exc:
            await message.answer(f"❌ Не удалось загрузить персонажа: {exc}")
            return

        progress = await message.answer(
            f"🧪 <b>Тест поз: {folder_arg}</b>\n\n"
            f"Найдено пар: <b>{len(pose_pairs)}</b>\n"
            "Генерирую по очереди…",
            parse_mode="HTML",
        )

        current_scene = (data.get("current_scene") or "").strip()
        scene = (
            "Create a photorealistic image of the selected adult character using "
            "the supplied pose reference as the exact body-position and camera-"
            "orientation guide. Preserve the character identity, face, hair, body "
            "proportions and natural realistic appearance. The pose reference is "
            "authoritative for body position and subject orientation. Do not rotate "
            "the subject toward the camera and do not invent a different pose."
        )
        if current_scene:
            scene += (
                f" Maintain compatible visual continuity with the current chat "
                f"scene: {current_scene}"
            )

        sent = 0
        failed = 0
        for index, (original_file, pose_file, depth_file) in enumerate(pose_pairs, start=1):
            try:
                original_bytes = original_file.read_bytes()
                pose_bytes = pose_file.read_bytes()
                depth_bytes = depth_file.read_bytes() if depth_file is not None else None

                character_result, result, generation_id = await image_service.generate(
                    user_id=message.from_user.id,
                    character_id=character.id,
                    scene=scene,
                    pose=folder_arg,
                    pose_reference_image=pose_bytes,
                    pose_reference_path=pose_file,
                    orientation_reference_image=original_bytes,
                    orientation_reference_path=original_file,
                    depth_reference_image=depth_bytes,
                    depth_reference_path=depth_file,
                    depth_strength=0.35 if depth_bytes is not None else None,
                )

                # Read the orientation from the ORIGINAL image's cache entry.
                orientation_info = await image_service.get_pose_orientation(
                    original_file,
                    original_bytes,
                )
                orientation_text = (
                    "🤖 Анализ ИИ из кеша:\n"
                    f"orientation: {orientation_info.get('orientation', 'unknown')}\n"
                    f"face_visible: {str(bool(orientation_info.get('face_visible', False))).lower()}\n"
                    f"confidence: {float(orientation_info.get('confidence', 0.0)):.2f}"
                )

                # Telegram album: show the REAL original pose, never the skeleton,
                # followed by the generated result.
                await message.answer_media_group(
                    media=[
                        types.InputMediaPhoto(
                            media=types.BufferedInputFile(
                                original_bytes,
                                filename=f"pose_original_{index:03d}{original_file.suffix.lower()}",
                            ),
                            caption=(
                                f"🧪 Поза {index}/{len(pose_pairs)} — {original_file.stem}\n"
                                "⬅️ Оригинал позы\n\n"
                                "➡️ Результат генерации\n\n"
                                + orientation_text
                            ),
                        ),
                        types.InputMediaPhoto(
                            media=types.BufferedInputFile(
                                result,
                                filename=f"pose_result_{index:03d}.png",
                            ),
                        ),
                    ]
                )

                # Inline keyboard must be sent as a separate message because
                # Telegram media-group items cannot have inline keyboards.
                token = secrets.token_urlsafe(6)
                pose_delete_tokens[token] = (message.from_user.id, original_file)
                # Keep the in-memory map bounded.
                if len(pose_delete_tokens) > 1000:
                    for stale in list(pose_delete_tokens)[:200]:
                        pose_delete_tokens.pop(stale, None)

                keyboard = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            types.InlineKeyboardButton(
                                text="🗑 Удалить эту позу",
                                callback_data=f"pose_delete:{token}",
                            )
                        ]
                    ]
                )
                await message.answer(
                    f"Поза {index}: если результат не подходит, удалить все 3 файла:",
                    reply_markup=keyboard,
                )

                sent += 1
                try:
                    await progress.edit_text(
                        f"🧪 <b>Тест поз: {folder_arg}</b>\n\n"
                        f"Готово: <b>{sent}/{len(pose_pairs)}</b>\n"
                        f"Сейчас: <code>{original_file.name}</code>",
                        parse_mode="HTML",
                    )
                except TelegramBadRequest:
                    pass
            except Exception as exc:
                failed += 1
                await message.answer(
                    f"⚠️ Поза {index}/{len(pose_pairs)} — {original_file.name}\n"
                    f"Не удалось сгенерировать: {exc}"
                )

        summary = f"✅ Тест завершён: {sent}/{len(pose_pairs)} изображений."
        if failed:
            summary += f"\n⚠️ Ошибок: {failed}."
        try:
            await progress.edit_text(summary)
        except TelegramBadRequest:
            await message.answer(summary)
