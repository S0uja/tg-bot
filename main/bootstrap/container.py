from __future__ import annotations

from dataclasses import dataclass

from main.config import settings
from main.infrastructure.database.connection import Database
from main.infrastructure.database.repositories.characters import SQLiteCharacterRepository
from main.infrastructure.database.repositories.generations import SQLiteGenerationRepository
from main.infrastructure.ai.llm.comfyui_qwen import ComfyUIQwenLLM
from images.provider.comfyui import ComfyUIImageGenerator
from videos.provider.comfyui import ComfyUIVideoGenerator
from main.infrastructure.storage.local import LocalMediaStorage
from characters.service import CharacterService
from chat.service import ChatService
from images.service import ImageGenerationService
from videos.service import VideoGenerationService
from main.prompts.service import PromptService


@dataclass(slots=True)
class ApplicationContainer:
    """Composition root: constructs the application and its infrastructure adapters."""

    db: Database
    characters: SQLiteCharacterRepository
    generations: SQLiteGenerationRepository
    storage: LocalMediaStorage
    llm: ComfyUIQwenLLM
    image_provider: ComfyUIImageGenerator
    video_provider: ComfyUIVideoGenerator
    character_service: CharacterService
    chat_service: ChatService
    prompt_service: PromptService
    image_service: ImageGenerationService
    video_service: VideoGenerationService


async def create_container() -> ApplicationContainer:
    db = Database(settings.database_path)
    await db.init()

    characters = SQLiteCharacterRepository(db)
    generations = SQLiteGenerationRepository(db)
    storage = LocalMediaStorage(settings.media_path)

    llm = ComfyUIQwenLLM(
        base_url=settings.comfyui_url,
        input_path=settings.comfyui_input_path,
        create_workflow_path=settings.comfyui_llm_workflow_create,
        vision_workflow_path=settings.comfyui_llm_workflow_vision,
        model_match=settings.comfyui_llm_model_match,
        timeout=settings.comfyui_llm_timeout,
        poll_interval=settings.comfyui_llm_poll_interval,
        log_workflow=settings.comfyui_log_workflow,
    )
    image_provider = ComfyUIImageGenerator(
        base_url=settings.comfyui_url,
        workflow_path=settings.comfyui_image_generate_workflow,
        input_path=settings.comfyui_input_path,
        timeout=settings.comfyui_timeout,
        poll_interval=settings.comfyui_poll_interval,
        log_workflow=settings.comfyui_log_workflow,
        reactor_input_faces_index=settings.comfyui_reactor_input_faces_index,
        reactor_workflow_path=settings.comfyui_image_reface_workflow,
        controlnet_openpose_model=settings.comfyui_controlnet_openpose_model,
        controlnet_depth_model=settings.comfyui_controlnet_depth_model,
    )
    video_provider = ComfyUIVideoGenerator(
        base_url=settings.comfyui_url,
        workflow_path=settings.comfyui_video_create_workflow,
        create_workflow_path=settings.comfyui_video_create_workflow,
        animate_workflow_path=settings.comfyui_video_animate_workflow,
        decode_workflow_path=settings.comfyui_video_decode_workflow,
        decode_fallback_workflow_path=settings.comfyui_video_decode_fallback_workflow,
        input_path=settings.comfyui_input_path,
        timeout=settings.comfyui_timeout,
        poll_interval=settings.comfyui_poll_interval,
        log_workflow=settings.comfyui_log_workflow,
        text_encoder_name=settings.comfyui_video_text_encoder,
        reactor_workflow_path=settings.comfyui_video_reface_workflow,
    )

    prompt_service = PromptService(llm)
    chat_service = ChatService(llm, db)
    character_service = CharacterService(characters, llm, storage)
    image_service = ImageGenerationService(
        characters=characters,
        generations=generations,
        prompt_service=prompt_service,
        image_provider=image_provider,
        storage=storage,
        reference_sheet_workflow_path=settings.comfyui_reference_sheet_workflow,
        video_start_frame_workflow_path=settings.comfyui_video_start_frame_workflow,
    )
    video_service = VideoGenerationService(
        characters=characters,
        generations=generations,
        video_provider=video_provider,
        storage=storage,
        prompt_enhancer=llm,
        image_service=image_service,
        i2v_video_provider=video_provider,
        reface_provider=video_provider,
    )

    return ApplicationContainer(
        db=db,
        characters=characters,
        generations=generations,
        storage=storage,
        llm=llm,
        image_provider=image_provider,
        video_provider=video_provider,
        character_service=character_service,
        chat_service=chat_service,
        prompt_service=prompt_service,
        image_service=image_service,
        video_service=video_service,
    )
