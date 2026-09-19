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

    


    @router.callback_query(F.data.startswith("chat:"))
    async def chat_start(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            character = await character_service.get(callback.from_user.id, character_id)
            await state.clear()
            await state.set_state(CharacterChat.chatting)
            await state.update_data(character_id=character_id)
            await edit_ui(callback.message, f"💬 <b>Чат с {character.name}</b>\n\nНапиши сообщение.", reply_markup=chat_keyboard(), parse_mode="HTML")
            await callback.answer()
        except AppError:
            await callback.answer("Персонаж не найден", show_alert=True)

    @router.message(CharacterChat.chatting, F.text & ~F.text.startswith("/"))
    async def chat_message(message: types.Message, state: FSMContext):
        user_text = message.text or ""
        data = await state.get_data()
        character_id = data.get("character_id")
        if not character_id:
            await message.answer("❌ Персонаж не выбран.", reply_markup=chat_keyboard())
            return

        try:
            character = await character_service.get(message.from_user.id, character_id)
            previous_scene = data.get("current_scene", "")
            result: ChatReply = await chat_service.reply(
                user_id=message.from_user.id,
                character=character,
                user_text=user_text,
                previous_scene=previous_scene,
            )

            explicit_photo = result.media_type == "photo"
            explicit_video = result.media_type == "video"

            if explicit_photo and not result.media_prompt:
                result = ChatReply(
                    result.reply,
                    "photo",
                    result.media_prompt or (
                        "Create a single realistic photo of the character. "
                        "Preserve face, hair, body proportions, clothing and environment. "
                        "Natural pose, coherent full scene."
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

            if result.scene_state:
                await state.update_data(current_scene=json.dumps(result.scene_state, ensure_ascii=False))

            reply = result.reply.strip() or "Не знаю, что сказать 😅"
            await chat_service.remember(message.from_user.id, character.id, "user", user_text)
            await chat_service.remember(message.from_user.id, character.id, "assistant", reply)

            if result.media_type == "video":
                await message.answer(reply, reply_markup=chat_keyboard())
                try:
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
                                "medium-full shot, body and legs clearly visible, enough space for the requested movement"
                            )
                        else:
                            framing = (
                                "medium-full shot, upper body and both hands clearly visible, enough space for natural movement"
                            )
                        return (
                            "Create the exact starting frame for a short video. "
                            f"{framing}. "
                            "Keep the character centered and fully coherent. "
                            "Preserve face, hair, body proportions, clothing and environment. "
                            f"Current scene context: {previous_scene}. "
                            f"Required action/motion: {action}. "
                            "The starting frame must already contain the body configuration needed for the first motion."
                        )

                    start_scene = build_video_start_scene(action_plan, previous_scene)
                    _, start_bytes, _ = await image_service.generate(
                        user_id=message.from_user.id,
                        character_id=character.id,
                        scene=start_scene,
                    )

                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp.write(start_bytes)
                        start_path = Path(tmp.name)

                    try:
                        video_character, video_bytes, video_generation_id = await video_service.generate(
                            user_id=message.from_user.id,
                            character_id=character.id,
                            prompt=action_plan,
                            start_frame=start_bytes,
                            start_frame_path=start_path,
                        )
                        await message.answer_video(
                            types.BufferedInputFile(video_bytes, filename="chat_video.mp4"),
                            caption=reply,
                        )
                    finally:
                        start_path.unlink(missing_ok=True)
                except Exception as exc:
                    await message.answer(f"Не получилось сделать видео: {exc}", reply_markup=chat_keyboard())
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
                            # Chat always uses the dedicated selfi control folder.
                            # The semantic pose returned by Qwen is intentionally not
                            # used for physical pose-file routing here.
                            pose="selfie",
                        )
                        await message.answer_photo(
                            types.BufferedInputFile(photo_bytes, filename="chat_photo.png"),
                        )
                        if result.scene_state:
                            await state.update_data(current_scene=json.dumps(result.scene_state, ensure_ascii=False))
                        else:
                            await state.update_data(current_scene=result.media_prompt)
                        await progress_message.delete()
                    except Exception as exc:
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
