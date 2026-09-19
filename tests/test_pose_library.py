import asyncio
import json
import tempfile
from pathlib import Path

from poses.library import PoseLibraryIndex


class FakePoseAnalyzer:
    def __init__(self):
        self.calls = 0
        self.inputs = []

    async def analyze_pose_metadata(self, image: bytes) -> dict:
        self.calls += 1
        self.inputs.append(image)
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


def test_pose_library_analyzes_depth_and_caches_by_depth_hash():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bone = root / "exercise_bone_structure.png"
        depth = root / "exercise_depth.png"
        bone.write_bytes(b"bone")
        depth.write_bytes(b"depth-first")
        analyzer = FakePoseAnalyzer()
        library = PoseLibraryIndex(root, analyzer)

        analyzed, cached, failures = asyncio.run(library.analyze_all())
        assert (analyzed, cached, failures) == (1, 0, [])
        assert analyzer.inputs == [b"depth-first"]

        analyzed, cached, failures = asyncio.run(library.analyze_all())
        assert (analyzed, cached, failures) == (0, 1, [])
        assert analyzer.calls == 1

        depth.write_bytes(b"depth-second")
        analyzed, cached, failures = asyncio.run(library.analyze_all())
        assert (analyzed, cached, failures) == (1, 0, [])
        assert analyzer.inputs == [b"depth-first", b"depth-second"]

        payload = json.loads((root / ".pose_library.json").read_text(encoding="utf-8"))
        entry = payload["entries"]["exercise_bone_structure.png"]
        assert entry["analysis_source"] == "exercise_depth.png"
        assert entry["analysis"]["keywords_ru"] == ["упражнение", "на полу"]
