from __future__ import annotations

from aiogram import Router

from main.config import settings
from main.core.context import TelegramContext
from main.core.handlers import register as register_core
from characters.service import CharacterService
from chat.service import ChatService
from images.service import ImageGenerationService
from videos.service import VideoGenerationService


def build_router(
    *,
    character_service: CharacterService,
    image_service: ImageGenerationService,
    video_service: VideoGenerationService,
    chat_service: ChatService,
) -> Router:
    """Build the single bot router from independently switchable features.

    The bot remains one application/process. Feature code is physically separated
    in top-level module folders and can be enabled/disabled via .env.
    """
    router = Router()
    ctx = TelegramContext(
        character_service=character_service,
        image_service=image_service,
        video_service=video_service,
        chat_service=chat_service,
    )

    # Core always provides /start, /menu and navigation.
    register_core(router, ctx)

    if settings.feature_characters_enabled:
        from characters.handlers import register as register_characters
        from characters.profile import register as register_profile
        register_characters(router, ctx)
        register_profile(router, ctx)

    if settings.feature_chat_enabled:
        from chat.handlers import register as register_chat
        register_chat(router, ctx)

    if settings.feature_images_enabled:
        from images.handlers import register as register_images
        register_images(router, ctx)

    if settings.feature_videos_enabled:
        from videos.handlers import register as register_videos
        register_videos(router, ctx)

    if settings.feature_poses_enabled:
        from poses.handlers import register as register_poses
        register_poses(router, ctx)

    if settings.feature_library_enabled:
        from main.library.handlers import register as register_library
        register_library(router, ctx)

    return router
