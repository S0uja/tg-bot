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
from poses.config import normalize_pose_image, poses_root, resolve_pose
from poses.orientation import PoseOrientationCache


def _select_pose_image(pose: str, scene: str) -> tuple[str, Path | None, bytes | None, Path | None, bytes | None]:
    """Select a random pose image and return its source path and normalized bytes."""
    category = resolve_pose(pose, scene)
    if not category:
        return "", None, None, None, None

    category_dir = poses_root() / category
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    candidates = [
        f for f in category_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in exts
    ] if category_dir.is_dir() else []

    if not candidates:
        return category, None, None, None, None

    # V8 pose folders contain original + generated control maps:
    #   image.jpg + image_noise_final_openpose.png + image_depth.png
    # Prefer the OpenPose companion when an original image is selected. Legacy
    # skeleton-only folders continue to work unchanged.
    originals = [
        f for f in candidates
        if not f.stem.lower().endswith("_noise_final_openpose")
        and not f.stem.lower().endswith("_depth")
    ]
    selected_original = random.choice(originals) if originals else random.choice(candidates)
    if not selected_original.stem.lower().endswith("_noise_final_openpose"):
        skeleton = selected_original.with_name(selected_original.stem + "_noise_final_openpose.png")
        if skeleton.is_file():
            depth_path = selected_original.with_name(selected_original.stem + "_depth.png")
            depth_bytes = depth_path.read_bytes() if depth_path.is_file() else None
            return category, skeleton, normalize_pose_image(skeleton.read_bytes()), depth_path if depth_path.is_file() else None, depth_bytes

    return category, selected_original, normalize_pose_image(selected_original.read_bytes()), None, None



class ImageGenerationService:
    def __init__(
        self,
        characters: CharacterRepository,
        generations: GenerationRepository,
        prompt_service: PromptService,
        image_provider: ImageGenerator,
        storage: MediaStorage,
        reference_sheet_workflow_path: str | None = None,
        body_reference_workflow_path: str | None = None,
        video_start_frame_workflow_path: str | None = None,
    ) -> None:
        self.characters = characters
        self.generations = generations
        self.prompt_service = prompt_service
        self.image_provider = image_provider
        self.storage = storage
        self.reference_sheet_workflow_path = reference_sheet_workflow_path
        self.body_reference_workflow_path = body_reference_workflow_path
        self.video_start_frame_workflow_path = video_start_frame_workflow_path
        self.pose_orientation_cache = PoseOrientationCache(poses_root(), prompt_service.enhancer)

    async def generate(
        self,
        user_id: int,
        character_id: int,
        scene: str,
        pose: str = "",
        clothing: str = "",
        pose_reference_image: bytes | None = None,
        pose_reference_path: Path | None = None,
        orientation_reference_image: bytes | None = None,
        orientation_reference_path: Path | None = None,
        pose_visual_reference_image: bytes | None = None,
        depth_reference_image: bytes | None = None,
        depth_reference_path: Path | None = None,
        depth_strength: float | None = None,
        generation_seed: int | None = None,
    ) -> tuple[Character, bytes, int]:
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        generation_id = await self.generations.create(
            user_id=user_id,
            character_id=character.id,
            kind=GenerationKind.IMAGE,
            prompt=scene,
            pose=pose,
            clothing=clothing,
            provider="comfyui",
        )

        try:
            await self.generations.set_status(generation_id, GenerationStatus.PROCESSING)

            # Exact pose references (used by /test_poses) must bypass semantic
            # folder selection. Otherwise pose="test" is interpreted as a pose
            # category and _select_pose_image() raises before the supplied file
            # can be used.
            pose_orientation = ""
            pose_face_visible = True

            explicit_depth_image = depth_reference_image
            explicit_depth_path = depth_reference_path
            depth_reference_image = None
            depth_reference_path = None

            if pose_reference_image is not None:
                pose_category = pose or "reference"
                selected_pose_path = pose_reference_path

                if orientation_reference_path is not None:
                    orientation_info = await self.pose_orientation_cache.ensure(
                        orientation_reference_path,
                        orientation_reference_image,
                    )
                elif pose_reference_path is not None and orientation_reference_image is None:
                    # Backward-compatible path: normal exact references can still
                    # use their own image for orientation when no separate original
                    # reference was supplied.
                    orientation_info = await self.pose_orientation_cache.ensure(
                        pose_reference_path,
                        pose_reference_image,
                    )
                else:
                    raise ProviderError(
                        "Для pose reference не указан оригинал для анализа ориентации."
                    )

                pose_orientation = orientation_info["orientation"]
                pose_face_visible = orientation_info["face_visible"]
                pose_image = normalize_pose_image(pose_reference_image)
                if explicit_depth_image is not None:
                    depth_reference_image = explicit_depth_image
                    depth_reference_path = explicit_depth_path
                elif pose_reference_path is not None:
                    candidate_depth = pose_reference_path.with_name(
                        pose_reference_path.stem.removesuffix("_noise_final_openpose") + "_depth.png"
                    )
                    if candidate_depth.is_file():
                        depth_reference_path = candidate_depth
                        depth_reference_image = candidate_depth.read_bytes()
            else:
                if settings.feature_poses_enabled:
                    pose_category, selected_pose_path, pose_image, depth_reference_path, depth_reference_image = _select_pose_image(pose, scene)
                    if selected_pose_path is not None:
                        orientation_info = await self.pose_orientation_cache.ensure(selected_pose_path)
                        pose_orientation = orientation_info["orientation"]
                        pose_face_visible = orientation_info["face_visible"]
                else:
                    # Pose feature is disabled: ignore semantic pose selection and
                    # generate without OpenPose/Depth references.
                    pose_category, selected_pose_path, pose_image = "", None, None
                    depth_reference_path, depth_reference_image = None, None

            if pose or pose_reference_image is not None:
                if pose_image is None:
                    raise ProviderError(
                        f"Не найдена картинка позы '{pose}' в poses/{pose_category or '...'}."
                    )
                logging.getLogger("image_generation").info(
                    "[IMAGE POSE] selected category=%s orientation=%s face_visible=%s bytes=%d",
                    pose_category, pose_orientation, pose_face_visible, len(pose_image)
                )

            prompt = await self.prompt_service.build_image_prompt(
                ImagePromptContext(
                    character_description=character.description,
                    scene=scene,
                    pose=pose,
                    clothing=clothing,
                    weight_profile=character.weight_profile,
                    bust_size=character.bust_size,
                    age_category=character.age_category,
                    hairstyle=character.hairstyle,
                    hair_color=character.hair_color,
                    consistency_strength=character.consistency_strength,
                    pose_orientation=pose_orientation,
                )
            )

            face_bytes = None
            if character.face_file_id:
                face_bytes = await self.storage.read(character.face_file_id)

            body_reference = None
            if character.body_reference_file_id:
                try:
                    body_reference = await self.storage.read(character.body_reference_file_id)
                except (OSError, FileNotFoundError):
                    body_reference = None
            use_pose_workflow = bool(
                pose_image is not None and self.video_start_frame_workflow_path
            )

            result = await self.image_provider.generate(
                character=character,
                prompt=prompt.positive,
                reference_image=face_bytes,
                body_reference_image=body_reference,
                workflow_path=(
                    self.video_start_frame_workflow_path
                    if use_pose_workflow
                    else (
                        self.body_reference_workflow_path
                        if body_reference and self.body_reference_workflow_path
                        else None
                    )
                ),
                pose_image=pose_image if use_pose_workflow else None,
                pose_visual_reference_image=(
                    orientation_reference_image
                    if use_pose_workflow and pose_visual_reference_image is None
                    else pose_visual_reference_image
                ),
                depth_image=depth_reference_image if use_pose_workflow else None,
                depth_strength=depth_strength if use_pose_workflow else None,
                generation_seed=generation_seed,
            )
            # Do not force a frontal face onto poses whose reference has no visible face.
            # ReActor is still used normally for front/side/visible-face poses.
            if face_bytes and pose_face_visible:
                result = await self.image_provider.reface(image=result, face_reference=face_bytes)

            result_path = await self.storage.save(
                result,
                f"generation_{generation_id}.png",
            )
            await self.generations.complete(
                generation_id,
                result_path=result_path,
                enhanced_prompt=prompt.positive,
            )
            return character, result, generation_id

        except Exception as exc:
            await self.generations.fail(generation_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc


    async def analyze_all_pose_orientations(self) -> tuple[int, int]:
        """Analyze all pose references once and persist their orientation cache."""
        return await self.pose_orientation_cache.ensure_all()


    async def get_pose_orientation(
        self,
        pose_path: Path,
        pose_bytes: bytes | None = None,
    ) -> dict:
        """Return cached AI orientation metadata for one pose reference."""
        return await self.pose_orientation_cache.ensure(pose_path, pose_bytes)


    async def get_generation(self, user_id: int, generation_id: int):
        generation = await self.generations.get(user_id, generation_id)
        if generation is None or generation.status != GenerationStatus.COMPLETED or not generation.result_path:
            raise NotFoundError("Генерация не найдена или ещё не готова.")
        return generation

    async def read_generation_media(self, user_id: int, generation_id: int):
        generation = await self.get_generation(user_id, generation_id)
        return generation, await self.storage.read(generation.result_path)

    async def toggle_favorite(self, user_id: int, generation_id: int) -> bool:
        value = await self.generations.toggle_favorite(user_id, generation_id)
        if value is None:
            raise NotFoundError("Генерация не найдена.")
        return value

    async def list_recent(self, user_id: int, limit: int = 12):
        return await self.generations.list_recent(user_id, limit)

    async def list_favorites(self, user_id: int, limit: int = 12):
        return await self.generations.list_favorites(user_id, limit)

    async def get_image_generation(self, user_id: int, generation_id: int):
        generation = await self.generations.get(user_id, generation_id)
        if generation is None or generation.kind != GenerationKind.IMAGE:
            raise NotFoundError("Изображение не найдено.")
        if generation.result_path is None:
            raise NotFoundError("Файл изображения не найден.")
        return generation

    async def generate_video_start_frame(
        self,
        *,
        user_id: int,
        character_id: int,
        description: str,
    ) -> tuple[Character, bytes, str]:
        """Generate the still image that will become the first frame of a video.

        This deliberately uses the normal character image workflow so the character
        face/profile is established before LTXV receives the image.
        """
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        prompt = await self.prompt_service.build_video_start_frame_prompt(
            ImagePromptContext(
                character_description=character.description,
                scene=description,
                pose="initial starting pose matching the requested video action, with all action-relevant body parts clearly visible",
                clothing="clothing described by the video request, otherwise appropriate clothing",
                weight_profile=character.weight_profile,
                bust_size=character.bust_size,
                age_category=character.age_category,
                hairstyle=character.hairstyle,
                hair_color=character.hair_color,
                    consistency_strength=character.consistency_strength,
            )
        )

        face_bytes = None
        if character.face_file_id:
            face_bytes = await self.storage.read(character.face_file_id)

        result = await self.image_provider.generate(
            character=character,
            prompt=prompt.positive,
            reference_image=face_bytes,
            workflow_path=self.video_start_frame_workflow_path,
        )
        if face_bytes:
            result = await self.image_provider.reface(image=result, face_reference=face_bytes)
        return character, result, prompt.positive

    async def generate_character_control(
        self,
        *,
        user_id: int,
        character_id: int,
        stage: str,
    ) -> tuple[Character, bytes, int]:
        """Generate a neutral full-body control image using the current character profile."""
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        profile = []
        weight_map = {
            "Очень худая": "very slim adult physique, very low body fat, slender arms and legs, narrow ribcage, slim waist, slim hips and thighs, flat abdomen, delicate proportions",
            "Худая": "slim build, narrow waist, slender arms and legs, low body fat",
            "Нормальная": "average natural build, balanced proportions, moderate body fat",
            "Пышная": "curvy plus-size build, fuller hips and thighs, softer waist and abdomen, higher body fat, fuller overall body volume",
            "Толстая": "plus-size heavy build, visibly overweight, thick upper arms, broad waist, full abdomen, wide hips, heavy thighs, soft body, substantial body mass",
        }
        bust_map = {
            1: "very small adult bust, very low breast volume, minimal breast projection, small subtle breasts, small chest, compact chest, narrow chest proportions",
            2: "small to medium adult bust, modest breast volume, moderate projection, natural rounded shape, balanced chest proportions",
            3: "large adult bust, clearly full breast volume, pronounced projection, full rounded breasts, prominent chest proportions",
            4: "very large adult bust, very high breast volume, strongly pronounced projection, very full rounded breasts, prominent heavy chest proportions",
        }
        hairstyle_map = HAIRSTYLE_PROMPTS
        hair_color_map = HAIR_COLOR_PROMPTS
        age_map = {
            "Молодая": "young adult woman in her 20s, youthful face, smooth firm youthful skin, minimal fine lines, no pronounced wrinkles",
            "Милф": "mature adult woman, approximately late 30s to mid 40s, subtle forehead lines, fine crow's feet, light nasolabial folds, slightly less firm skin",
            "Зрелая": "older mature adult woman, approximately 55 to 65 years old, pronounced forehead wrinkles, visible crow's feet, defined nasolabial folds, fine lines around the mouth, noticeable age-related skin texture, less firm skin, natural facial creases",
        }
        if character.weight_profile:
            profile.append(weight_map.get(character.weight_profile, "natural body"))
        if character.bust_size is not None:
            profile.append(bust_map.get(character.bust_size, "natural bust"))
        if character.age_category:
            profile.append(age_map.get(character.age_category, "adult woman"))
        if character.hairstyle:
            profile.append(hairstyle_map.get(character.hairstyle, character.hairstyle))
        if character.hair_color:
            profile.append(hair_color_map.get(character.hair_color, character.hair_color))
        # Legacy numeric fields are only used when the corresponding category is absent.
        # Otherwise they can contradict the selected visual profile (for example age=38
        # together with the "Зрелая" category).
        if not character.weight_profile and character.weight is not None:
            profile.append(f"weight {character.weight:g} kg")
        if not character.bust_size and character.bust is not None:
            profile.append(f"bust circumference {character.bust:g} cm")
        if not character.age_category and character.age is not None:
            profile.append(f"age {character.age}")
        profile_text = ", ".join(profile) if profile else "natural proportions"

        control_prompt = (
            "(one person:1.6), (single adult woman:1.55), (one full human figure:1.5), "
            "(head to toe, both feet visible:1.45), front-facing neutral standing pose, "
            "arms relaxed at sides, centered composition, one continuous human silhouette, "
            f"{profile_text}, fully nude adult anatomical body reference, "
            "neutral non-erotic presentation, plain seamless gray studio background, "
            "soft even studio lighting, photorealistic CyberRealistic style, realistic anatomy"
        )
        generation_id = await self.generations.create(
            user_id=user_id,
            character_id=character.id,
            kind=GenerationKind.IMAGE,
            prompt=f"character_profile:{stage}",
            pose="standing straight full body",
            clothing="simple fitted neutral clothing",
            provider="comfyui",
        )
        try:
            await self.generations.set_status(generation_id, GenerationStatus.PROCESSING)
            face_bytes = None
            if character.face_file_id:
                face_bytes = await self.storage.read(character.face_file_id)
            print("\n" + "=" * 90)
            print("BODY REFERENCE — PROMPT SENT TO IMAGE GENERATOR")
            print("=" * 90)
            print(control_prompt)
            print("=" * 90)
            print(f"Workflow: {self.reference_sheet_workflow_path}")
            print(f"Character: {character.name} (id={character.id})")
            print("=" * 90 + "\n")

            result = await self.image_provider.generate(
                character=character,
                prompt=control_prompt,
                reference_image=face_bytes,
                workflow_path=self.reference_sheet_workflow_path,
                reactor_input_faces_index="0",
            )
            result_path = await self.storage.save(result, f"generation_{generation_id}.png")
            await self.characters.set_body_reference_file(character.id, result_path)
            # The same file is also kept as the persistent character body reference.
            await self.generations.complete(
                generation_id,
                result_path=result_path,
                enhanced_prompt=control_prompt,
            )
            return character, result, generation_id
        except Exception as exc:
            await self.generations.fail(generation_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc

    async def regenerate(
        self,
        user_id: int,
        character_id: int,
        generation_id: int | None = None,
    ) -> tuple[Character, bytes, int]:
        """Regenerate an image from the exact selected generation inputs.

        The enhanced prompt is reused verbatim when available so the retry changes
        the random seed, not the semantic prompt produced by the AI prompt engine.
        """
        previous = (
            await self.generations.get(user_id, generation_id)
            if generation_id is not None
            else await self.generations.latest_image(user_id, character_id)
        )
        if previous is None or previous.kind != GenerationKind.IMAGE or previous.character_id != character_id:
            raise NotFoundError("Изображение не найдено.")

        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")

        new_id = await self.generations.create(
            user_id=user_id,
            character_id=character.id,
            kind=GenerationKind.IMAGE,
            prompt=previous.prompt,
            pose=previous.pose or "",
            clothing=previous.clothing or "",
            provider="comfyui",
        )
        try:
            await self.generations.set_status(new_id, GenerationStatus.PROCESSING)
            prompt = previous.enhanced_prompt
            if not prompt:
                generated = await self.prompt_service.build_image_prompt(
                    ImagePromptContext(
                        character_description=character.description,
                        scene=previous.prompt,
                        pose=previous.pose or "",
                        clothing=previous.clothing or "",
                        weight_profile=character.weight_profile,
                        bust_size=character.bust_size,
                        age_category=character.age_category,
                        hairstyle=character.hairstyle,
                        hair_color=character.hair_color,
                    consistency_strength=character.consistency_strength,
                    )
                )
                prompt = generated.positive

            face_bytes = await self.storage.read(character.face_file_id) if character.face_file_id else None
            body_reference = None
            if character.body_reference_file_id:
                try:
                    body_reference = await self.storage.read(character.body_reference_file_id)
                except (OSError, FileNotFoundError):
                    body_reference = None
            result = await self.image_provider.generate(
                character=character,
                prompt=prompt,
                reference_image=face_bytes,
                body_reference_image=body_reference,
                workflow_path=(self.body_reference_workflow_path if body_reference and self.body_reference_workflow_path else None),
            )
            # Repeat must execute the same separate ReActor stage as a normal image.
            # V37 moved ReActor out of the generation workflow, so this call is required
            # for regenerated images as well.
            if face_bytes:
                import logging
                logging.getLogger("image_generation").info("[REPEAT][IMAGE] Running separate ReActor refacing")
                result = await self.image_provider.reface(image=result, face_reference=face_bytes)
            result_path = await self.storage.save(result, f"generation_{new_id}.png")
            await self.generations.complete(new_id, result_path=result_path, enhanced_prompt=prompt)
            return character, result, new_id
        except Exception as exc:
            await self.generations.fail(new_id, str(exc))
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc)) from exc
