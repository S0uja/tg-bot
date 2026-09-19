import asyncio
import unittest

from main.prompts.service import PromptService
from main.domain.models import ImagePromptContext


class FakeEnhancer:
    async def enhance_image_prompt(self, context):
        return "indoor sports hall, gym floor, sports equipment, woman standing, sportswear, expressive eyes"


class PromptOrderTest(unittest.TestCase):
    def test_scene_is_first_and_profile_is_not_duplicated(self):
        service = PromptService(FakeEnhancer())
        context = ImagePromptContext(
            character_description="young woman with light brown hair",
            scene="спортзал, стоит у баскетбольной площадки, в спортивной одежде",
            weight_profile="Очень худая",
            bust_size=1,
            age_category="Молодая",
            hairstyle="Удлинённое каре",
            hair_color="Светло-каштановые",
        )
        result = asyncio.run(service.build_image_prompt(context)).positive
        self.assertTrue(result.startswith("indoor sports hall"))
        self.assertEqual(result.count("very thin, extremely slim build"), 1)
        self.assertEqual(result.count("young adult woman"), 1)
        self.assertEqual(result.count("long bob haircut"), 1)
        self.assertLess(result.index("sports hall"), result.index("very thin"))

    def test_pose_prompt_locks_natural_head_to_body_proportion(self):
        service = PromptService(FakeEnhancer())
        result = asyncio.run(service.build_image_prompt(ImagePromptContext(
            character_description="adult woman",
            scene="in a studio",
            pose="seated pose",
        ))).positive
        self.assertIn("natural adult head-to-body proportion", result)
        self.assertIn("approximately 8 percent smaller", result)
        self.assertIn("do not enlarge the head relative to the body", result)
        self.assertIn("exactly two arms", result)
        self.assertIn("one continuous anatomically connected body", result)


if __name__ == "__main__":
    unittest.main()
