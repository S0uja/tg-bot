from main.domain.models import GeneratedPrompt, ImagePromptContext
from main.infrastructure.ai.llm.base import PromptEnhancer
from main.prompts.consistency import consistency_prompt
from poses.orientation import ORIENTATION_PROMPTS


WEIGHT_PROMPTS = {
    "Очень худая": "(extremely thin adult woman:1.4), (very low body fat:1.4), (very thin arms and legs:1.35), (very narrow waist:1.3), (narrow hips:1.25), (very small overall body volume:1.3), (visible collarbones and subtle rib definition:1.15), delicate narrow frame, minimal soft tissue volume",
    "Худая": "(slim adult woman:1.2), (low body fat:1.15), (slender arms and legs:1.15), (narrow waist:1.15), slim hips, lean body, small overall body volume",
    "Нормальная": "(average natural adult woman:1.2), (balanced natural body proportions:1.2), moderate body fat, medium waist, medium hips, medium thighs, average overall body volume",
    "Пышная": "(curvy plus-size adult woman:1.25), (noticeably fuller body:1.2), (higher body fat:1.2), (full hips and thighs:1.2), (soft wider waist and abdomen:1.15), rounded hips, fuller arms, clearly more body volume than an average body",
    "Толстая": "(heavy plus-size adult woman:1.35), (clearly very high body fat:1.35), (large overall body volume:1.3), (very broad waist:1.3), (large soft abdomen:1.3), (very wide hips:1.3), (very thick thighs:1.3), (full upper arms:1.2), (heavy soft legs:1.2), substantial soft body mass, clearly heavier than a curvy plus-size body",
}

BUST_PROMPTS = {
    1: "(nearly flat adult chest:1.5), (minimal breast tissue:1.5), (almost no visible breast projection:1.45), (very small bust:1.4), very subtle natural chest contour, flat chest",
    2: "(small adult bust:1.3), (low breast volume:1.3), (small natural breasts:1.3), modest projection, clearly smaller than medium bust",
    3: "(large adult bust:1.35), (high breast volume:1.35), (pronounced natural projection:1.3), (full breasts:1.3), clearly larger than small and medium bust",
    4: "(very large adult bust:1.5), (extremely high breast volume:1.5), (very pronounced projection:1.45), (very full breasts:1.45), (exceptionally large bust:1.4), dramatically larger than size 3",
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
    "Молодая": "young adult woman, approximately 20s, youthful facial features, smooth firm skin, minimal fine lines, no pronounced wrinkles, fresh youthful appearance, youthful body appearance, firm skin on arms and legs, firm natural body tissue, little visible skin laxity, youthful muscle tone",
    "Милф": "mature adult woman, approximately late 30s to mid 40s, mature facial features, natural skin texture, subtle forehead lines, fine crow's feet, light nasolabial folds, slightly less firm skin, clearly adult but not elderly, mature body appearance, slightly softer skin on arms and legs, mild natural skin laxity, less youthful muscle tone",
    "Зрелая": "older mature adult woman, approximately 55 to 65 years old, clearly mature facial features, pronounced forehead wrinkles, visible crow's feet, defined nasolabial folds, fine lines around the mouth, noticeable age-related skin texture, less firm skin, natural facial creases, realistic mature skin, visibly mature body appearance, softer skin on arms and legs, noticeable natural skin laxity, reduced muscle definition, age-appropriate body tissue",
}

AGE_NEGATIVE_PROMPTS = {
    "Молодая": "deep wrinkles, pronounced crow's feet, deep nasolabial folds, sagging skin, age spots, elderly facial features, aged body appearance, pronounced skin laxity, loose skin, reduced muscle tone",
    "Милф": "elderly facial features, deep severe wrinkles, heavy sagging skin, extreme age spots, strongly aged body appearance, pronounced loose skin, severe skin laxity",
    "Зрелая": "very young face, youthful facial features, baby face, perfectly smooth skin, no wrinkles, unlined skin, youthful body appearance, very firm youthful skin, minimal skin laxity, high youthful muscle tone",
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
                "(OPENPOSE POSE GUIDE:1.1), "
                "follow the provided OpenPose for the overall body posture and limb arrangement, "
                "preserve the general pelvis, knee, lower-leg, and foot placement, "
                "while adapting naturally to the character's body shape, proportions, and anatomy; "
                "keep all limbs anatomically connected and naturally proportioned, "
                "do not force the body into impossible joint angles or distort limb lengths"
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

        if pose_lock_block:
            parts.append(pose_lock_block)
        if orientation_block:
            parts.append(orientation_block)

        positive = ", ".join(p for p in parts if p)
        max_chars = 1500
        if len(positive) > max_chars:
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
        """Build an image prompt for the exact opening frame of a video request."""
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
            pose="initial starting pose matching the requested video action, with all action-relevant body parts clearly visible",
            clothing=context.clothing or "appropriate clothing matching the video request",
            weight_profile=context.weight_profile,
            bust_size=context.bust_size,
            age_category=context.age_category,
            hairstyle=context.hairstyle,
            hair_color=context.hair_color,
            consistency_strength=context.consistency_strength,
        )
        return await self.build_image_prompt(frame_context)
