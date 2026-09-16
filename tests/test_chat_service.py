import asyncio
import tempfile
import unittest
from pathlib import Path

from chat.service import ChatService
from main.domain.models import Character
from main.infrastructure.database.connection import Database


class FakeLLM:
    def __init__(self, responses=None):
        self.prompts = []
        self.responses = list(responses or ["ага"])

    async def chat(self, prompt):
        self.prompts.append(prompt)
        if len(self.prompts) <= len(self.responses):
            return self.responses[len(self.prompts) - 1]
        return self.responses[-1]


class ChatServiceTests(unittest.TestCase):
    def test_current_user_message_is_not_duplicated(self):
        llm = FakeLLM()
        service = ChatService(llm, None)
        character = Character(1, 1, "Соня", None, "спокойная, ироничная девушка", "", None)
        asyncio.run(service.reply(character, [{"role": "user", "content": "Привет"}], "Как дела?"))
        prompt = llm.prompts[0]
        self.assertEqual(prompt.count("USER: Как дела?"), 1)
        self.assertIn("do not end every message with a question", prompt.lower())
        self.assertIn("CURRENT CONVERSATIONAL MOOD", prompt)
        self.assertIn('"media_type": "photo" or "none"', prompt)
        self.assertIn("PHOTO DECISION", prompt)

    def test_chat_memory_survives_between_sessions(self):
        async def run():
            with tempfile.TemporaryDirectory() as td:
                db = Database(Path(td) / "chat.sqlite3")
                await db.init()
                service = ChatService(FakeLLM(), db)
                await service.remember(10, 2, "user", "Мне нравится кофе без сахара")
                await service.remember(10, 2, "assistant", "ага")
                history = await service.history(10, 2)
                self.assertEqual(history[0]["content"], "Мне нравится кофе без сахара")
                self.assertEqual(len(history), 2)
        asyncio.run(run())

    def test_video_note_request_detection(self):
        self.assertTrue(ChatService.wants_video_note("А кружок мне заснимешь?)"))
        self.assertTrue(ChatService.wants_video_note("сними мне короткий видос"))
        self.assertFalse(ChatService.wants_video_note("не надо видео"))
        self.assertFalse(ChatService.wants_video_note("как дела?"))

    def test_structured_photo_decision(self):
        result = ChatService._parse_result(
            '{"reply":"блин, ну ладно, сейчас покажусь","media_type":"photo",'
            '"media_prompt":"evening at home, oversized white shirt, standing by the window, casual selfie, warm room light"}'
        )
        self.assertEqual(result.reply, "блин, ну ладно, сейчас покажусь")
        self.assertEqual(result.media_type, "photo")
        self.assertIn("oversized white shirt", result.media_prompt)

    def test_plain_qwen_reply_does_not_trigger_media(self):
        result = ChatService._parse_result("привет, я дома")
        self.assertEqual(result.media_type, "none")

    def test_retries_repeated_character_reply(self):
        llm = FakeLLM([
            '{"reply":"Ты бы не сжимал, я же худая.","media_type":"none","media_prompt":""}',
            '{"reply":"Ну давай, рассказывай, что у тебя сегодня случилось.","media_type":"none","media_prompt":""}',
        ])
        service = ChatService(llm, None)
        character = Character(1, 1, "Соня", None, "спокойная, ироничная девушка", "", None)
        history = [
            {"role": "user", "content": "Предыдущая фраза"},
            {"role": "assistant", "content": "Ты бы не сжимал, я же худая."},
        ]
        result = asyncio.run(service.reply(character, history, "Что делаешь сейчас?"))
        self.assertEqual(result.reply, "Ну давай, рассказывай, что у тебя сегодня случилось.")
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("CURRENT USER MESSAGE", llm.prompts[1])
        self.assertIn("RESPONSE REPAIR", llm.prompts[1])

    def test_compact_dialogue_uses_character_role(self):
        llm = FakeLLM(['{"reply":"нормально, отдыхаю","media_type":"none","media_prompt":""}'])
        service = ChatService(llm, None)
        character = Character(1, 1, "Соня", None, "спокойная, ироничная девушка", "", None)
        asyncio.run(service.reply(character, [
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Привет"},
        ], "Что делаешь?"))
        prompt = llm.prompts[0]
        self.assertIn("USER: Привет", prompt)
        self.assertIn("CHARACTER: Привет", prompt)
        self.assertEqual(prompt.count("CURRENT USER MESSAGE:\nЧто делаешь?"), 1)

    def test_visual_state_is_passed_to_prompt(self):
        llm = FakeLLM(['{"reply":"сейчас","media_type":"none","media_prompt":""}'])
        service = ChatService(llm, None)
        character = Character(1, 1, "Соня", None, "спокойная, ироничная девушка", "", None)
        asyncio.run(service.reply(
            character,
            [],
            "Покажись",
            current_scene="evening at home, green sweater, sitting by the window",
        ))
        prompt = llm.prompts[0]
        self.assertIn("CURRENT VISUAL STATE FROM THE LAST PHOTO", prompt)
        self.assertIn("green sweater", prompt)

    def test_clear_history(self):
        async def run():
            with tempfile.TemporaryDirectory() as td:
                db = Database(Path(td) / "chat.sqlite3")
                await db.init()
                service = ChatService(FakeLLM(), db)
                await service.remember(10, 2, "user", "hello")
                await service.remember(10, 2, "assistant", "hi")
                await service.clear_history(10, 2)
                self.assertEqual(await service.history(10, 2), [])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
