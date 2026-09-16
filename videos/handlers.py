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

    


    @router.callback_query(F.data.startswith("video_continue:"))
    async def continue_video(callback: types.CallbackQuery):
        _, character_id, generation_id = callback.data.split(":", 2)
        character_id, generation_id = int(character_id), int(generation_id)
        await callback.answer("Продолжаю видео…")
        progress_message = await callback.message.answer("🎬 <b>Продолжение видео</b>\n\n⏳ Подготовка…", parse_mode="HTML")
        async def progress(stage: str):
            try: await progress_message.edit_text(stage, parse_mode="HTML")
            except TelegramBadRequest: pass
        try:
            character, result, new_id = await video_service.continue_video(user_id=callback.from_user.id, character_id=character_id, generation_id=generation_id, progress_callback=progress)
            await callback.message.answer_video(types.BufferedInputFile(result, filename="video.mp4"), reply_markup=video_actions(character.id, new_id))
            try: await progress_message.delete()
            except TelegramBadRequest: pass
        except AppError as exc:
            await progress_message.edit_text(f"❌ Не удалось продолжить видео: {exc}", parse_mode="HTML")

    @router.callback_query(F.data.startswith("video_repeat:"))
    async def repeat_video(callback: types.CallbackQuery):
        _, character_id, generation_id = callback.data.split(":", 2)
        character_id = int(character_id)
        generation_id = int(generation_id)
        await callback.answer("Повторно генерирую видео…")
        # Immediately hide the currently displayed media while the replacement is generated.
        if callback.message.video:
            current_file_id = callback.message.video.file_id
            await callback.message.edit_media(
                media=types.InputMediaVideo(media=current_file_id, has_spoiler=True),
                reply_markup=video_actions(character_id, generation_id),
            )
        try:
            character, result, new_generation_id = await video_service.regenerate_exact(
                user_id=callback.from_user.id,
                character_id=character_id,
                generation_id=generation_id,
            )
            await callback.message.edit_media(
                media=types.InputMediaVideo(
                    media=types.BufferedInputFile(result, filename="video.mp4"),
                    has_spoiler=False,
                ),
                reply_markup=video_actions(character.id, new_generation_id),
            )
        except AppError as exc:
            await callback.answer(f"Не удалось повторить: {exc}", show_alert=True)

    # ---------- Videos ----------

    @router.callback_query(F.data == "menu:video")
    async def video_start(callback: types.CallbackQuery, state: FSMContext):
        items = await character_service.list(callback.from_user.id)
        if not items:
            await edit_ui(callback.message, "🎬 <b>Создание видео</b>\n\nСначала создайте персонажа.", reply_markup=menu(), parse_mode="HTML")
        else:
            await state.clear()
            await state.set_state(VideoCreation.character)
            await edit_ui(callback.message, 
                "🎬 <b>Создание видео</b>\n\nВыберите персонажа:",
                reply_markup=character_list([(item.id, item.name) for item in items], prefix="videochar"),
                parse_mode="HTML",
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("videofromchar:"))
    async def video_from_character(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            await character_service.get(callback.from_user.id, character_id)
            await show_video_setup(callback.message, state, character_id)
            await callback.answer()
        except AppError:
            await callback.answer("Персонаж не найден", show_alert=True)

    @router.callback_query(VideoCreation.character, F.data.startswith("videochar:"))
    async def video_character(callback: types.CallbackQuery, state: FSMContext):
        await show_video_setup(callback.message, state, int(callback.data.split(":", 1)[1]))
        await callback.answer()

    @router.message(VideoCreation.description, F.text)
    async def generate_video(message: types.Message, state: FSMContext):
        data = await state.get_data()
        progress_message = await message.answer("🎬 <b>Создание видео</b>\n\n⏳ Подготовка…", parse_mode="HTML")
        async def progress(stage: str):
            try: await progress_message.edit_text(stage, parse_mode="HTML")
            except TelegramBadRequest: pass
        try:
            character, result, generation_id = await video_service.generate(
                progress_callback=progress,
                user_id=message.from_user.id,
                character_id=data["character_id"],
                description=message.text,
            )
            await message.answer_video(
                types.BufferedInputFile(result, filename="video.mp4"),
                reply_markup=video_actions(character.id, generation_id),
            )
        except AppError as exc:
            await message.answer(f"❌ Не удалось создать видео: {exc}")
        finally:
            await state.clear()

    return router
