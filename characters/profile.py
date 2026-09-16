from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from characters.service import CharacterService
from characters.keyboards import (
    HAIR_COLOR_OPTIONS, HAIRSTYLE_OPTIONS, age_category_choices, bust_size_choices,
    character_actions, cancel_to_character, consistency_choices, character_profile_menu,
    delete_confirmation, hair_color_choices, hairstyle_choices, weight_profile_choices,
)
from main.domain.errors import AppError
from main.core.context import TelegramContext
from main.core.menu_keyboard import menu
from characters.states import CharacterEdit, CharacterProfileEdit


def register(router: Router, ctx: TelegramContext) -> None:
    character_service = ctx.character_service
    edit_ui = ctx.edit_ui
    show_menu = ctx.show_menu
    render_character = ctx.render_character
    render_profile = ctx.render_profile

    


    @router.callback_query(F.data.startswith("clonecharacter:"))
    async def clone_character(callback: types.CallbackQuery):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            new_id = await character_service.duplicate(callback.from_user.id, character_id)
            await render_character(callback.message, callback.from_user.id, new_id)
            await callback.answer("🧬 Персонаж продублирован")
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("deletecharacter:"))
    async def request_delete(callback: types.CallbackQuery):
        character_id = int(callback.data.split(":", 1)[1])
        try:
            item = await character_service.get(callback.from_user.id, character_id)
        except AppError:
            await callback.answer("Персонаж не найден", show_alert=True)
            return
        await edit_ui(callback.message, 
            f"🗑 <b>Удалить персонажа «{item.name}»?</b>\n\nЭто действие нельзя отменить.",
            reply_markup=delete_confirmation(character_id),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("confirmdelete:"))
    async def delete_character(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        character_id = int(callback.data.split(":", 1)[1])
        deleted = await character_service.delete(callback.from_user.id, character_id)
        await edit_ui(callback.message, 
            "✅ Персонаж удалён." if deleted else "Персонаж не найден.",
            reply_markup=menu() if deleted else character_actions(character_id),
        )
        await callback.answer()

    # ---------- Character profile ----------

    @router.callback_query(F.data.startswith("editprofile:"))
    async def edit_profile_start(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        character_id = int(callback.data.split(":", 1)[1])
        if not await render_profile(callback.message, callback.from_user.id, character_id):
            await callback.answer("Персонаж не найден", show_alert=True)
            return
        await callback.answer()

    @router.callback_query(F.data.startswith("profile:consistency:"))
    async def profile_consistency(callback: types.CallbackQuery):
        character_id=int(callback.data.split(":")[-1])
        item=await character_service.get(callback.from_user.id, character_id)
        await edit_ui(callback.message, "🧬 <b>Character consistency</b>\n\nВыберите силу фиксации identity.", reply_markup=consistency_choices(character_id, item.consistency_strength), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data.startswith("profileconsistency:"))
    async def set_profile_consistency(callback: types.CallbackQuery):
        _, character_id, value=callback.data.split(":",2)
        await character_service.update(callback.from_user.id, int(character_id), consistency_strength=value)
        await render_profile(callback.message, callback.from_user.id, int(character_id))
        await callback.answer("🧬 Consistency сохранён")

    @router.callback_query(F.data.startswith("profile:weight:"))
    async def profile_weight_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(CharacterProfileEdit.weight)
        character_id = int(callback.data.split(":")[-1])
        character = await character_service.get(callback.from_user.id, character_id)
        await edit_ui(callback.message, 
            f"⚖️ <b>Телосложение «{character.name}»</b>\n\nВыберите вариант:",
            reply_markup=weight_profile_choices(character_id, character.weight_profile),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("profileweight:"))
    async def edit_profile_weight(callback: types.CallbackQuery, state: FSMContext):
        _, character_id, value = callback.data.split(":", 2)
        try:
            await character_service.update(callback.from_user.id, int(character_id), weight_profile=value)
            await state.clear()
            await render_profile(callback.message, callback.from_user.id, int(character_id))
            await callback.answer("Телосложение сохранено")
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("profile:bust:"))
    async def profile_bust_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(CharacterProfileEdit.bust)
        character_id = int(callback.data.split(":")[-1])
        character = await character_service.get(callback.from_user.id, character_id)
        await edit_ui(callback.message, 
            f"💗 <b>Размер груди «{character.name}»</b>\n\nВыберите размер:",
            reply_markup=bust_size_choices(character_id, character.bust_size),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("profilebust:"))
    async def edit_profile_bust(callback: types.CallbackQuery, state: FSMContext):
        _, character_id, value = callback.data.split(":", 2)
        try:
            await character_service.update(callback.from_user.id, int(character_id), bust_size=int(value))
            await state.clear()
            await render_profile(callback.message, callback.from_user.id, int(character_id))
            await callback.answer("Размер груди сохранён")
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("profile:age:"))
    async def profile_age_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(CharacterProfileEdit.age)
        character_id = int(callback.data.split(":")[-1])
        character = await character_service.get(callback.from_user.id, character_id)
        await edit_ui(callback.message, 
            f"🎂 <b>Возрастной профиль «{character.name}»</b>\n\nВыберите категорию:",
            reply_markup=age_category_choices(character_id, character.age_category),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("profileage:"))
    async def edit_profile_age(callback: types.CallbackQuery, state: FSMContext):
        _, character_id, value = callback.data.split(":", 2)
        try:
            await character_service.update(callback.from_user.id, int(character_id), age_category=value)
            await state.clear()
            await render_profile(callback.message, callback.from_user.id, int(character_id))
            await callback.answer("Возрастной профиль сохранён")
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("profile:hair:"))
    async def profile_hair_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(CharacterProfileEdit.hairstyle)
        character_id = int(callback.data.split(":")[-1])
        character = await character_service.get(callback.from_user.id, character_id)
        await edit_ui(callback.message, 
            f"💇 <b>Прическа «{character.name}»</b>\n\nВыберите вариант:",
            reply_markup=hairstyle_choices(character_id, character.hairstyle),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("profilehair:"))
    async def edit_profile_hair(callback: types.CallbackQuery, state: FSMContext):
        _, character_id, index = callback.data.split(":", 2)
        try:
            value = HAIRSTYLE_OPTIONS[int(index)][0]
            await character_service.update(callback.from_user.id, int(character_id), hairstyle=value)
            await state.clear()
            await render_profile(callback.message, callback.from_user.id, int(character_id))
            await callback.answer("Прическа сохранена")
        except (AppError, IndexError, ValueError) as exc:
            await callback.answer(str(exc) or "Недопустимая прическа", show_alert=True)

    @router.callback_query(F.data.startswith("profile:color:"))
    async def profile_color_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(CharacterProfileEdit.hair_color)
        character_id = int(callback.data.split(":")[-1])
        character = await character_service.get(callback.from_user.id, character_id)
        await edit_ui(callback.message, 
            f"🎨 <b>Цвет волос «{character.name}»</b>\n\nВыберите цвет:",
            reply_markup=hair_color_choices(character_id, character.hair_color),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("profilehaircolor:"))
    async def edit_profile_hair_color(callback: types.CallbackQuery, state: FSMContext):
        _, character_id, index = callback.data.split(":", 2)
        try:
            value = HAIR_COLOR_OPTIONS[int(index)][0]
            await character_service.update(callback.from_user.id, int(character_id), hair_color=value)
            await state.clear()
            await render_profile(callback.message, callback.from_user.id, int(character_id))
            await callback.answer("Цвет волос сохранён")
        except (AppError, IndexError, ValueError) as exc:
            await callback.answer(str(exc) or "Недопустимый цвет волос", show_alert=True)

    @router.callback_query(F.data.startswith("editname:"))
    async def edit_name(callback: types.CallbackQuery, state: FSMContext):
        character_id = int(callback.data.split(":", 1)[1])
        await state.set_state(CharacterEdit.value)
        await state.update_data(character_id=character_id, field="name")
        await edit_ui(callback.message, 
            "✏️ <b>Новое имя</b>\n\nВведите новое имя персонажа.",
            parse_mode="HTML",
            reply_markup=cancel_to_character(character_id),
        )
        await callback.answer()

    @router.message(CharacterEdit.value, F.text)
    async def save_edit(message: types.Message, state: FSMContext):
        data = await state.get_data()
        if data.get("field") != "name":
            await state.clear()
            await message.answer("Этот параметр больше не редактируется здесь.")
            return
        try:
            updated = await character_service.update(message.from_user.id, data["character_id"], name=message.text)
            await state.clear()
            await message.answer("✅ Имя сохранено." if updated else "Персонаж не найден.")
        except AppError as exc:
            await message.answer(str(exc))

    # ---------- Images ----------

