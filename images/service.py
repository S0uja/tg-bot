from io import BytesIO
from pathlib import Path
import random
import logging

from main.config import settings
from main.domain.enums import GenerationKind, GenerationStatus
from main.domain.errors import NotFoundError, ProviderError
from main.domain.models import Character, ImagePromptContext
from images.provider.base import ImageGenerator
from main.infrastructure.database.repositories.characters import CharacterRepository
from main.infrastructure.database.repositories.generations import GenerationRepository
from main.infrastructure.storage.base import MediaStorage
from main.prompts.service import PromptService, HAIRSTYLE_PROMPTS, HAIR_COLOR_PROMPTS
from poses.config import normalize_pose_image, poses_root, media_root, pose_category_root, resolve_pose
from poses.orientation import PoseOrientationCache


def _select_pose_image(pose: str, scene: str) -> tuple[str, Path | None, bytes | None, Path | None, bytes | None]:
    """Select a random pose image from the correct physical media folder."""
    category = resolve_pose(pose, scene)
    if not category:
        return "", None, None, None, None

    category_dir = pose_category_root(category)
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    candidates = [f for f in category_dir.rglob("*") if f.is_file() and f.suffix.lower() in exts] if category_dir.is_dir() else []
    if not candidates:
        return category, None, None, None, None

    originals = [f for f in candidates if not f.stem.lower().endswith("_noise_final_openpose") and not f.stem.lower().endswith("_depth")]
    selected_original = random.choice(originals) if originals else random.choice(candidates)

    if not selected_original.stem.lower().endswith("_noise_final_openpose"):
        skeleton = selected_original.with_name(selected_original.stem + "_noise_final_openpose.png")
        if skeleton.is_file():
            depth_path = selected_original.with_name(selected_original.stem + "_depth.png")
            return category, skeleton, normalize_pose_image(skeleton.read_bytes()), depth_path if depth_path.is_file() else None, depth_path.read_bytes() if depth_path.is_file() else None

    return category, selected_original, normalize_pose_image(selected_original.read_bytes()), None, None


class ImageGenerationService:
    def __init__(self, characters: CharacterRepository, generations: GenerationRepository, prompt_service: PromptService, image_provider: ImageGenerator, storage: MediaStorage, reference_sheet_workflow_path: str | None = None, body_reference_workflow_path: str | None = None, video_start_frame_workflow_path: str | None = None) -> None:
        self.characters = characters
        self.generations = generations
        self.prompt_service = prompt_service
        self.image_provider = image_provider
        self.storage = storage
        self.reference_sheet_workflow_path = reference_sheet_workflow_path
        self.body_reference_workflow_path = body_reference_workflow_path
        self.video_start_frame_workflow_path = video_start_frame_workflow_path
        self.pose_orientation_cache = PoseOrientationCache(media_root(), prompt_service.enhancer)

    async def generate(self, user_id: int, character_id: int, scene: str, pose: str = "", clothing: str = "", pose_reference_image: bytes | None = None, pose_reference_path: Path | None = None, orientation_reference_image: bytes | None = None, orientation_reference_path: Path | None = None, pose_visual_reference_image: bytes | None = None, depth_reference_image: bytes | None = None, depth_reference_path: Path | None = None, depth_strength: float | None = None, generation_seed: int | None = None) -> tuple[Character, bytes, int]:
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")
        generation_id = await self.generations.create(user_id=user_id, character_id=character.id, kind=GenerationKind.IMAGE, prompt=scene, pose=pose, clothing=clothing, provider="comfyui")
        try:
            await self.generations.set_status(generation_id, GenerationStatus.PROCESSING)
            pose_orientation = ""
            pose_face_visible = True
            pose_category = resolve_pose(pose, scene) if pose else ""
            selected_pose_path = None
            pose_image = None
            explicit_depth_image = depth_reference_image
            explicit_depth_path = depth_reference_path
            depth_reference_image = None
            depth_reference_path = None

            if pose_reference_image is not None:
                pose_category = pose or "reference"
                selected_pose_path = pose_reference_path
                if orientation_reference_path is not None:
                    orientation_info = await self.pose_orientation_cache.ensure(orientation_reference_path, orientation_reference_image)
                elif pose_reference_path is not None and orientation_reference_image is None:
                    orientation_info = await self.pose_orientation_cache.ensure(pose_reference_path, pose_reference_image)
                else:
                    raise ProviderError("Для pose reference не указан оригинал для анализа ориентации.")
                pose_orientation = orientation_info["orientation"]
                pose_face_visible = orientation_info["face_visible"]
                pose_image = normalize_pose_image(pose_reference_image)
                if explicit_depth_image is not None:
                    depth_reference_image = explicit_depth_image
                    depth_reference_path = explicit_depth_path
                elif pose_reference_path is not None:
                    candidate_depth = pose_reference_path.with_name(pose_reference_path.stem.removesuffix("_noise_final_openpose") + "_depth.png")
                    if candidate_depth.is_file():
                        depth_reference_path = candidate_depth
                        depth_reference_image = candidate_depth.read_bytes()
            else:
                dedicated_pose = pose_category in {"reference", "selfie"}
                if settings.feature_poses_enabled or dedicated_pose:
                    pose_category, selected_pose_path, pose_image, depth_reference_path, depth_reference_image = _select_pose_image(pose, scene)
                    if selected_pose_path is not None:
                        orientation_info = await self.pose_orientation_cache.ensure(selected_pose_path)
                        pose_orientation = orientation_info["orientation"]
                        pose_face_visible = orientation_info["face_visible"]
                else:
                    pose_category, selected_pose_path, pose_image = "", None, None
                    depth_reference_path, depth_reference_image = None, None

            if pose or pose_reference_image is not None:
                if pose_image is None:
                    expected_dir = pose_category_root(pose_category or pose or "...")
                    raise ProviderError(f"Не найдена картинка позы '{pose}' в {expected_dir}.")
                logging.getLogger("image_generation").info("[IMAGE POSE] selected category=%s path=%s orientation=%s face_visible=%s bytes=%d", pose_category, selected_pose_path, pose_orientation, pose_face_visible, len(pose_image))

            prompt = await self.prompt_service.build_image_prompt(ImagePromptContext(character_description=character.description, scene=scene, pose=pose, clothing=clothing, weight_profile=character.weight_profile, bust_size=character.bust_size, age_category=character.age_category, hairstyle=character.hairstyle, hair_color=character.hair_color, consistency_strength=character.consistency_strength, pose_orientation=pose_orientation))
            face_bytes = await self.storage.read(character.face_file_id) if character.face_file_id else None
            body_reference = None
            if character.body_reference_file_id:
                try:
                    body_reference = await self.storage.read(character.body_reference_file_id)
                except (OSError, FileNotFoundError):
                    body_reference = None
            use_pose_workflow = bool(pose_image is not None and self.video_start_frame_workflow_path)
            result = await self.image_provider.generate(character=character, prompt=prompt.positive, reference_image=face_bytes, body_reference_image=body_reference, workflow_path=self.video_start_frame_workflow_path if use_pose_workflow else (self.body_reference_workflow_path if body_reference and self.body_reference_workflow_path else None), pose_image=pose_image if use_pose_workflow else None, pose_visual_reference_image=orientation_reference_image if use_pose_workflow and pose_visual_reference_image is None else pose_visual_reference_image, depth_image=depth_reference_image if use_pose_workflow else None, depth_strength=depth_strength if use_pose_workflow else None, generation_seed=generation_seed)
            if face_bytes and pose_face_visible:
                result = await self.image_provider.reface(image=result, face_reference=face_bytes)
            result_path = await self.storage.save(result, f"generation_{generation_id}.png")
            await self.generations.complete(generation_id, result_path=result_path, enhanced_prompt=prompt.positive)
            return character, result, generation_id
        except Exception as exc:
            await self.generations.fail(generation_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc

    async def analyze_all_pose_orientations(self) -> tuple[int, int]:
        """Analyze all pose references once and persist their orientation cache."""
        return await self.pose_orientation_cache.ensure_all()
