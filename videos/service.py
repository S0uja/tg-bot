from main.domain.enums import GenerationKind, GenerationStatus
from main.domain.errors import NotFoundError, ProviderError
from main.domain.models import Character
from images.service import ImageGenerationService
from videos.provider.base import VideoGenerator
from main.infrastructure.ai.llm.base import PromptEnhancer
from main.infrastructure.database.repositories.characters import CharacterRepository
from main.infrastructure.database.repositories.generations import GenerationRepository
from main.infrastructure.storage.base import MediaStorage


from videos.duration import extract_video_duration, duration_from_marker
from typing import Awaitable, Callable
import asyncio
import subprocess
import tempfile
from pathlib import Path
import re
import logging
import random

from poses.config import normalize_pose_image, poses_root, resolve_pose


def _default_video_duration_frames(description: str, extracted_frames: int) -> int:
    """Use ~10 seconds unless the user explicitly requested another duration.

    LTXV works in frame counts of 8n+1 at 24 FPS. 241 frames is ~10.04s.
    The duration parser may return the workflow default (97 frames) when no
    duration marker is present, so we must make the default explicit here.
    """
    text = (description or "").lower()
    explicit = re.search(
        r"\b\d+(?:[\.,]\d+)?\s*(?:секунд(?:а|ы)?|сек\.?|с\.?|"
        r"second(?:s)?|sec(?:s)?)\b",
        text,
    )
    if explicit:
        return extracted_frames
    return 241



def _start_frame_pose_lock(scene: str) -> str:
    """Add deterministic composition constraints for poses that must be visible in frame 0."""
    text = (scene or "").lower()
    if any(key in text for key in (
        "лежу на спине", "лежит на спине", "лёжа на спине",
        "лежа на спине", "на спине",
    )):
        return (
            "START FRAME POSE LOCK: one adult woman is already lying flat on her back "
            "on a bed or sofa, full body visible from head to feet, head and back resting "
            "on the surface, body aligned horizontally with the surface, legs extended "
            "along the surface, natural relaxed pose, camera positioned above or at a "
            "clear side angle that visibly shows the horizontal lying posture. "
            "The subject must NOT be standing, sitting, kneeling, crouching, or posing upright. "
            "Only one person and one body are present in the entire frame."
        )
    return ""

def _select_random_pose(scene: str) -> tuple[str, bytes | None]:
    """Select a random OpenPose map using the shared env-configured registry."""
    category = resolve_pose(scene=scene) or "stand"
    pose_dir = poses_root() / category
    candidates = [
        p for p in pose_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    ] if pose_dir.exists() else []
    if not candidates:
        logger.warning("[POSE] No pose files found: category=%s dir=%s", category, pose_dir)
        return category, None
    selected = random.choice(candidates)
    logger.info("[POSE] Selected random OpenPose: category=%s file=%s", category, selected)
    return category, normalize_pose_image(selected.read_bytes())


class VideoGenerationService:
    def __init__(self, characters: CharacterRepository, generations: GenerationRepository, video_provider: VideoGenerator, storage: MediaStorage, prompt_enhancer: PromptEnhancer, image_service: ImageGenerationService, i2v_video_provider: VideoGenerator, reface_provider: VideoGenerator | None = None) -> None:
        self.characters = characters
        self.generations = generations
        self.video_provider = video_provider
        self.i2v_video_provider = i2v_video_provider
        self.reface_provider = reface_provider or i2v_video_provider
        self.storage = storage
        self.prompt_enhancer = prompt_enhancer
        self.image_service = image_service

    async def generate(
        self,
        *,
        user_id: int,
        character_id: int,
        description: str,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ):
        """Create a video via hidden start-frame generation followed by LTXV I2V.

        The start frame is an internal intermediate only: it is never saved as a
        user-facing generation and is never sent to Telegram.
        """
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        generation_id = await self.generations.create(
            user_id=user_id,
            character_id=character.id,
            kind=GenerationKind.VIDEO,
            prompt=description,
            provider="comfyui-ltxv",
        )
        try:
            await self.generations.set_status(generation_id, GenerationStatus.PROCESSING)
            if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Подготовка промптов…")
            clean_description, duration_frames = extract_video_duration(description)
            duration_frames = _default_video_duration_frames(description, duration_frames)
            logger = logging.getLogger("video_generation")
            logger.info("[VIDEO] Effective duration: %s frames (~%.2fs at 24 FPS)", duration_frames, duration_frames / 24.0)

            # One LLM call prepares both prompts. The start frame remains an
            # internal intermediate and is never sent to Telegram.
            character_ctx = await self.characters.get(user_id, character_id)
            from main.domain.models import ImagePromptContext
            frame_ctx = ImagePromptContext(
                character_description=character_ctx.description,
                scene=clean_description,
                weight_profile=character_ctx.weight_profile,
                bust_size=character_ctx.bust_size,
                age_category=character_ctx.age_category,
                hairstyle=character_ctx.hairstyle,
                hair_color=character_ctx.hair_color,
            )
            # Qwen3-VL text workflow creates the opening-frame prompt. A second,
            # vision-capable Qwen3-VL pass will inspect the generated frame below
            # and turn the user's requested action into an LTXV motion prompt.
            image_prompt = await self.prompt_enhancer.enhance_image_prompt(frame_ctx)
            # Add authoritative structured character profile to the image prompt.
            from main.prompts.service import profile_prompt
            pose_lock = _start_frame_pose_lock(clean_description)
            image_prompt_text = ", ".join(
                p for p in (image_prompt, profile_prompt(frame_ctx), pose_lock) if p
            )
            if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Промпт готов ✓\n🖼 Создаю стартовый кадр…")
            face_bytes = await self.storage.read(character.face_file_id) if character.face_file_id else None
            pose_category, pose_bytes = _select_random_pose(clean_description)
            logger.info(
                "[POSE] Category=%s | random OpenPose=%s",
                pose_category,
                "selected" if pose_bytes else "NONE",
            )
            if pose_bytes is None:
                raise ProviderError(
                    f"Не найдена OpenPose-карта для категории '{pose_category}' "
                    f"в проекте. Ожидается папка poses/{pose_category}/."
                )
            start_image = await self.image_service.image_provider.generate(
                character=character,
                prompt=image_prompt_text,
                reference_image=face_bytes,
                workflow_path="videos/workflows/video_start_frame_generate_api.json",
                pose_image=pose_bytes,
            )
            logger.info("[VIDEO] Start frame generated successfully: %d bytes", len(start_image))
            if face_bytes:
                start_image = await self.image_service.image_provider.reface(
                    image=start_image, face_reference=face_bytes
                )
            identity_bytes = (
                await self.storage.read(character.face_file_id)
                if character.face_file_id else None
            )

            # The actual generated opening frame is the visual ground truth for
            # motion generation. Qwen3-VL now sees that exact image.
            if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Промпт готов ✓\n🖼 Стартовый кадр готов ✓\n👁 Анализирую кадр…")
            video_prompt = await self.prompt_enhancer.translate_video_prompt(clean_description, start_image)

            if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Промпт ✓\n🖼 Стартовый кадр ✓\n👁 Motion prompt ✓\n🎞 Генерирую LTXV…")
            result = await self.video_provider.generate(
                character=character,
                prompt=video_prompt,
                reference_image=start_image,
                identity_image=identity_bytes,
                duration_frames=duration_frames,
                workflow_path="videos/workflows/ltxvideo-i2v-motion-create-video.json",
                strength=0.875,
            )

            if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Промпт ✓\n🖼 Стартовый кадр ✓\n🎞 LTXV готов ✓\n🎨 VideoVAE декодирует…")
            # The LTXV graph is kept VRAM-safe: video ReActor is not embedded
            # in the generation graph. The returned payload is video only.
            if identity_bytes:
                if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Промпт ✓\n🖼 Кадр ✓\n🎞 LTXV ✓\n🎨 VideoVAE ✓\n👤 Улучшаю identity…")
                result = await self.reface_provider.reface(
                    video=result,
                    face_reference=identity_bytes,
                )

            if progress_callback: await progress_callback("🎬 <b>Создание видео</b>\n\n🧠 Промпт ✓\n🖼 Кадр ✓\n🎞 LTXV ✓\n🎨 VideoVAE ✓\n👤 ReActor ✓\n📦 Сохраняю…")
            result_path = await self.storage.save(
                result,
                f"generation_{generation_id}.mp4",
            )
            await self.generations.complete(
                generation_id,
                result_path=result_path,
                enhanced_prompt=(
                    f"START_FRAME: internal\n"
                    f"DURATION_FRAMES: {duration_frames}\n"
                    f"VIDEO: {video_prompt}"
                ),
            )
            return character, result, generation_id
        except Exception as exc:
            await self.generations.fail(generation_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc

    async def generate_from_image(
        self,
        *,
        user_id: int,
        character_id: int,
        generation_id: int | None = None,
        description: str = "",
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
        source_image: bytes | None = None,
    ) -> tuple[Character, bytes, int]:
        """Animate an already generated image directly, without creating a new start frame."""
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        source = await self.generations.get(user_id, generation_id) if generation_id is not None else None
        if source_image is None:
            if source is None or source.kind != GenerationKind.IMAGE or source.character_id != character_id:
                raise NotFoundError("Исходное изображение не найдено.")
            if not source.result_path:
                raise NotFoundError("Файл исходного изображения не найден.")

        video_generation_id = await self.generations.create(
            user_id=user_id,
            character_id=character.id,
            kind=GenerationKind.VIDEO,
            prompt=description,
            provider="comfyui-ltxv",
        )
        try:
            await self.generations.set_status(video_generation_id, GenerationStatus.PROCESSING)
            if progress_callback: await progress_callback("🎬 <b>Анимация изображения</b>\n\n🧠 Анализирую кадр…")
            if source_image is None:
                source_image = await self.storage.read(source.result_path)
            clean_description, duration_frames = extract_video_duration(description)
            duration_frames = _default_video_duration_frames(description, duration_frames)
            logger = logging.getLogger("video_generation")
            logger.info("[VIDEO] Effective duration: %s frames (~%.2fs at 24 FPS)", duration_frames, duration_frames / 24.0)
            # Let the vision-capable Qwen model inspect the actual image before writing
            # the LTXV prompt. This makes animation instructions grounded in the selected frame.
            video_prompt = await self.prompt_enhancer.translate_video_prompt(clean_description, source_image)
            identity_bytes = None
            if character.face_file_id:
                identity_bytes = await self.storage.read(character.face_file_id)

            if progress_callback: await progress_callback("🎬 <b>Анимация изображения</b>\n\n🧠 Промпт готов ✓\n🎞 Генерирую LTXV…")
            result = await self.i2v_video_provider.generate(
                character=character,
                prompt=video_prompt,
                reference_image=source_image,
                identity_image=identity_bytes,
                duration_frames=duration_frames,
                workflow_path="videos/workflows/ltxvideo-i2v-motion-animate-image.json",
                strength=0.95,
            )
            if progress_callback: await progress_callback("🎬 <b>Анимация изображения</b>\n\n🧠 Промпт ✓\n🎞 LTXV ✓\n🎨 VideoVAE ✓\n👤 ReActor…")
            if identity_bytes:
                result = await self.reface_provider.reface(video=result, face_reference=identity_bytes)
            result_path = await self.storage.save(result, f"generation_{video_generation_id}.mp4")
            await self.generations.complete(
                video_generation_id,
                result_path=result_path,
                enhanced_prompt=f"SOURCE IMAGE GENERATION: {generation_id}\nDURATION_FRAMES: {duration_frames}\nVIDEO: {video_prompt}",
            )
            return character, result, video_generation_id
        except Exception as exc:
            await self.generations.fail(video_generation_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc

    async def continue_video(
        self, *, user_id: int, character_id: int, generation_id: int,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[Character, bytes, int]:
        """Continue a completed video from its final frame."""
        source = await self.generations.get(user_id, generation_id)
        if source is None or source.kind != GenerationKind.VIDEO or source.character_id != character_id or not source.result_path:
            raise NotFoundError("Исходное видео не найдено.")
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")
        source_video = await self.storage.read(source.result_path)
        tmp_video = Path(tempfile.gettempdir()) / f"tg_continue_{generation_id}_{int(asyncio.get_running_loop().time()*1000)}.mp4"
        tmp_frame = tmp_video.with_suffix(".png")
        tmp_video.write_bytes(source_video)
        new_id = await self.generations.create(user_id=user_id, character_id=character_id, kind=GenerationKind.VIDEO, prompt=source.prompt, provider="comfyui-ltxv")
        try:
            await self.generations.set_status(new_id, GenerationStatus.PROCESSING)
            if progress_callback: await progress_callback("🎬 <b>Продолжение видео</b>\n\n🖼 Извлекаю последний кадр…")
            proc = await asyncio.create_subprocess_exec("ffmpeg", "-y", "-sseof", "-0.05", "-i", str(tmp_video), "-frames:v", "1", str(tmp_frame), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0 or not tmp_frame.exists():
                raise ProviderError(f"Не удалось извлечь последний кадр видео: {err.decode(errors='ignore')[-500:]}")
            frame = tmp_frame.read_bytes()
            if progress_callback: await progress_callback("🎬 <b>Продолжение видео</b>\n\n🖼 Последний кадр готов ✓\n🎞 Продолжаю LTXV…")
            video_prompt = source.enhanced_prompt or source.prompt
            if "VIDEO:" in video_prompt: video_prompt = video_prompt.split("VIDEO:",1)[1].strip()
            identity = await self.storage.read(character.face_file_id) if character.face_file_id else None
            result = await self.i2v_video_provider.generate(character=character, prompt=video_prompt, reference_image=frame, identity_image=identity, duration_frames=97)
            if progress_callback: await progress_callback("🎬 <b>Продолжение видео</b>\n\n🎞 LTXV ✓\n🎨 VideoVAE ✓\n👤 ReActor…")
            if identity: result = await self.reface_provider.reface(video=result, face_reference=identity)
            result_path=await self.storage.save(result, f"generation_{new_id}.mp4")
            await self.generations.complete(new_id, result_path=result_path, enhanced_prompt=f"CONTINUED_FROM: {generation_id}\nDURATION_FRAMES: 97\nVIDEO: {video_prompt}")
            return character, result, new_id
        except Exception as exc:
            await self.generations.fail(new_id, str(exc))
            if isinstance(exc, ProviderError): raise
            raise ProviderError(str(exc)) from exc
        finally:
            for path in (tmp_video, tmp_frame):
                try: path.unlink(missing_ok=True)
                except OSError: pass

    async def regenerate_exact(
        self,
        *,
        user_id: int,
        character_id: int,
        generation_id: int,
    ) -> tuple[Character, bytes, int]:
        """Repeat a completed video using the exact saved source frame and LTXV prompt."""
        previous = await self.generations.get(user_id, generation_id)
        if previous is None or previous.kind != GenerationKind.VIDEO or previous.character_id != character_id:
            raise NotFoundError("Видео не найдено.")
        if not previous.enhanced_prompt:
            raise NotFoundError("Для этого видео не сохранён исходный промпт.")

        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        source_path = None
        marker = "SOURCE IMAGE GENERATION: "
        if marker in previous.enhanced_prompt:
            try:
                source_id_text = previous.enhanced_prompt.split(marker, 1)[1].split("\n", 1)[0].strip()
                source_generation = await self.generations.get(user_id, int(source_id_text))
                if source_generation and source_generation.result_path:
                    source_path = source_generation.result_path
            except (ValueError, IndexError):
                source_path = None

        if source_path is None:
            source_path = f"generation_{generation_id}_start.png"

        try:
            source_image = await self.storage.read(source_path)
        except Exception as exc:
            raise NotFoundError("Не найден исходный кадр видео для повторной генерации.") from exc

        duration_frames = duration_from_marker(previous.enhanced_prompt)
        video_prompt = previous.enhanced_prompt
        if "VIDEO:" in video_prompt:
            video_prompt = video_prompt.split("VIDEO:", 1)[1].strip()
        else:
            video_prompt = video_prompt.split("\n", 1)[-1].strip()

        new_id = await self.generations.create(
            user_id=user_id,
            character_id=character.id,
            kind=GenerationKind.VIDEO,
            prompt=previous.prompt,
            provider="comfyui-ltxv",
        )
        try:
            await self.generations.set_status(new_id, GenerationStatus.PROCESSING)
            identity_bytes = await self.storage.read(character.face_file_id) if character.face_file_id else None
            result = await self.i2v_video_provider.generate(
                character=character,
                prompt=video_prompt,
                reference_image=source_image,
                identity_image=identity_bytes,
                duration_frames=duration_frames,
            )
            # Repeat must execute the separate video ReActor workflow too.
            # The LTXV workflow intentionally contains no ReActor in V37.
            if identity_bytes:
                logging.getLogger("video_generation").info("[REPEAT][VIDEO] Running separate ReActor refacing")
                result = await self.reface_provider.reface(video=result, face_reference=identity_bytes)
            result_path = await self.storage.save(result, f"generation_{new_id}.mp4")
            await self.generations.complete(
                new_id,
                result_path=result_path,
                enhanced_prompt=previous.enhanced_prompt,
            )
            return character, result, new_id
        except Exception as exc:
            await self.generations.fail(new_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc
