import json
import unittest
from pathlib import Path


class VideoWorkflowTest(unittest.TestCase):
    def test_ltxv_create_workflow_uses_fixed_portrait_dimensions(self):
        path = Path(__file__).resolve().parents[1] / "workflows" / "ltxvideo-i2v-motion-create-video.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["38"]["inputs"]["clip_name"], "t5xxl_fp8_e4m3fn.safetensors")
        self.assertEqual(data["95"]["inputs"]["width"], 512)
        self.assertEqual(data["95"]["inputs"]["height"], 768)

    def test_ltxv_animate_workflow_exists(self):
        path = Path(__file__).resolve().parents[1] / "workflows" / "ltxvideo-i2v-motion-animate-image.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["38"]["inputs"]["clip_name"], "t5xxl_fp8_e4m3fn.safetensors")
        self.assertEqual(data["95"]["inputs"]["width"], 512)
        self.assertEqual(data["95"]["inputs"]["height"], 768)


if __name__ == "__main__":
    unittest.main()
