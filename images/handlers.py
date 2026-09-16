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

    


    @router.callback_query(F.data.startswith("reference:"))
    async def generate_reference(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        character_id = int(callback.data.split(":", 1)[1])
        try:
            await character_service.get(callback.from_user.id, character_id)
            await callback.answer("Генерирую персонажа по reference-позе…")
            await edit_ui(callback.message,
                "🖼 <b>Создаю персонажа по reference-позе…</b>\n\n"
                "Поза берётся из папки <code>data/media/reference</code>.\n"
                "Reference-изображение используется только как ControlNet-поза; пользователю отправляется только готовый персонаж.",
                parse_mode="HTML",
            )
            character, result, generation_id = await image_service.generate(
                user_id=callback.from_user.id,
                character_id=character_id,
                scene=(
                    "Generate the character using the selected reference pose. "
                    "Use the reference only to control the body pose. Preserve the character's "
                    "identity, face, hair, body proportions, clothing and established visual appearance. "
                    "Return one realistic final image of the character."
                ),
                pose="reference",
            )
            await callback.message.answer_photo(
                types.BufferedInputFile(result, filename="reference.png"),
                caption="🖼 Reference готов.",
                reply_markup=image_actions(character.id, generation_id),
            )
        except AppError as exc:
            await edit_ui(callback.message, f"❌ Не удалось создать reference: {exc}", reply_markup=character_actions(character_id))


    @router.callback_query(F.data == "menu:image")
    async def image_start(callback: types.CallbackQuery, state: FSMContext):
        items = await character_service.list(callback.from_user.id)
        if not items:
            await edit_ui(callback.message, "🎨 <b>Создание изображения</b>\n\nСначала создайте персонажа.", reply_markup=menu(), parse_mode="HTML")
        else:
            await state.clear()
            await state.set_state(ImageCreation.character)
            await edit_ui(callback.message, 
                "🎨 <b>Создание изображения</b>\n\nВыберите персонажа:",
                reply_markup=character_list([(item.id, item.name) for item in items], prefix="imagechar"),
                parse_mode="HTML",
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("imagefromchar:"))
    async def image_from_character(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            await character_service.get(callback.from_user.id, character_id)
            await show_image_setup(callback.message, state, callback.from_user.id, character_id)
            await callback.answer()
        except AppError:
            await callback.answer("Персонаж не найден", show_alert=True)

    @router.callback_query(ImageCreation.character, F.data.startswith("imagechar:"))
    async def image_character(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        await show_image_setup(callback.message, state, callback.from_user.id, character_id)
        await callback.answer()

    @router.message(ImageCreation.prompt, F.text)
    async def generate_image(message: types.Message, state: FSMContext):
        data = await state.get_data()
        await message.answer("⏳ Обрабатываю описание и готовлю изображение…")
        try:
            character, result, generation_id = await image_service.generate(
                user_id=message.from_user.id,
                character_id=data["character_id"],
                scene=message.text,
            )
            # The selected pose reference is internal to ControlNet and is not
            # exposed to the user. Only the final generated image is sent.
            await message.answer_photo(
                types.BufferedInputFile(result, filename="image.png"),
                reply_markup=image_actions(character.id, generation_id),
            )
        except AppError as exc:
            await message.answer(f"❌ Не удалось создать изображение: {exc}")
        finally:
            await state.clear()

    @router.callback_query(F.data.startswith("image_change:"))
    async def regenerate_image(callback: types.CallbackQuery):
        _, character_id, generation_id = callback.data.split(":", 2)
        character_id = int(character_id)
        generation_id = int(generation_id)
        await callback.answer("Повторно отрисовываю…")
        if callback.message.photo:
            current_file_id = callback.message.photo[-1].file_id
            await callback.message.edit_media(
                media=types.InputMediaPhoto(media=current_file_id, has_spoiler=True),
                reply_markup=image_actions(character_id, generation_id),
            )
        try:
            character, result, new_generation_id = await image_service.regenerate(
                callback.from_user.id, character_id, generation_id
            )
            await callback.message.edit_media(
                media=types.InputMediaPhoto(
                    media=types.BufferedInputFile(result, filename="image.png"),
                    has_spoiler=False,
                ),
                reply_markup=image_actions(character.id, new_generation_id),
            )
        except AppError as exc:
            await callback.answer(f"Не удалось повторить: {exc}", show_alert=True)

    @router.callback_query(F.data.startswith("image_animate:"))
    async def animate_image_start(callback: types.CallbackQuery, state: FSMContext):
        _, character_id, generation_id = callback.data.split(":", 2)
        try:
            character_id = int(character_id)
            generation_id = int(generation_id)
            generation = await image_service.get_image_generation(
                callback.from_user.id, generation_id
            )
            if generation.character_id != character_id:
                raise AppError("Изображение не принадлежит выбранному персонажу.")
            await state.clear()
            await state.update_data(
                character_id=character_id,
                source_generation_id=generation_id,
            )
            await state.set_state(AnimationCreation.prompt)
            await edit_ui(
                callback.message,
                "🎬 <b>Анимация изображения</b>\n\n"
                "Опишите, что должно происходить на изображении.\n\n"
                "Например: <i>медленно поворачивает голову к камере, слегка улыбается, "
                "камера неподвижна</i>",
                parse_mode="HTML",
                reply_markup=cancel_input(),
            )
            await callback.answer("Укажите движение")
        except (AppError, ValueError) as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.message(AnimationCreation.prompt, F.text)
    async def animate_image(message: types.Message, state: FSMContext):
        data = await state.get_data()
        progress_message = await message.answer("🎬 <b>Анимация изображения</b>\n\n⏳ Подготовка…", parse_mode="HTML")
        async def progress(stage: str):
            try: await progress_message.edit_text(stage, parse_mode="HTML")
            except TelegramBadRequest: pass
        try:
            character, result, generation_id = await video_service.generate_from_image(
                progress_callback=progress,
                user_id=message.from_user.id,
                character_id=data["character_id"],
                generation_id=data["source_generation_id"],
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
