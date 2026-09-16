from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import asyncio
import json
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

    


    @router.callback_query(F.data == "menu:chat")
    async def chat_character_list(callback: types.CallbackQuery):
        items = await character_service.list(callback.from_user.id)
        if not items:
            await edit_ui(callback.message, "💬 <b>Чат</b>\n\nПока нет персонажей. Сначала создайте персонажа.", reply_markup=character_list([], prefix="chat"), parse_mode="HTML")
        else:
            await edit_ui(callback.message, "💬 <b>Чат</b>\n\nВыберите персонажа для общения:", reply_markup=character_list([(item.id, item.name) for item in items], prefix="chat"), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data.startswith("chat:"))
    async def chat_character_selected(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            character = await character_service.get(callback.from_user.id, character_id)
        except AppError:
            await callback.answer("Персонаж не найден", show_alert=True)
            return
        await state.clear()
        await state.update_data(character_id=character.id)
        await state.set_state(CharacterChat.active)
        await edit_ui(callback.message, f"💬 <b>Чат с «{character.name}»</b>\n\nПишите как обычно — персонаж будет отвечать от своего имени.\nДля выхода используйте кнопку на клавиатуре.", parse_mode="HTML")
        await callback.message.answer("💬 Чат активирован.", reply_markup=chat_keyboard())
        await callback.answer("Чат открыт")

    @router.callback_query(F.data.startswith("charchar:"))
    async def character_chat_start(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            character = await character_service.get(callback.from_user.id, character_id)
        except AppError:
            await callback.answer("Персонаж не найден", show_alert=True)
            return
        await state.clear()
        await state.update_data(character_id=character.id)
        await state.set_state(CharacterChat.active)
        await edit_ui(callback.message, f"💬 <b>Чат с «{character.name}»</b>\n\nПишите сообщение — персонаж будет отвечать от своего имени.\nДля выхода используйте кнопку на клавиатуре.", parse_mode="HTML")
        await callback.message.answer("💬 Чат активирован.", reply_markup=chat_keyboard())
        await callback.answer("Чат открыт")

    @router.message(CharacterChat.active, Command("clear"))
    async def character_chat_clear(message: types.Message, state: FSMContext):
        data = await state.get_data()
        character_id = data.get("character_id")
        if not character_id:
            await state.clear()
            await message.answer("Сессия чата потеряна.", reply_markup=types.ReplyKeyboardRemove())
            return
        try:
            character = await character_service.get(message.from_user.id, int(character_id))
            await chat_service.clear_history(message.from_user.id, character.id)
            await state.update_data(current_scene="")
            await message.answer(
                f"🧹 История чата с «{character.name}» очищена.",
                reply_markup=chat_keyboard(),
            )
        except AppError as exc:
            await message.answer(f"❌ Не удалось очистить историю: {exc}", reply_markup=chat_keyboard())

    @router.message(CharacterChat.active, F.text == EXIT_CHAT_TEXT)
    async def character_chat_exit(message: types.Message, state: FSMContext):
        data = await state.get_data()
        character_id = data.get("character_id")
        await state.clear()
        if character_id:
            try:
                await message.answer("👋 Чат завершён.", reply_markup=types.ReplyKeyboardRemove())
                item = await character_service.get(message.from_user.id, int(character_id))
                profile = (
                    f"⚖️ Телосложение: {item.weight_profile}" if item.weight_profile
                    else (f"⚖️ Вес: {item.weight:g} кг" if item.weight is not None else "⚖️ Телосложение: не задано")
                ) + "\n" + (
                    f"💗 Грудь: {item.bust_size}" if item.bust_size is not None
                    else (f"💗 Объём груди: {item.bust:g} см" if item.bust is not None else "💗 Грудь: не задана")
                ) + "\n" + (
                    f"🎂 Возраст: {item.age_category}" if item.age_category
                    else (f"🎂 Возраст: {item.age} лет" if item.age is not None else "🎂 Возраст: не задан")
                ) + "\n" + f"💇 Прическа: {item.hairstyle or 'не задана'}" + "\n" + f"🎨 Цвет волос: {item.hair_color or 'не задан'}"
                text = (f"👤 <b>{item.name}</b>\n\n{item.description or 'Описание не задано.'}\n\n{profile}\n\nID: <code>{item.id}</code>")
                await message.answer(text, reply_markup=character_actions(item.id), parse_mode="HTML")
                return
            except AppError:
                pass
        await message.answer("👋 Чат завершён.", reply_markup=types.ReplyKeyboardRemove())
        await show_menu(message)

    @router.message(CharacterChat.active, F.text)
    async def character_chat_message(message: types.Message, state: FSMContext):
        data = await state.get_data()
        character_id = data.get("character_id")
        if not character_id:
            await state.clear()
            await message.answer("Сессия чата потеряна.", reply_markup=types.ReplyKeyboardRemove())
            return
        try:
            character = await character_service.get(message.from_user.id, int(character_id))
            history = await chat_service.history(message.from_user.id, character.id, limit=20)
            user_text = message.text.strip()
            current_scene = (data.get("current_scene") or "").strip()
            result = await chat_service.reply(
                character,
                history,
                user_text,
                current_scene=current_scene,
            )

            # An explicit Telegram video/circle request is deterministic user intent.
            # Do not let Qwen accidentally downgrade it to a text-only answer.
            explicit_video = chat_service.wants_video_note(user_text)

            # For an explicit hand-wave request, do not leave the motion wording
            # to Qwen. LTXV needs a concrete chronological physical action.
            wave_words = (
                "помаши рукой",
                "помаши мне рукой",
                "помахай рукой",
                "помахай мне рукой",
                "махни рукой",
                "помахать рукой",
                "помахать мне рукой",
            )
            if explicit_video and any(word in user_text.lower() for word in wave_words):
                result = ChatReply(
                    result.reply,
                    "video",
                    (
                        "HAND-WAVE ACTION — THE START FRAME MUST ALREADY CONTAIN THE "
                        "RAISED HAND. Exactly one adult woman, one person only, upper "
                        "body centered. START POSE: one arm is already raised beside "
                        "the face, elbow bent naturally, hand and forearm fully visible "
                        "inside the frame. Do NOT spend animation time raising the arm. "
                        "MOTION 1 (0.0-0.8s): keep the elbow and upper arm mostly steady "
                        "and move the raised hand/wrist clearly to the left side relative "
                        "to the face. MOTION 2 (0.8-1.6s): move the same hand/wrist clearly "
                        "to the right side relative to the face. MOTION 3 (1.6-2.4s): "
                        "move it back to the left. MOTION 4 (2.4-3.2s): move it back "
                        "to the right. These must be four distinct visible hand/wrist "
                        "direction changes, not one continuous reach. FINAL (3.2-4.0s): "
                        "slowly lower the same arm to a relaxed position only after all "
                        "four waves are completed. The hand must never reach toward the "
                        "camera. CAMERA LOCK: static camera, no zoom, pan or camera motion. "
                        "IDENTITY LOCK: preserve face, hair, body proportions, clothing "
                        "and background. Never add another person, duplicate or clone. "
                        "Do not turn the wave into pointing, touching the camera, or an "
                        "unrelated pose change."
                    ),
                    result.pose,
                    result.scene_state,
                )

            if explicit_video and result.media_type != "video":
                result = ChatReply(
                    result.reply,
                    "video",
                    result.media_prompt or (
                        "START POSE: natural seated or standing pose, upper body and both hands fully visible. "
                        f"MOTION STEP 1: {user_text}. "
                        "MOTION STEP 2: complete the requested movement clearly and visibly. "
                        "FINAL POSITION: return to a natural relaxed pose. "
                        "CAMERA/IDENTITY LOCK: fixed camera, preserve face, hair, body proportions, clothing and environment. "
                        "Keep all moving hands and arms inside the frame; no unrelated movement."
                    ),
                    result.pose,
                    result.scene_state,
                )

            # Persist the structured visual state even on text-only turns.
            # This is what lets "я лежу и читаю книгу" affect a later "покажи".
            if result.scene_state:
                await state.update_data(current_scene=json.dumps(result.scene_state, ensure_ascii=False))

            reply = result.reply.strip() or "Не знаю, что сказать 😅"
            await chat_service.remember(message.from_user.id, character.id, "user", user_text)
            await chat_service.remember(message.from_user.id, character.id, "assistant", reply)

            if result.media_type == "video":
                # The Qwen media decision is authoritative for media. Python only
                # performs the actual generation and delivery.
                await message.answer(reply, reply_markup=chat_keyboard())
                try:
                    # IMPORTANT: a text-to-video generation cannot reliably perform a
                    # requested gesture if the initial composition does not contain the
                    # required body part. Build a dedicated start frame first, then run
                    # the normal image-to-video pipeline from that exact image.
                    action_plan = result.media_prompt.strip()

                    def build_video_start_scene(action: str, previous_scene: str) -> str:
                        a = action.lower()
                        if re.search(r"(маш|помаш|рук|ладон|кист)", a):
                            framing = (
                                "medium portrait shot from about the waist/chest up, "
                                "both shoulders, both arms and both hands fully visible, "
                                "hands kept inside the central square-safe area of the frame"
                            )
                        elif re.search(r"(ид[её]|идти|шага|ход|подой|отойд|поверн.*тело|разверн)", a):
                            framing = (
                                "medium-full shot with the entire body visible from head to feet, "
                                "enough space around the body for natural movement"
                            )
                        elif re.search(r"(наклон|наклонит|впер[её]д|назад|встан|сесть|садит)", a):
                            framing = (
                                "medium shot with head, torso, hips and both arms visible, "
                                "enough vertical space for the requested movement"
                            )
                        else:
                            framing = (
                                "medium portrait shot with head, shoulders, torso and both hands "
                                "visible inside the central square-safe area"
                            )

                        continuity = previous_scene or (
                            f"the same character from the CHARACTER PROFILE, with her established "
                            f"face, hair and body appearance"
                        )
                        return (
                            "Create the START FRAME for a short realistic Telegram video note. ""SINGLE SUBJECT ONLY: exactly one adult woman and no other people. Never create a second person, duplicate, twin, clone, reflection-person, background person, or collage. "
                            "This is a preparatory still image, not the animation itself. "
                            f"COMPOSITION: {framing}. "
                            "Keep the subject centered and leave safe space around all limbs. "
                            "The requested movement must have physical room to happen without "
                            "the hand, arm or body leaving the frame. "
                            f"VISUAL CONTINUITY: {continuity}. "
                            f"REQUESTED ACTION: {action}. "
                            "Choose a natural neutral starting pose that makes the requested action "
                            "easy to see. Do not perform the action yet. "
                            "Do not crop hands or arms. Keep the important moving body part clearly "
                            "visible in the frame."
                        )

                    start_scene = build_video_start_scene(action_plan, current_scene)
                    progress_message = await message.answer(
                        "🖼️ Подготавливаю кадр для движения…",
                        reply_markup=chat_keyboard(),
                    )
                    try:
                        _, start_image, _ = await image_service.generate_video_start_frame(
                            user_id=message.from_user.id,
                            character_id=character.id,
                            description=start_scene,
                        )
                        await state.update_data(current_scene=start_scene)

                        # Не редактируем progress-сообщение: Telegram может
                        # отклонить edit_text() для сообщения с ReplyKeyboard.
                        await message.answer(
                            "🎥 Анимирую именно этот кадр…",
                            reply_markup=chat_keyboard(),
                        )
                        _, video_bytes, _ = await video_service.generate_from_image(
                            progress_callback=None,
                            user_id=message.from_user.id,
                            character_id=character.id,
                            source_image=start_image,
                            description=(
                                "ACTION PLAN:\n" + action_plan + "\n\n"
                                "START FRAME LOCK: use the supplied image as the exact first frame. "
                                "Do not replace, redesign or recompose it.\n"
                                "MOTION: perform every requested movement sequentially and visibly. "
                                "Complete one step before beginning the next.\n"
                                "CAMERA LOCK: fixed camera, no zoom, pan, tilt, tracking or reframing.\n"
                                "IDENTITY LOCK: preserve the same face, hair, body proportions, "
                                "clothing and environment.\n"
                                "FRAME SAFETY: keep the moving hands, arms and body inside the frame. "
                                "Do not crop or hide the requested moving part.\n"
                                "QUALITY: natural continuous motion, realistic acceleration/deceleration, "
                                "no pose jumps, teleportation, flicker, identity drift or body warping.\n"
                                "Only perform the requested action; do not invent a different gesture."
                            ),
                        )
                    finally:
                        try:
                            await progress_message.delete()
                        except TelegramBadRequest:
                            pass

                    src = Path(tempfile.gettempdir()) / f"tg_chat_note_{message.from_user.id}.mp4"
                    dst = src.with_name(src.stem + "_square.mp4")
                    src.write_bytes(video_bytes)
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", str(src),
                        "-vf", "scale=512:512:force_original_aspect_ratio=increase,crop=512:512",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-an", "-movflags", "+faststart", str(dst),
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                    )
                    _, err = await proc.communicate()
                    if proc.returncode != 0 or not dst.exists():
                        raise RuntimeError(f"Не удалось подготовить видео-кружок: {err.decode(errors='ignore')[-500:]}")
                    note_bytes = dst.read_bytes()
                    await message.answer_video_note(
                        types.BufferedInputFile(note_bytes, filename="video_note.mp4")
                    )
                    src.unlink(missing_ok=True)
                    dst.unlink(missing_ok=True)
                except Exception as exc:
                    try:
                        await progress_message.delete()
                    except TelegramBadRequest:
                        pass
                    await message.answer(
                        f"Не получилось записать кружок: {exc}",
                        reply_markup=chat_keyboard(),
                    )
            else:
                await message.answer(reply, reply_markup=chat_keyboard())
                if result.media_type == "photo" and result.media_prompt:
                    progress_message = await message.answer(
                        "📸 Секунду, сейчас покажусь…",
                        reply_markup=chat_keyboard(),
                    )
                    try:
                        photo_character, photo_bytes, photo_generation_id = await image_service.generate(
                            user_id=message.from_user.id,
                            character_id=character.id,
                            scene=result.media_prompt,
                            pose=result.pose,
                        )
                        # The pose reference is an internal ControlNet input.
                        # Do not send the skeleton/reference image to Telegram.
                        await message.answer_photo(
                            types.BufferedInputFile(photo_bytes, filename="chat_photo.png"),
                        )
                        # Keep the last successfully generated visual state in the
                        # chat FSM. This state is for image continuity, not dialogue.
                        if result.scene_state:
                            await state.update_data(current_scene=json.dumps(result.scene_state, ensure_ascii=False))
                        else:
                            await state.update_data(current_scene=result.media_prompt)
                        await progress_message.delete()
                    except Exception as exc:
                        # progress_message was sent with ReplyKeyboardMarkup, and
                        # Telegram may reject edit_text() for that message. Keep the
                        # error path independent: send a fresh text message instead.
                        try:
                            await progress_message.delete()
                        except TelegramBadRequest:
                            pass
                        await message.answer(
                            f"Не получилось сделать фото: {exc}",
                            reply_markup=chat_keyboard(),
                        )
        except AppError as exc:
            await message.answer(f"❌ Не удалось получить ответ: {exc}", reply_markup=chat_keyboard())
