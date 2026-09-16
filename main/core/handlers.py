import logging
from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from main.core.menu_keyboard import menu
from main.core.context import TelegramContext
from main.config import settings
from main.infrastructure.database.connection import Database
from pathlib import Path
import shutil

def register(router: Router, ctx: TelegramContext) -> None:
    edit_ui = ctx.edit_ui
    show_menu = ctx.show_menu
    render_character = ctx.render_character

    @router.message(CommandStart())
    async def start(message: types.Message, state: FSMContext):
        await state.clear()
        await show_menu(message)

    @router.message(Command("clear_db"))
    async def clear_database(message: types.Message, state: FSMContext):
        """Completely clear the SQLite database and data/media files."""
        await state.clear()
        db = Database(settings.database_path)
        counts = await db.clear_all()

        media_root = Path(settings.media_path)
        media_deleted = 0
        if media_root.exists():
            for child in list(media_root.iterdir()):
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    media_deleted += 1
                except OSError:
                    logging.getLogger(__name__).exception(
                        "Failed to remove media item: %s", child
                    )

        total_rows = sum(counts.values())
        await message.answer(
            "🧹 <b>Полная очистка выполнена.</b>\n\n"
            f"🗄 Записей БД удалено: <b>{total_rows}</b>\n"
            f"🗂 Таблиц очищено: <b>{len(counts)}</b>\n"
            f"🖼 Объектов в data/media удалено: <b>{media_deleted}</b>",
            parse_mode="HTML",
        )

    @router.message(Command("menu"))
    async def command_menu(message: types.Message, state: FSMContext):
        await state.clear()
        await show_menu(message)

    @router.callback_query(F.data == "menu:open")
    async def callback_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await edit_ui(callback.message, 
            "🏠 <b>Главное меню</b>\n\nВыберите действие:",
            reply_markup=menu(),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data == "cancel:menu")
    async def cancel_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await edit_ui(callback.message, 
            "🏠 <b>Главное меню</b>\n\nВыберите действие:",
            reply_markup=menu(),
            parse_mode="HTML",
        )
        await callback.answer("Отменено")

    @router.callback_query(F.data.startswith("cancel:character:"))
    async def cancel_to_character_card(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        character_id = int(callback.data.split(":")[-1])
        if not await render_character(callback.message, callback.from_user.id, character_id):
            await callback.answer("Персонаж не найден", show_alert=True)
            return
        await callback.answer("Отменено")

    # ---------- Characters ----------
