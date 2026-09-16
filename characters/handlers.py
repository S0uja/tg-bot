from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from characters.service import CharacterService
from characters.keyboards import character_actions, character_list, cancel_to_menu
from characters.states import CharacterCreation
from main.domain.errors import AppError
from main.core.context import TelegramContext

def register(router: Router, ctx: TelegramContext) -> None:
    character_service = ctx.character_service
    edit_ui = ctx.edit_ui
    show_menu = ctx.show_menu
    render_character = ctx.render_character
    render_profile = ctx.render_profile

    


    @router.callback_query(F.data == "menu:create")
    async def create_character_start(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await state.set_state(CharacterCreation.photo)
        await edit_ui(callback.message, 
            "👤 <b>Новый персонаж</b>\n\nПришлите портретное фото персонажа.\n\n"
            "После анализа лица я попрошу только имя — всё остальное можно настроить inline-кнопками.",
            parse_mode="HTML",
            reply_markup=cancel_to_menu(),
        )
        await callback.answer()

    @router.message(CharacterCreation.photo, F.photo)
    async def receive_character_photo(message: types.Message, state: FSMContext):
        try:
            photo = await message.bot.get_file(message.photo[-1].file_id)
            from io import BytesIO
            buffer = BytesIO()
            await message.bot.download_file(photo.file_path, destination=buffer)

            await message.answer("🔎 Анализирую персонажа через vision LLM...\nОпределяю параметры персонажа.")
            analysis = await character_service.analyze_reference(buffer.getvalue())
            await state.update_data(
                face_file_id=message.photo[-1].file_id,
                character_analysis=analysis,
                face_bytes=buffer.getvalue(),
            )
            await state.set_state(CharacterCreation.name)
            await message.answer(
                "✅ Параметры определены.\n\nВведите имя персонажа.",
                parse_mode="HTML",
                reply_markup=cancel_to_menu(),
            )
        except AppError as exc:
            await message.answer(f"Не удалось обработать фото: {exc}")

    @router.message(CharacterCreation.name, F.text)
    async def save_character(message: types.Message, state: FSMContext):
        data = await state.get_data()
        name = message.text.strip()
        analysis = data.get("character_analysis") or {}

        try:
            # First create the DB record to obtain its real character ID.
            # All reference images are then stored under media/character_<id>/.
            character_id = await character_service.create(
                message.from_user.id,
                name,
                "",
                "",
                weight_profile=analysis.get("weight_profile"),
                bust_size=analysis.get("bust_size"),
                age_category=analysis.get("age_category"),
                hairstyle=analysis.get("hairstyle"),
                hair_color=analysis.get("hair_color"),
            )
            face_path = await character_service.save_face(
                data["face_bytes"],
                str(character_id),
            )
            await character_service.set_face_file(character_id, face_path)
            await state.clear()
            await message.answer(
                f"✅ Персонаж «{name[:80]}» сохранён.\n"
                "🔍 Параметры автоматически определены по референсу."
            )
            await render_character(message, message.from_user.id, character_id)
        except AppError as exc:
            await message.answer(str(exc))

    @router.callback_query(F.data == "menu:list")
    async def list_characters(callback: types.CallbackQuery):
        items = await character_service.list(callback.from_user.id)
        if not items:
            await edit_ui(callback.message, 
                "📚 <b>Мои персонажи</b>\n\nПока нет персонажей.",
                reply_markup=character_list([], prefix="character"),
                parse_mode="HTML",
            )
        else:
            await edit_ui(callback.message, 
                "📚 <b>Мои персонажи</b>\n\nВыберите персонажа:",
                reply_markup=character_list([(item.id, item.name) for item in items], prefix="character"),
                parse_mode="HTML",
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("character:"))
    async def character_details(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        character_id = int(callback.data.split(":", 1)[1])
        if not await render_character(callback.message, callback.from_user.id, character_id):
            await callback.answer("Персонаж не найден", show_alert=True)
            return
        await callback.answer()

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
        await edit_ui(
            callback.message,
            f"💬 <b>Чат с «{character.name}»</b>\n\n"
            "Пишите сообщение — персонаж будет отвечать от своего имени.\n"
            "Для выхода используйте кнопку на клавиатуре.",
            parse_mode="HTML",
        )
        await callback.message.answer("💬 Чат активирован.", reply_markup=chat_keyboard())
        await callback.answer("Чат открыт")

