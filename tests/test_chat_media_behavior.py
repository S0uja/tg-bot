import unittest

from chat.service import ChatService, CHAT_SYSTEM_PROMPT


class ChatMediaBehaviorTests(unittest.TestCase):
    def test_media_is_optional_and_context_driven(self):
        text = CHAT_SYSTEM_PROMPT.lower()
        self.assertIn("most replies should contain no media", text)
        self.assertIn("do not generate media just to make the conversation more interesting", text)
        self.assertIn('"media_type": "none"', text)

    def test_media_parser_accepts_only_supported_types(self):
        photo = ChatService._parse_result(
            '{"reply":"сейчас","media_type":"photo","media_prompt":"casual selfie at home"}'
        )
        note = ChatService._parse_result(
            '{"reply":"сек","media_type":"video_note","media_prompt":"short selfie video"}'
        )
        invalid = ChatService._parse_result(
            '{"reply":"ага","media_type":"voice","media_prompt":"audio"}'
        )
        self.assertEqual(photo.media_type, "photo")
        self.assertEqual(note.media_type, "video_note")
        self.assertEqual(invalid.media_type, "none")


if __name__ == "__main__":
    unittest.main()
