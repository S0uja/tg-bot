import asyncio
import json
import tempfile
from pathlib import Path

from poses.library import PoseLibraryIndex


class FakePoseAnalyzer:
    def __init__(self):
        self.calls = 0

    async def analyze_pose_metadata(self, image: bytes) -> dict:
        self.calls += 1
        return {
            "posture": "lying",
            "orientation": "front",
            "activity_tags": ["floor exercise"],
            "support": ["floor", "back"],
            "arms": "raised",
            "legs": "bent",
            "framing": "full_body",
            "keywords_ru": ["упражнение", "на полу"],
            "confidence": 0.9,
        }


def test_pose_library_skips_unchanged_images_and_reanalyzes_changes():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original = root / "exercise.jpg"
        original.write_bytes(b"first image")
        (root / "exercise_depth.png").write_bytes(b"derived")
        (root / "exercise_noise_final_openpose.png").write_bytes(b"derived")
        analyzer = FakePoseAnalyzer()
        library = PoseLibraryIndex(root, analyzer)

        analyzed, cached, failures = asyncio.run(library.analyze_all())
        assert (analyzed, cached, failures) == (1, 0, [])
        assert analyzer.calls == 1

        analyzed, cached, failures = asyncio.run(library.analyze_all())
        assert (analyzed, cached, failures) == (0, 1, [])
        assert analyzer.calls == 1

        original.write_bytes(b"changed image")
        analyzed, cached, failures = asyncio.run(library.analyze_all())
        assert (analyzed, cached, failures) == (1, 0, [])
        payload = json.loads((root / ".pose_library.json").read_text(encoding="utf-8"))
        assert payload["entries"]["exercise.jpg"]["analysis"]["keywords_ru"] == ["упражнение", "на полу"]
