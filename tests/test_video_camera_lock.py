import asyncio

from main.infrastructure.ai.llm.openai_compatible import OpenAICompatibleLLM


class FakeLLM(OpenAICompatibleLLM):
    def __init__(self, response):
        self.response = response
        self.url = self.api_key = self.model = self.vision_model = "x"

    async def _chat(self, payload):
        return {"choices": [{"message": {"content": self.response}}]}


def run(prompt):
    llm = FakeLLM("woman falls backward onto the bed")
    return asyncio.run(llm.translate_video_prompt(prompt))


def test_locks_camera_when_user_only_requests_subject_motion():
    text = run("Девушка медленно падает спиной назад и ложится на кровать")
    assert "camera completely static and locked in place" in text.lower()
    assert "no zoom in" in text.lower()
    assert "no reframing" in text.lower()


def test_preserves_explicit_camera_motion():
    text = run("Девушка идет вперед, камера медленно приближается")
    assert "camera completely static and locked in place" not in text.lower()
