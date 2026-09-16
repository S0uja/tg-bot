import re

DEFAULT_VIDEO_FPS = 24
DEFAULT_VIDEO_FRAMES = 97


def extract_video_duration(description: str, *, fps: int = DEFAULT_VIDEO_FPS, default_frames: int = DEFAULT_VIDEO_FRAMES) -> tuple[str, int]:
    """Extract a human duration and convert it to LTXV's required 8n+1 frame count."""
    text = description.strip()
    pattern = re.compile(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:секунд(?:ы|у)?|сек\.?|с\.?|seconds?|secs?|s)(?![a-zа-я])",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return text, default_frames
    seconds = float(match.group(1).replace(",", "."))
    seconds = max(0.375, min(seconds, 20.0))
    target_frames = max(9, int(round(seconds * fps)))
    frames = max(9, 1 + 8 * round((target_frames - 1) / 8))
    cleaned = (text[:match.start()] + " " + text[match.end():]).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned, frames


def duration_from_marker(text: str, default: int = DEFAULT_VIDEO_FRAMES) -> int:
    match = re.search(r"(?:^|\n)DURATION_FRAMES:\s*(\d+)", text)
    return int(match.group(1)) if match else default
