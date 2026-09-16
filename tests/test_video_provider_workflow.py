import json
import tempfile
import unittest
from pathlib import Path

from videos.provider.comfyui import ComfyUIVideoGenerator


class Character:
    id = 1


class VideoProviderWorkflowTest(unittest.TestCase):
    def test_provider_prepares_raw_ltxv_without_reactor(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = {
                "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": "old", "type": "ltxv"}},
                "44": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltxv-2b-0.9.8-distilled-fp8.safetensors"}},
                "78": {"class_type": "LoadImage", "inputs": {"image": "face_default.png"}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                "95": {"class_type": "LTXVImgToVideo", "inputs": {"length": 97, "strength": 1.0}},
                "103": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["8", 0]}},
                "102": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
            }
            wf = Path(tmp) / "workflow.json"
            wf.write_text(json.dumps(workflow), encoding="utf-8")
            provider = ComfyUIVideoGenerator(
                base_url="http://127.0.0.1:8188", workflow_path=str(wf), input_path=str(Path(tmp) / "input"),
                timeout=1, poll_interval=0.1, text_encoder_name="t5xxl_fp8_e4m3fn.safetensors",
            )
            result = provider._prepare_workflow(Character(), "new prompt", b"PNG", duration_frames=145)
            self.assertEqual(result["38"]["inputs"]["clip_name"], "t5xxl_fp8_e4m3fn.safetensors")
            self.assertEqual(result["44"]["inputs"]["ckpt_name"], "ltxv-2b-0.9.8-distilled-fp8.safetensors")
            self.assertEqual(result["6"]["inputs"]["text"], "new prompt")
            self.assertEqual(result["95"]["inputs"]["length"], 145)
            self.assertEqual(result["103"]["inputs"]["images"], ["8", 0])
            self.assertFalse(any(node.get("class_type") == "ReActorFaceSwap" for node in result.values() if isinstance(node, dict)))

    def test_separate_video_reface_workflow_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "reactor.json"
            wf.write_text(json.dumps({
                "1": {"class_type": "VHS_LoadVideo", "inputs": {"video": "old.mp4"}},
                "2": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
                "3": {"class_type": "ReActorFaceSwap", "inputs": {}},
                "4": {"class_type": "VHS_VideoCombine", "inputs": {"images": []}},
            }), encoding="utf-8")
            provider = ComfyUIVideoGenerator(
                base_url="http://127.0.0.1:8188", workflow_path=str(wf), input_path=str(Path(tmp) / "input"),
                timeout=1, poll_interval=0.1,
                reactor_workflow_path=str(wf),
            )
            result = provider._prepare_reface_workflow("video.mp4", "face.png")
            self.assertEqual(result["1"]["inputs"]["video"], "video.mp4")
            self.assertEqual(result["2"]["inputs"]["image"], "face.png")
            self.assertEqual(result["3"]["inputs"]["input_image"], ["1", 0])
            self.assertEqual(result["3"]["inputs"]["source_image"], ["2", 0])
            self.assertEqual(result["4"]["inputs"]["images"], ["3", 0])


if __name__ == "__main__":
    unittest.main()
