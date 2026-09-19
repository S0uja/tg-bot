import unittest

from main.domain.models import ImagePromptContext
from main.prompts.builder import PromptBuilder


class PromptBuilderTest(unittest.TestCase):
    def test_parses_structured_scene_json_in_stable_order(self):
        spec = PromptBuilder.parse('{"subject":"adult woman","environment":"modern bedroom","action":"looking toward the window","composition":"full body","camera":"eye level","lighting":"soft evening light"}')
        result = PromptBuilder.render(spec, ImagePromptContext(character_description='adult woman', scene='test'))
        self.assertTrue(result.startswith('adult woman, modern bedroom, looking toward the window'))
        self.assertIn('full body', result)
        self.assertIn('soft evening light', result)

    def test_plain_text_falls_back_without_breaking_old_enhancers(self):
        spec = PromptBuilder.parse('modern bedroom, soft evening light, full body')
        result = PromptBuilder.render(spec, ImagePromptContext(character_description='adult woman', scene='test'))
        self.assertEqual(result, 'modern bedroom, soft evening light, full body')

    def test_fenced_json_is_supported(self):
        spec = PromptBuilder.parse('```json\n{"environment":"studio","lighting":"soft light"}\n```')
        self.assertEqual(spec.environment, 'studio')
        self.assertEqual(spec.lighting, 'soft light')