from main.domain.models import GeneratedPrompt, ImagePromptContext
from main.infrastructure.ai.llm.base import PromptEnhancer
from main.prompts.consistency import consistency_prompt
from poses.orientation import ORIENTATION_PROMPTS


WEIGHT_PROMPTS = {
    "Очень худая": "very slim adult body, very low body fat, slim arms and legs, narrow waist, slim hips and thighs",
    "Худая": "slim adult body, low body fat, slender arms and legs, narrow waist",
    "Нормальная": "average natural adult body, balanced proportions, moderate body fat",
    "Пышная": "curvy plus-size adult body, higher body fat, fuller hips and thighs, softer waist and abdomen, fuller overall body volume",
    "Толстая": "heavy plus-size adult body, high body fat, broad waist, full abdomen, wide hips, heavy thighs, substantial body mass",
}

BUST_PROMPTS = {
    1: "very small adult bust, very low breast volume, minimal projection, small natural breasts",
    2: "small to medium adult bust, modest volume, moderate projection, natural proportions",
    3: "large adult bust, high breast volume, pronounced projection, full natural breasts",
    4: "very large adult bust, very high breast volume, strongly pronounced projection, very full natural breasts",
}


HAIRSTYLE_PROMPTS = {
    "Длинные прямые": "long straight hair, reaching below shoulders, sleek, smooth texture, blunt ends",
    "Длинные волнистые": "long wavy hair, reaching below shoulders, loose natural waves",
    "Длинные кудрявые": "long curly hair, reaching below shoulders, defined natural curls, voluminous",
    "Каре": "short blunt bob haircut, chin-length, straight hair, clean even ends",
    "Удлинённое каре": "long bob haircut, shoulder-length, straight hair, blunt ends",
    "Каскад": "long layered haircut, multiple visible layers, face-framing layers",
    "Пикси": "short pixie haircut, cropped sides and back, longer textured top",
    "Высокий хвост": "long hair pulled into a high ponytail, gathered above the crown",
    "Низкий хвост": "long hair tied into a low ponytail at the nape of the neck",
    "Коса": "long hair styled into a single braid",
    "Пучок": "hair gathered into a neat bun at the back of the head",
}

HAIR_COLOR_PROMPTS = {
    "Чёрные": "black hair",
    "Тёмно-каштановые": "dark brown hair",
    "Каштановые": "medium brown chestnut hair",
    "Светло-каштановые": "light brown hair",
    "Блонд": "blonde hair",
    "Платиновый блонд": "platinum blonde hair",
    "Рыжие": "natural red hair",
    "Тёмно-рыжие": "auburn hair",
    "Седые": "gray hair with natural silver tones",
}

AGE_PROMPTS = {
    "Молодая": "young adult woman, approximately 20s, youthful facial features, smooth firm skin, minimal fine lines, no pronounced wrinkles, fresh youthful appearance",
    "Милф": "mature adult woman, approximately late 30s to mid 40s, mature facial features, natural skin texture, subtle forehead lines, fine crow's feet, light nasolabial folds, slightly less firm skin, clearly adult but not elderly",
    "Зрелая": "older mature adult woman, approximately 55 to 65 years old, clearly mature facial features, pronounced forehead wrinkles, visible crow's feet, defined nasolabial folds, fine lines around the mouth, noticeable age-related skin texture, less firm skin, natural facial creases, realistic mature skin",
}

AGE_NEGATIVE_PROMPTS = {
    "Молодая": "deep wrinkles, pronounced crow's feet, deep nasolabial folds, sagging skin, age spots, elderly facial features",
    "Милф": "elderly facial features, deep severe wrinkles, heavy sagging skin, extreme age spots",
    "Зрелая": "very young face, youthful facial features, baby face, perfectly smooth skin, no wrinkles, unlined skin",
}


def profile_prompt(context: ImagePromptContext) -> str:
    parts: list[str] = []
    if context.weight_profile:
        parts.append(WEIGHT_PROMPTS.get(context.weight_profile, "natural adult body"))
    if context.bust_size is not None:
        parts.append(BUST_PROMPTS.get(context.bust_size, "natural adult bust"))
    if context.age_category:
        parts.append(AGE_PROMPTS.get(context.age_category, "adult woman"))
    if context.hairstyle:
        parts.append(HAIRSTYLE_PROMPTS.get(context.hairstyle, context.hairstyle))
    if context.hair_color:
        parts.append(HAIR_COLOR_PROMPTS.get(context.hair_color, context.hair_color))
    return ", ".join(parts)


class PromptService:
    def __init__(self, enhancer: PromptEnhancer) -> None:
        self.enhancer = enhancer

    async def build_image_prompt(self, context: ImagePromptContext) -> GeneratedPrompt:
        """Build a compact SD 1.5 prompt with strict priority:
        scene/environment -> exact pose/clothing -> character profile.
        """
        enhanced = await self.enhancer.enhance_image_prompt(context)
        enhanced = " ".join(enhanced.strip().split()).rstrip(" ,.")

        parts = [enhanced]

        # Clothing is a scene attribute, not a character-reference attribute.
        # Give it a dedicated high-priority block so the Body Reference cannot
        # silently replace the requested outfit.
        if context.clothing.strip():
            clothing = " ".join(context.clothing.strip().split()).strip(" ,.")
            if not clothing.lower().startswith(("wearing ", "dressed in ", "in ")):
                clothing = f"wearing {clothing}"
            parts.append(f"(exact requested clothing:1.25), ({clothing}:1.2)")

        if context.pose.strip():
            parts.append(context.pose.strip())

        pose_lock_block = ""
        if context.pose.strip():
            pose_lock_block = (
                "(STRICT OPENPOSE LOWER-BODY GEOMETRY:1.35), "
                "follow the provided OpenPose body pose, "
                "keep the pelvis/hips in the same position and at the same height, "
                "keep both knees at the same relative positions and angles as the skeleton, "
                "keep both feet and lower legs in the same positions and directions, "
                "preserve the depth and width of the squat, "
                "do not straighten or narrow the legs, do not swap left and right legs, "
                "do not invent a different lower-body pose; "
                "allow natural anatomical adjustment only where required to connect the joints"
            )


        orientation_block = ""
        if getattr(context, 'pose_orientation', ''):
            orientation = str(context.pose_orientation).strip().lower()
            orientation_block = (
                f"(pose orientation lock:1.5), "
                f"{ORIENTATION_PROMPTS.get(orientation, ORIENTATION_PROMPTS['unknown'])}"
            )

        profile = profile_prompt(context)
        if profile:
            parts.append(profile)

        # Pose and orientation are deterministic structural constraints. Keep them
        # last so they survive prompt shortening and receive the highest textual
        # priority after the scene/profile description.
        if pose_lock_block:
            parts.append(pose_lock_block)
        if orientation_block:
            parts.append(orientation_block)

        positive = ", ".join(p for p in parts if p)
        max_chars = 1500
        if len(positive) > max_chars:
            # Only the LLM-generated scene section is trimmed. Every
            # deterministic constraint, including orientation, is reserved.
            tail = ", ".join(
                p for p in (
                    context.pose.strip(),
                    context.clothing.strip(),
                    profile,
                    pose_lock_block,
                    orientation_block,
                ) if p
            )
            budget = max(200, max_chars - len(tail) - 2)
            scene_part = enhanced[:budget].rsplit(",", 1)[0].strip(" ,.")
            positive = ", ".join(
                p for p in (
                    scene_part,
                    context.pose.strip(),
                    context.clothing.strip(),
                    profile,
                    pose_lock_block,
                    orientation_block,
                ) if p
            )

        return GeneratedPrompt(positive=positive)



    async def build_video_start_frame_prompt(self, context: ImagePromptContext) -> GeneratedPrompt:
        """Build an image prompt for the exact opening frame of a video.

        The opening image must contain the body parts and composition required by the
        requested action, so the subsequent LTXV image-to-video stage has a useful
        starting state instead of trying to invent missing limbs or framing.
        """
        frame_scene = (
            "Create the exact opening still frame for this video request. "
            "This image will be used as frame 0 of an image-to-video animation. "
            "Match the requested subject, environment, clothing, pose, camera angle, framing, and composition exactly. "
            "Show the subject in the initial pose before any motion begins. "
            "Frame the subject wide enough to include every body part required by the requested action. "
            "If the request involves legs, walking, standing, sitting, jumping, or other full-body movement, "
            "use a full-body head-to-toe composition with both feet visible. "
            "Do not use a close-up when it would hide an action-relevant body part. "
            "Do not crop or hide action-relevant body parts. Do not invent a different camera angle or close-up. "
            "Preserve the requested environment, clothing, subject, and action-relevant starting pose. "
            "Preserve the character facial identity exactly: same face shape, eyes, nose, lips, jawline, cheekbones, hairline, and hairstyle. "
            "Prefer a natural photographic composition that gives the later animation room to move without "
            "cropping the subject. The generated image must be a coherent single frame, not a sequence or collage. "
            f"VIDEO REQUEST: {context.scene}"
        )
        frame_context = ImagePromptContext(
            character_description=context.character_description,
            scene=frame_scene,
            pose=(
                "initial starting pose matching the requested video action, "
                "with all action-relevant body parts clearly visible"
            ),
            clothing=context.clothing or "appropriate clothing matching the video request",
            weight_profile=context.weight_profile,
            bust_size=context.bust_size,
            age_category=context.age_category,
            hairstyle=context.hairstyle,
            hair_color=context.hair_color,
            consistency_strength=context.consistency_strength,
        )
        return await self.build_image_prompt(frame_context)
