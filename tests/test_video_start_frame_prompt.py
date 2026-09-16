import asyncio

from main.prompts.service import PromptService
from main.domain.models import ImagePromptContext


class Enhancer:
    async def enhance_image_prompt(self, context):
        assert "exact opening still frame" in context.scene
        assert "every body part required" in context.scene
        assert "full-body" in context.scene
        return "indoor room, full body, legs visible, seated starting pose, casual clothing"


class TestablePromptService(PromptService):
    pass


def test_video_start_frame_prompt_requires_action_relevant_framing():
    service = TestablePromptService(Enhancer())
    result = asyncio.run(
        service.build_video_start_frame_prompt(
            ImagePromptContext(
                character_description="adult woman, dark hair",
                scene="the character crosses her legs",
                pose="",
                clothing="casual outfit",
            )
        )
    )
    assert "full body" in result.positive
