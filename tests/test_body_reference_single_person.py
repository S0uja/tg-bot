from pathlib import Path

def test_body_reference_service_prompt_is_single_person():
    path = Path(__file__).parents[1] / "app" / "application" / "image_generation" / "service.py"
    text = path.read_text(encoding="utf-8")
    assert "single adult woman, one person only, one body only" in text
    assert "shown in two full-body views side by side" not in text
    assert "three-quarter view" not in text
