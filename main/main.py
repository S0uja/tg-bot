from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from main.config import settings
from main.bootstrap.container import create_container
from characters.migration import migrate_telegram_face_files
from main.telegram.bot import build_router


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    configure_logging()
    logging.getLogger(__name__).info(
        "Features: characters=%s chat=%s images=%s videos=%s poses=%s library=%s",
        settings.feature_characters_enabled, settings.feature_chat_enabled,
        settings.feature_images_enabled, settings.feature_videos_enabled,
        settings.feature_poses_enabled, settings.feature_library_enabled,
    )
    container = await create_container()

    bot = Bot(token=settings.bot_token)
    migrated, failed = await migrate_telegram_face_files(
        bot, container.characters, container.storage
    )
    logging.getLogger(__name__).info(
        "Legacy face migration: migrated=%s failed=%s", migrated, failed
    )

    router = build_router(
        character_service=container.character_service,
        image_service=container.image_service,
        video_service=container.video_service,
        chat_service=container.chat_service,
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
