import asyncio

from main.infrastructure.ai.llm.openai_compatible import (
    IMAGE_PROMPT_SYSTEM,
    VIDEO_PROMPT_SYSTEM,
    OpenAICompatibleLLM,
)


class CaptureLLM(OpenAICompatibleLLM):
    def __init__(self):
        self.url = self.api_key = self.model = self.vision_model = "test"
        self.payloads = []

    async def _chat(self, payload):
        self.payloads.append(payload)
        return {"choices": [{"message": {"content": "short generated prompt"}}]}


def test_system_prompts_are_compact():
    assert len(IMAGE_PROMPT_SYSTEM) < 800
    assert len(VIDEO_PROMPT_SYSTEM) < 800


def test_limits_llm_output_tokens():
    llm = CaptureLLM()
    asyncio.run(llm.enhance_image_prompt(type("C", (), {
        "scene": "girl sitting on a bed",
        "character_description": "brown hair",
        "pose": "",
        "clothing": "",
    })()))
    assert llm.payloads[-1]["max_tokens"] == 128

    asyncio.run(llm.translate_video_prompt("girl slowly lies down"))
    assert llm.payloads[-1]["max_tokens"] == 160
