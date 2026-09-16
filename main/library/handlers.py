from aiogram import F, Router, types
from main.domain.errors import AppError
from main.core.context import TelegramContext
from main.library.keyboards import library_menu, library_items
from images.generation_keyboards import image_actions, video_actions


def register(router: Router, ctx: TelegramContext) -> None:
    image_service = ctx.image_service
    edit_ui = ctx.edit_ui
    render_generation_message = ctx.render_generation_message

    @router.callback_query(F.data == "menu:library")
    async def open_library(callback: types.CallbackQuery):
        await edit_ui(callback.message, "📚 <b>Библиотека генераций</b>\n\nХраню последние результаты и избранное. Выберите раздел:", reply_markup=library_menu(), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data.in_({"library:recent", "library:favorites"}))
    async def library_section(callback: types.CallbackQuery):
        section = callback.data.split(":", 1)[1]
        items = await image_service.list_recent(callback.from_user.id) if section == "recent" else await image_service.list_favorites(callback.from_user.id)
        title = "🕘 <b>Последние генерации</b>" if section == "recent" else "⭐ <b>Избранное</b>"
        if not items:
            await edit_ui(callback.message, title + "\n\nПока здесь ничего нет.", reply_markup=library_menu(), parse_mode="HTML")
        else:
            await edit_ui(callback.message, title + f"\n\nНайдено: <b>{len(items)}</b>", reply_markup=library_items(items), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data.startswith("library:item:"))
    async def library_item(callback: types.CallbackQuery):
        try:
            generation_id = int(callback.data.rsplit(":", 1)[1])
            generation, media = await image_service.read_generation_media(callback.from_user.id, generation_id)
            await render_generation_message(callback.message, generation, media)
            await callback.answer("Результат открыт")
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("favorite:"))
    async def toggle_generation_favorite(callback: types.CallbackQuery):
        try:
            generation_id = int(callback.data.split(":", 1)[1])
            favorite = await image_service.toggle_favorite(callback.from_user.id, generation_id)
            generation = await image_service.get_generation(callback.from_user.id, generation_id)
            markup = image_actions(generation.character_id or 0, generation.id, favorite) if generation.kind.value == "image" else video_actions(generation.character_id or 0, generation.id, favorite)
            await callback.message.edit_reply_markup(reply_markup=markup)
            await callback.answer("⭐ Добавлено в избранное" if favorite else "Убрано из избранного")
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("prompt:"))
    async def show_generation_prompt(callback: types.CallbackQuery):
        try:
            generation_id = int(callback.data.split(":", 1)[1])
            generation = await image_service.get_generation(callback.from_user.id, generation_id)
            prompt = generation.enhanced_prompt or generation.prompt or "—"
            if len(prompt) > 1800:
                prompt = prompt[:1800] + "…"
            await callback.answer("📝 Промпт:\n" + prompt, show_alert=True)
        except AppError as exc:
            await callback.answer(str(exc), show_alert=True)
