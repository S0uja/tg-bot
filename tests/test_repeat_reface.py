from pathlib import Path


def test_image_repeat_contains_reface_call():
    text = Path("app/application/image_generation/service.py").read_text(encoding="utf-8")
    marker = "async def regenerate("
    section = text[text.index(marker):]
    assert "self.image_provider.generate(" in section
    assert "self.image_provider.reface(image=result, face_reference=face_bytes)" in section


def test_video_repeat_contains_reface_call():
    text = Path("app/application/video_generation/service.py").read_text(encoding="utf-8")
    marker = "async def regenerate_exact("
    section = text[text.index(marker):]
    assert "self.video_provider.generate(" in section
    assert "self.video_provider.reface(video=result, face_reference=identity_bytes)" in section


def test_repeat_media_is_spoiler():
    text = Path("app/presentation/telegram/bot.py").read_text(encoding="utf-8")
    image_marker = 'media=types.InputMediaPhoto('
    video_marker = 'media=types.InputMediaVideo('
    image_section = text[text.index(image_marker):text.index(image_marker) + 300]
    video_section = text[text.index(video_marker):text.index(video_marker) + 300]
    assert "has_spoiler=True" in image_section
    assert "has_spoiler=True" in video_section
