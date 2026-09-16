import asyncio

from videos.service import VideoGenerationService


class Enhancer:
    async def translate_video_prompt(self, prompt: str, image=None) -> str:
        return "a woman slowly turns toward the camera, gentle camera push in"


class Character:
    id = 2
    face_file_id = "x"


class Characters:
    async def get(self, user_id, character_id):
        return Character()


class Generations:
    async def create(self, **kwargs): return 1
    async def set_status(self, *args): pass
    async def complete(self, *args, **kwargs): pass
    async def fail(self, *args): pass


class Storage:
    async def read(self, file_id): return b"face"
    async def save(self, result, name): return name


class ImageService:
    async def generate_video_start_frame(self, **kwargs):
        assert kwargs["description"] == "a woman slowly turns toward the camera, gentle camera push in"
        return Character(), b"generated-start-frame", "full body, woman facing camera"


class Video:
    async def generate(self, **kwargs):
        assert kwargs["prompt"] == "a woman slowly turns toward the camera, gentle camera push in"
        assert kwargs["reference_image"] == b"generated-start-frame"
        return b"video"


def test_video_uses_generated_start_frame_and_same_prompt():
    service = VideoGenerationService(
        Characters(), Generations(), Video(), Storage(), Enhancer(), ImageService()
    )
    result = asyncio.run(service.generate(1, 2, "женщина медленно поворачивается к камере"))
    assert result[1] == b"video"
    assert result[3] == b"generated-start-frame"
