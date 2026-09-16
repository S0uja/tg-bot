from __future__ import annotations

from dataclasses import dataclass
from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from app.features.characters.service import CharacterService
from app.features.chat.service import ChatService
from app.features.images.service import ImageGenerationService
from app.features.videos.service import VideoGenerationService
from app.domain.errors import AppError
from app.features.characters.keyboards import character_actions, character_profile_menu
from app.features.images.generation_keyboards import image_actions, video_actions
from app.features.core.menu_keyboard import menu
from app.features.images.states import ImageCreation
from app.features.videos.states import VideoCreation

@dataclass(slots=True)
class TelegramContext:
    character_service: CharacterService
    image_service: ImageGenerationService
    video_service: VideoGenerationService
    chat_service: ChatService

    async def edit_ui(self, message: types.Message, text: str, **kwargs):
        """Show a new UI state without leaving stale media behind.

        Navigation buttons reuse the same Telegram message. If that message is a
        photo/video, editing only its caption leaves the old media visible. For
        normal navigation we therefore delete media messages and send a fresh
        text message. Media regeneration/repeat handlers use edit_media directly
        and are intentionally unaffected by this helper.
        """
        if message.photo or message.video or message.animation or message.document:
            try:
                await message.delete()
            except TelegramBadRequest:
                # If Telegram no longer allows deletion, still try to replace
                # the UI in the normal way below.
                pass
            return await message.answer(text, **kwargs)

        try:
            return await message.edit_text(text, **kwargs)
        except TelegramBadRequest as exc:
            if "there is no text in the message to edit" not in str(exc).lower():
                raise
            return await message.edit_caption(caption=text, **kwargs)

    async def render_generation_message(self, message: types.Message, generation, media: bytes) -> None:
        if generation.kind.value == "image":
            await message.answer_photo(
                types.BufferedInputFile(media, filename=f"image_{generation.id}.png"),
                reply_markup=image_actions(generation.character_id or 0, generation.id, bool(generation.favorite)),
            )
        else:
            await message.answer_video(
                types.BufferedInputFile(media, filename=f"video_{generation.id}.mp4"),
                reply_markup=video_actions(generation.character_id or 0, generation.id, bool(generation.favorite)),
            )

    async def show_menu(self, message: types.Message) -> None:
        await message.answer("🏠 <b>Главное меню</b>\n\nВыберите действие:", reply_markup=menu(), parse_mode="HTML")

    async def render_character(self, message: types.Message, user_id: int, character_id: int) -> bool:
        try:
            item = await self.character_service.get(user_id, character_id)
        except AppError:
            return False
        profile = (
            f"⚖️ Телосложение: {item.weight_profile}" if item.weight_profile
            else (f"⚖️ Вес: {item.weight:g} кг" if item.weight is not None else "⚖️ Телосложение: не задано")
        ) + "\n" + (
            f"💗 Грудь: {item.bust_size}" if item.bust_size is not None
            else (f"💗 Объём груди: {item.bust:g} см" if item.bust is not None else "💗 Грудь: не задана")
        ) + "\n" + (
            f"🎂 Возраст: {item.age_category}" if item.age_category
            else (f"🎂 Возраст: {item.age} лет" if item.age is not None else "🎂 Возраст: не задан")
        ) + "\n" + f"💇 Прическа: {item.hairstyle or 'не задана'}" + "\n" + f"🎨 Цвет волос: {item.hair_color or 'не задан'}" + "\n" + f"🧬 Consistency: {item.consistency_strength or 'medium'}"
        text = f"👤 <b>{item.name}</b>\n\n{item.description or 'Описание не задано.'}\n\n{profile}\n\nID: <code>{item.id}</code>"
        await self.edit_ui(message, text, reply_markup=character_actions(item.id), parse_mode="HTML")
        return True

    async def render_profile(self, message: types.Message, user_id: int, character_id: int) -> bool:
        try:
            item = await self.character_service.get(user_id, character_id)
        except AppError:
            return False
        text = (
            f"⚙️ <b>Параметры персонажа «{item.name}»</b>\n\n"
            "Нажмите на параметр, чтобы изменить его.\n"
            "Изменения сохраняются сразу.\n\n"
            f"⚖️ Телосложение: <b>{item.weight_profile or 'не задано'}</b>\n"
            f"💗 Грудь: <b>{item.bust_size or 'не задана'}</b>\n"
            f"🎂 Возраст: <b>{item.age_category or 'не задан'}</b>\n"
            f"💇 Прическа: <b>{item.hairstyle or 'не задана'}</b>\n"
            f"🎨 Цвет волос: <b>{item.hair_color or 'не задан'}</b>\n"
            f"🧬 Consistency: <b>{item.consistency_strength or 'medium'}</b>"
        )
        await self.edit_ui(message, text, reply_markup=character_profile_menu(item.id, weight=item.weight_profile, bust=item.bust_size, age=item.age_category, hairstyle=item.hairstyle, hair_color=item.hair_color, consistency_strength=item.consistency_strength), parse_mode="HTML")
        return True

    async def show_image_setup(self, message: types.Message, state, user_id: int, character_id: int) -> None:
        await state.clear(); await state.update_data(character_id=character_id); await state.set_state(ImageCreation.prompt)
        await self.edit_ui(message, "🎨 <b>Создание изображения</b>\n\nОпишите сцену, позу, одежду, окружение, камеру и любые дополнительные детали.\n\nИИ сам превратит ваше описание в качественный промпт для CyberRealistic.\n\nНапример: <i>женщина стоит на кухне у окна, смотрит в камеру, футболка и шорты, полный рост, естественный свет</i>", parse_mode="HTML", reply_markup=__import__('app.features.images.generation_keyboards', fromlist=['cancel_input']).cancel_input())

    async def show_video_setup(self, message: types.Message, state, character_id: int) -> None:
        await state.clear(); await state.update_data(character_id=character_id); await state.set_state(VideoCreation.description)
        await self.edit_ui(message, "🎬 <b>Создание видео</b>\n\nОпишите короткое видео: действие, камера, настроение и длительность.\n\nНапример: <i>персонаж идёт навстречу камере, лёгкая улыбка, плавный наезд, 5 секунд</i>", parse_mode="HTML", reply_markup=__import__('app.features.images.generation_keyboards', fromlist=['cancel_input']).cancel_input())
