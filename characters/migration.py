from pathlib import Path
from aiogram import Bot

from main.infrastructure.database.repositories.characters import SQLiteCharacterRepository
from main.infrastructure.storage.base import MediaStorage


async def migrate_telegram_face_files(
    bot: Bot,
    characters: SQLiteCharacterRepository,
    storage: MediaStorage,
) -> tuple[int, int]:
    """Convert legacy Telegram file_id values in characters.face_file_id to local files."""
    migrated = 0
    failed = 0
    for character in await characters.list_all():
        value = character.face_file_id
        if not value:
            continue
        if Path(value).is_file():
            continue
        try:
            telegram_file = await bot.get_file(value)
            if not telegram_file.file_path:
                raise RuntimeError("Telegram did not return a file path")
            from io import BytesIO
            buffer = BytesIO()
            await bot.download_file(telegram_file.file_path, destination=buffer)
            local_path = await storage.save(
                buffer.getvalue(), f"character_{character.id}.jpg"
            )
            await characters.set_face_file(character.id, local_path)
            migrated += 1
        except Exception:
            failed += 1
    return migrated, failed
