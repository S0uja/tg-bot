from pathlib import Path


def test_repeat_handlers_enable_spoiler_before_generation_and_disable_after():
    source = Path("app/presentation/telegram/bot.py").read_text(encoding="utf-8")
    image_block = source[source.index('async def regenerate_image'):source.index('async def animate_image_start')]
    video_block = source[source.index('async def repeat_video'):source.index('# ---------- Videos ----------')]

    assert 'InputMediaPhoto(media=current_file_id, has_spoiler=True)' in image_block
    assert 'InputMediaPhoto(\n                    media=types.BufferedInputFile(result, filename="image.png"),\n                    has_spoiler=False,' in image_block
    assert 'InputMediaVideo(media=current_file_id, has_spoiler=True)' in video_block
    assert 'InputMediaVideo(\n                    media=types.BufferedInputFile(result, filename="video.mp4"),\n                    has_spoiler=False,' in video_block


def test_repeat_services_call_separate_reface_stage():
    image = Path("app/application/image_generation/service.py").read_text(encoding="utf-8")
    video = Path("app/application/video_generation/service.py").read_text(encoding="utf-8")
    image_repeat = image[image.index('async def regenerate('):]
    video_repeat = video[video.index('async def regenerate_exact('):]
    assert '[REPEAT][IMAGE] Running separate ReActor refacing' in image_repeat
    assert 'self.image_provider.reface(image=result, face_reference=face_bytes)' in image_repeat
    assert '[REPEAT][VIDEO] Running separate ReActor refacing' in video_repeat
    assert 'self.video_provider.reface(video=result, face_reference=identity_bytes)' in video_repeat
