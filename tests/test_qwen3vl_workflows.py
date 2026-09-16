import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_qwen_text_workflow_uses_qwen3vl_and_has_api_output():
    wf = json.loads((ROOT / "main/workflows/qwen_prompt_create_api.json").read_text(encoding="utf-8"))
    qwen = next(v for v in wf.values() if v.get("class_type") == "AILab_QwenVL_GGUF")
    assert qwen["inputs"]["model_name"] == "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    assert qwen["inputs"]["max_tokens"] == 256
    assert qwen["inputs"]["keep_model_loaded"] is False
    assert any(v.get("class_type") == "SaveText" for v in wf.values())


def test_qwen_vision_workflow_connects_image_and_has_api_output():
    wf = json.loads((ROOT / "main/workflows/qwen_prompt_vision_api.json").read_text(encoding="utf-8"))
    qwen = next(v for v in wf.values() if v.get("class_type") == "AILab_QwenVL_GGUF")
    assert qwen["inputs"]["model_name"] == "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    assert qwen["inputs"]["image"] == ["1", 0]
    assert any(v.get("class_type") == "SaveText" for v in wf.values())


def test_qwen_provider_targets_standard_gguf_node():
    text = (ROOT / "main/infrastructure/ai/llm/comfyui_qwen.py").read_text(encoding="utf-8")
    assert 'node_type = "AILab_QwenVL_GGUF"' in text
    assert "AILab_QwenVL_GGUF_Advanced" not in text
    assert "build_video_prompts" not in text
