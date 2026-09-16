from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def test_video_negative_prompt_blocks_skin_color_shift():
    data = json.loads((ROOT / "workflows" / "ltxvideo-i2v-distilled.json").read_text(encoding="utf-8"))
    text = data["7"]["inputs"]["text"].lower()
    for term in ("red skin", "skin color shift", "face color shift", "hand color shift", "uneven skin tone"):
        assert term in text

def test_video_prompt_code_adds_skin_tone_continuity():
    text = (ROOT / "app" / "infrastructure" / "ai" / "llm" / "openai_compatible.py").read_text(encoding="utf-8")
    assert "consistent natural skin tone throughout the entire video" in text
    assert "stable skin color" in text
    assert "consistent hand and face color from the first frame" in text
