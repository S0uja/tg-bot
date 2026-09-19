from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


CACHE_FILENAME = ".pose_library.json"
PRESERVED_METADATA_FILES = {CACHE_FILENAME, ".pose_orientation_cache.json"}
POSTURES = {"standing", "sitting", "lying", "kneeling", "all_fours", "crouching", "bent_over", "unknown"}
ORIENTATIONS = {"front", "back", "left_side", "right_side", "three_quarter_front", "three_quarter_back", "unknown"}
FRAMINGS = {"full_body", "upper_body", "lower_body", "partial", "unknown"}
POSE_ANALYSIS_CACHE_VERSION = 2

ProgressCallback = Callable[[int, int, int, int, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PoseCleanupResult:
    valid_pairs: int
    deleted_files: int
    incomplete_sets: int
    extra_files: int


class PoseLibraryIndex:
    """Persistent Vision metadata for pose-reference image pairs."""

    def __init__(self, root: Path, analyzer: Any) -> None:
        self.root = root.resolve()
        self.analyzer = analyzer
        self.path = self.root / CACHE_FILENAME
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            version = payload.get("version", 0) if isinstance(payload, dict) else 0
            entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
            self._entries = entries if version == POSE_ANALYSIS_CACHE_VERSION and isinstance(entries, dict) else {}
        except (OSError, ValueError, TypeError):
            self._entries = {}

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"version": POSE_ANALYSIS_CACHE_VERSION, "entries": self._entries}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def _key(self, image_path: Path) -> str:
        return image_path.resolve().relative_to(self.root).as_posix()

    @staticmethod
    def _sha256(image: bytes) -> str:
        return hashlib.sha256(image).hexdigest()

    @staticmethod
    def _tags(value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            tag = " ".join(str(item).strip().lower().split())[:80]
            if tag and tag not in result:
                result.append(tag)
            if len(result) >= limit:
                break
        return result

    @classmethod
    def _normalize(cls, value: Any) -> dict[str, Any]:
        value = value if isinstance(value, dict) else {}
        posture = str(value.get("posture", "unknown")).strip().lower()
        orientation = str(value.get("orientation", "unknown")).strip().lower()
        framing = str(value.get("framing", "unknown")).strip().lower()
        try:
            confidence = float(value.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        return {
            "posture": posture if posture in POSTURES else "unknown",
            "orientation": orientation if orientation in ORIENTATIONS else "unknown",
            "activity_tags": cls._tags(value.get("activity_tags"), 6),
            "support": cls._tags(value.get("support"), 8),
            "arms": " ".join(str(value.get("arms", "unknown")).strip().split())[:160] or "unknown",
            "legs": " ".join(str(value.get("legs", "unknown")).strip().split())[:160] or "unknown",
            "framing": framing if framing in FRAMINGS else "unknown",
            "keywords_ru": cls._tags(value.get("keywords_ru"), 10),
            "confidence": max(0.0, min(1.0, confidence)),
        }

    def pose_images(self) -> list[Path]:
        """Return the canonical OpenPose image from every valid pair."""
        if not self.root.is_dir():
            return []
        return sorted(
            path for path in self.root.rglob("*")
            if path.is_file()
            and path.name.endswith("_bone_structure.png")
            and path.with_name(
                path.name.removesuffix("_bone_structure.png") + "_depth.png"
            ).is_file()
        )

    def _analysis_pairs(self) -> list[tuple[Path, Path]]:
        """Return (bone_structure, depth) for every valid pair."""
        return [
            (bone_path, bone_path.with_name(
                bone_path.name.removesuffix("_bone_structure.png") + "_depth.png"
            ))
            for bone_path in self.pose_images()
        ]

    def cleanup_pairs(self) -> PoseCleanupResult:
        """Keep only complete *_bone_structure.png / *_depth.png pairs.

        Metadata caches are intentionally excluded.
        """
        if not self.root.is_dir():
            return PoseCleanupResult(0, 0, 0, 0)

        files = [path for path in self.root.rglob("*") if path.is_file()]
        protected = [path for path in files if path.name in PRESERVED_METADATA_FILES]
        assets = [path for path in files if path not in protected]
        valid_pairs = 0
        incomplete_sets = 0
        delete_targets: set[Path] = set()
        handled: set[Path] = set()

        for bone_path in assets:
            if not bone_path.name.endswith("_bone_structure.png"):
                continue
            base = bone_path.name.removesuffix("_bone_structure.png")
            depth_path = bone_path.with_name(base + "_depth.png")
            group = [
                path for path in assets
                if path.parent == bone_path.parent
                and (path.name == base or path.name.startswith(base + "_"))
            ]
            handled.update(group)
            if depth_path in assets:
                valid_pairs += 1
                delete_targets.update(
                    path for path in group if path not in {bone_path, depth_path}
                )
            else:
                incomplete_sets += 1
                delete_targets.update(group)

        for path in assets:
            if path not in handled:
                delete_targets.add(path)

        extra_files = sum(1 for path in delete_targets if path not in handled)
        for path in sorted(delete_targets):
            path.unlink(missing_ok=True)

        self._load()
        remaining = {self._key(path) for path in self.pose_images()}
        stale_keys = [key for key in self._entries if key not in remaining]
        for key in stale_keys:
            del self._entries[key]
        if stale_keys:
            self._save()

        return PoseCleanupResult(
            valid_pairs=valid_pairs,
            deleted_files=len(delete_targets),
            incomplete_sets=incomplete_sets,
            extra_files=extra_files,
        )

    def get_analysis(self, image_path: Path | None) -> dict[str, Any] | None:
        """Return cached semantic pose metadata for a selected pose image."""
        if image_path is None:
            return None
        self._load()
        candidates = [image_path]
        name = image_path.name
        if name.endswith("_noise_final_openpose.png"):
            base = name.removesuffix("_noise_final_openpose.png")
            candidates.append(image_path.with_name(base + "_bone_structure.png"))
        elif name.endswith("_depth.png"):
            base = name.removesuffix("_depth.png")
            candidates.append(image_path.with_name(base + "_bone_structure.png"))
        elif name.endswith("_bone_structure.png"):
            candidates.append(image_path)
        for candidate in candidates:
            try:
                key = self._key(candidate)
            except ValueError:
                continue
            entry = self._entries.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("analysis"), dict):
                return entry["analysis"]
        return None

    async def analyze_all(
        self, on_progress: ProgressCallback | None = None,
    ) -> tuple[int, int, list[str]]:
        self._load()
        pairs = self._analysis_pairs()
        analyzed = 0
        cached = 0
        failures: list[str] = []
        total = len(pairs)

        for index, (bone_path, depth_path) in enumerate(pairs, 1):
            # Depth maps contain the silhouette/body geometry in a much clearer
            # form for semantic Vision analysis than the OpenPose skeleton.
            image = depth_path.read_bytes()
            key = self._key(bone_path)
            digest = self._sha256(image)
            entry = self._entries.get(key)
            if isinstance(entry, dict) and entry.get("sha256") == digest:
                cached += 1
            else:
                try:
                    analysis = self._normalize(await self.analyzer.analyze_pose_metadata(image))
                    self._entries[key] = {
                        "sha256": digest,
                        "analysis_version": POSE_ANALYSIS_CACHE_VERSION,
                        "analysis_source": self._key(depth_path),
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                        "analysis": analysis,
                    }
                    self._save()
                    analyzed += 1
                except Exception as exc:
                    failures.append(f"{key}: {exc}")

            if on_progress is not None:
                await on_progress(index, total, analyzed, cached, key)

        return analyzed, cached, failures
