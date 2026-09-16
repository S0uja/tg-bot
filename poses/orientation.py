from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from main.domain.errors import ProviderError

logger = logging.getLogger("pose_orientation")

ORIENTATIONS = {
    "front",
    "back",
    "left_side",
    "right_side",
    "three_quarter_front",
    "three_quarter_back",
    "unknown",
}

ORIENTATION_PROMPTS = {
    "front": (
        "(FRONT VIEW:1.5), (SUBJECT FACING CAMERA:1.45), "
        "face toward camera when physically possible, keep torso and hips camera-facing, "
        "do not rotate the subject away from the camera"
    ),
    "back": (
        "(BACK VIEW:1.6), (SUBJECT FACING AWAY FROM CAMERA:1.6), "
        "(BACK OF BODY TOWARD CAMERA:1.55), rear view, back of head and back/shoulders visible, "
        "torso and hips face away from camera, do not turn the subject toward camera, "
        "do not show the front of the torso, do not create a frontal portrait"
    ),
    "left_side": (
        "(LEFT SIDE PROFILE:1.5), subject oriented in left profile relative to camera, "
        "keep torso and hips side-on, do not rotate to a frontal view"
    ),
    "right_side": (
        "(RIGHT SIDE PROFILE:1.5), subject oriented in right profile relative to camera, "
        "keep torso and hips side-on, do not rotate to a frontal view"
    ),
    "three_quarter_front": (
        "(THREE-QUARTER FRONT VIEW:1.5), subject turned partly toward camera, "
        "preserve the same three-quarter camera angle, do not rotate fully frontal or rear"
    ),
    "three_quarter_back": (
        "(THREE-QUARTER BACK VIEW:1.55), subject turned partly away from camera, "
        "back and rear three-quarter body orientation visible, do not rotate to frontal view"
    ),
    "unknown": (
        "preserve the subject's camera-facing orientation from the pose reference, "
        "do not arbitrarily rotate the subject"
    ),
}


def cache_path(root: Path) -> Path:
    return root / ".pose_orientation_cache.json"


class PoseOrientationCache:
    """Persistent per-file pose orientation cache.

    Entries are invalidated automatically when the source file content changes.
    The cache is intentionally independent of the generation database.
    """

    def __init__(self, root: Path, analyzer: Any):
        self.root = root.resolve()
        self.analyzer = analyzer
        self.path = cache_path(self.root)
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except (OSError, ValueError, TypeError):
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _key(self, image_path: Path) -> str:
        return image_path.resolve().relative_to(self.root).as_posix()

    @staticmethod
    def _sha256(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()

    @staticmethod
    def _normalize(result: Any) -> dict[str, Any]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (ValueError, TypeError):
                result = {}

        if not isinstance(result, dict):
            result = {}

        orientation = str(result.get("orientation", "unknown")).strip().lower()
        aliases = {
            "front_view": "front",
            "back_view": "back",
            "rear": "back",
            "rear_view": "back",
            "left": "left_side",
            "right": "right_side",
            "side_left": "left_side",
            "side_right": "right_side",
            "three-quarter-front": "three_quarter_front",
            "three-quarter-back": "three_quarter_back",
            "3/4_front": "three_quarter_front",
            "3/4_back": "three_quarter_back",
        }
        orientation = aliases.get(orientation, orientation)
        if orientation not in ORIENTATIONS:
            orientation = "unknown"

        face_visible = result.get("face_visible")
        if isinstance(face_visible, str):
            face_visible = face_visible.strip().lower() in {"true", "yes", "1"}
        else:
            face_visible = bool(face_visible)

        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return {
            "orientation": orientation,
            "face_visible": face_visible,
            "confidence": confidence,
        }

    async def ensure(self, image_path: Path, image_bytes: bytes | None = None) -> dict[str, Any]:
        self._load()
        image_path = image_path.resolve()
        key = self._key(image_path)
        if image_bytes is None:
            image_bytes = image_path.read_bytes()
        digest = self._sha256(image_bytes)

        entry = self._data.get(key)
        if isinstance(entry, dict) and entry.get("sha256") == digest:
            return self._normalize(entry)

        logger.info("[POSE ORIENTATION] analyzing %s", key)
        result = await self.analyzer.analyze_pose_orientation(image_bytes)
        normalized = self._normalize(result)
        self._data[key] = {"sha256": digest, **normalized}
        self._save()
        logger.info(
            "[POSE ORIENTATION] %s -> %s face_visible=%s confidence=%.2f",
            key,
            normalized["orientation"],
            normalized["face_visible"],
            normalized["confidence"],
        )
        return normalized

    async def ensure_all(self, extensions: set[str] | None = None) -> tuple[int, int]:
        self._load()
        extensions = extensions or {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        files = sorted(
            p for p in self.root.rglob("*")
            if p.is_file()
            and p.suffix.lower() in extensions
            and p.name != self.path.name
            # OpenPose renderings contain only skeleton geometry and cannot
            # reliably tell front/back. Analyze the paired original image
            # instead; the *_noise_final_openpose.png file is only for ControlNet.
            and (not p.stem.lower().endswith("_noise_final_openpose") and not p.stem.lower().endswith("_depth"))
        )
        analyzed = 0
        cached = 0
        for image_path in files:
            before = self._data.get(self._key(image_path))
            digest = self._sha256(image_path.read_bytes())
            if isinstance(before, dict) and before.get("sha256") == digest:
                cached += 1
                continue
            await self.ensure(image_path)
            analyzed += 1
        return analyzed, cached

    def orientation_prompt(self, orientation: str) -> str:
        return ORIENTATION_PROMPTS.get(orientation, ORIENTATION_PROMPTS["unknown"])
