from __future__ import annotations

CONSISTENCY_LEVELS = {
    "low": {
        "label": "Low",
        "prompt": (
            "Preserve the character's recognizable identity and overall appearance, "
            "but allow natural variation in expression, pose and minor facial details."
        ),
    },
    "medium": {
        "label": "Medium",
        "prompt": (
            "Strong character identity lock: preserve the same facial identity, face shape, "
            "eyes, nose, lips, jawline, cheekbones, hairline and hairstyle. Keep the character "
            "recognizably the same person across generations while allowing natural expression and motion."
        ),
    },
    "high": {
        "label": "High",
        "prompt": (
            "Very strong character identity lock: match the reference person's facial geometry "
            "and recognizable features as closely as possible. Preserve face shape, eye shape and spacing, "
            "nose, lips, jawline, cheekbones, hairline and hairstyle. Minimize identity drift between frames "
            "and generations."
        ),
    },
    "maximum": {
        "label": "Maximum",
        "prompt": (
            "Maximum character identity lock: treat the character reference face as the authoritative identity anchor. "
            "Preserve facial geometry and all distinctive identity features with minimal deviation: face shape, "
            "eyes, eyebrows, nose, lips, jawline, cheekbones, hairline and hairstyle. Do not redesign, beautify, "
            "age, de-age or otherwise alter the person's identity. Maintain the same person throughout the image/video."
        ),
    },
}

def normalize_consistency(value: str | None) -> str:
    value=(value or "medium").strip().lower()
    return value if value in CONSISTENCY_LEVELS else "medium"

def consistency_prompt(value: str | None) -> str:
    return CONSISTENCY_LEVELS[normalize_consistency(value)]["prompt"]

def consistency_label(value: str | None) -> str:
    return CONSISTENCY_LEVELS[normalize_consistency(value)]["label"]
