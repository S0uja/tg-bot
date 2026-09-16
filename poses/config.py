from __future__ import annotations

import os
import io
import re
from pathlib import Path

from PIL import Image, ImageOps


DEFAULT_POSE_ALIASES: dict[str, tuple[str, ...]] = {
    "all_fours": ("четвереньк", "all fours"),
    "kneeling": ("на колен", "на колени", "kneeling"),
    "selfie": ("селфи", "selfie"),
    "reference": ("reference", "референс", "референсная поза"),
    "lying": (
        "лежу", "лежит", "лежа", "лег", "легла",
        "на спине", "на животе", "на боку", "lying",
    ),
    "sitting": ("сижу", "сидит", "сидя", "села", "сел", "сядь", "sitting"),
    "stand": ("стою", "стоит", "стоя", "встал", "встала", "stand"),
    "masturbate": (
        "дрочу", "мастурбирую", "дрочит", "дрочишь",
        "мастурбируешь", "мастурбирует", "ласкаешь", "ласкает", "ласкаю",
    ),
    "missionary": ("миссионерская", "миссионерской"),
}


def _split_aliases(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[,;|]", value) if item.strip())


def _load_pose_aliases() -> dict[str, tuple[str, ...]]:
    configured: dict[str, tuple[str, ...]] = {}
    for category, defaults in DEFAULT_POSE_ALIASES.items():
        raw = os.getenv(f"POSE_{category.upper()}")
        configured[category] = _split_aliases(raw) if raw is not None else defaults

    for key, value in os.environ.items():
        if not key.startswith("POSE_") or key in {"POSE_ORDER", "POSES_ROOT"}:
            continue
        category = key[5:].strip().lower()
        if not category:
            continue
        aliases = _split_aliases(value)
        if aliases:
            configured[category] = aliases

    order_raw = os.getenv("POSE_ORDER", "")
    if order_raw:
        ordered_names = [x.strip().lower() for x in re.split(r"[,;|]", order_raw) if x.strip()]
        ordered: dict[str, tuple[str, ...]] = {}
        for category in ordered_names:
            if category in configured:
                ordered[category] = configured[category]
        for category, aliases in configured.items():
            ordered.setdefault(category, aliases)
        configured = ordered

    return configured


POSE_ALIASES = _load_pose_aliases()
ALLOWED_POSES = frozenset(POSE_ALIASES)

POSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        pose,
        re.compile(r"(?:" + "|".join(re.escape(alias) for alias in aliases) + r")", re.I),
    )
    for pose, aliases in POSE_ALIASES.items()
    if aliases
)


def resolve_pose(pose: str = "", scene: str = "") -> str:
    explicit = (pose or "").strip().lower()
    if explicit in ALLOWED_POSES:
        return explicit

    text = f"{pose} {scene}".lower().replace("ё", "е")
    for category, pattern in POSE_PATTERNS:
        if pattern.search(text):
            return category
    return ""


def media_root() -> Path:
    """Return data/media, independent of the process current working directory."""
    configured = os.getenv("MEDIA_ROOT", "").strip()
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            root = Path(__file__).resolve().parents[2] / root
        return root

    return Path(__file__).resolve().parents[2] / "data" / "media"


def poses_root() -> Path:
    """Return data/media/poses, the root for ordinary pose categories."""
    configured = os.getenv("POSES_ROOT", "").strip()
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            root = Path(__file__).resolve().parents[2] / root
        return root

    return media_root() / "poses"


def pose_category_root(category: str) -> Path:
    """Resolve the physical folder for a semantic pose category.

    reference -> data/media/reference
    selfie    -> data/media/selfi
    all other categories -> data/media/poses/<category>
    """
    category = (category or "").strip().lower()
    if category == "reference":
        return media_root() / "reference"
    if category == "selfie":
        return media_root() / "selfi"
    return poses_root() / category


def pose_target_size() -> tuple[int, int]:
    def _positive_int(name: str, default: int) -> int:
        try:
            value = int(os.getenv(name, str(default)).strip())
            return value if value > 0 else default
        except (TypeError, ValueError):
            return default

    return _positive_int("POSE_TARGET_WIDTH", 512), _positive_int("POSE_TARGET_HEIGHT", 768)


def normalize_pose_image(image_bytes: bytes) -> bytes:
    if not image_bytes:
        return image_bytes

    target_width, target_height = pose_target_size()
    with Image.open(io.BytesIO(image_bytes)) as source:
        source = ImageOps.exif_transpose(source).convert("RGBA")
        contained = ImageOps.contain(
            source,
            (target_width, target_height),
            method=Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 255))
        left = (target_width - contained.width) // 2
        top = (target_height - contained.height) // 2
        canvas.alpha_composite(contained, (left, top))

        output = io.BytesIO()
        canvas.convert("RGB").save(output, format="PNG", optimize=False)
        return output.getvalue()


def pose_prompt() -> str:
    lines = [
        "POSE CONTROL:",
        "The application selects the actual pose reference image locally.",
        "Do not describe limb coordinates or invent pose filenames.",
        "Allowed pose values:",
    ]
    for category, aliases in POSE_ALIASES.items():
        lines.append(f"- {category}: {', '.join(aliases)}")
    lines.extend(
        [
            '- "pose" is the semantic body-position category for the current visual state.',
            '- If the user explicitly changes posture, update pose to the matching category.',
            '- If the user only says "покажи", "скинь фотку" or similar, keep the current pose.',
            '- If there is no current pose and a photo is requested, use the first suitable category from the list.',
            '- Do not invent a new pose category.',
        ]
    )
    return "\n".join(lines)
