import unittest

from characters.keyboards import (
    age_category_choices,
    character_actions,
    character_list,
    character_profile_menu,
    hair_color_choices,
    hairstyle_choices,
    weight_profile_choices,
)
from images.generation_keyboards import image_actions, video_actions
from main.core.menu_keyboard import menu


class InlineUiTests(unittest.TestCase):
    def test_all_main_navigation_is_inline(self):
        markup = menu()
        self.assertTrue(markup.inline_keyboard)
        self.assertTrue(all(button.callback_data for row in markup.inline_keyboard for button in row))

    def test_main_menu_has_chat_entry(self):
        markup = menu()
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("menu:chat", callbacks)

    def test_character_card_has_generation_and_profile_actions(self):
        data = [button.callback_data for row in character_actions(7).inline_keyboard for button in row]
        self.assertIn("editprofile:7", data)
        self.assertIn("reference:7", data)
        self.assertIn("imagefromchar:7", data)
        self.assertIn("videofromchar:7", data)

    def test_profile_menu_has_current_values(self):
        data = [button.callback_data for row in character_profile_menu(
            7, weight="Пышная", bust=3, age="Милф", hairstyle="Каре", hair_color="Блонд"
        ).inline_keyboard for button in row]
        self.assertIn("profile:weight:7", data)
        self.assertIn("profile:bust:7", data)
        self.assertIn("profile:age:7", data)
        self.assertIn("profile:hair:7", data)
        self.assertIn("profile:color:7", data)

    def test_profile_choice_menus_have_back_button(self):
        for markup in (
            weight_profile_choices(7),
            age_category_choices(7),
            hairstyle_choices(7),
            hair_color_choices(7),
        ):
            callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
            self.assertTrue(any(value == "editprofile:7" for value in callbacks))

    def test_generation_actions_are_inline(self):
        image_markup = image_actions(7, 42)
        self.assertEqual(image_markup.inline_keyboard[0][0].callback_data, "image_animate:7:42")
        video_markup = video_actions(7, 42)
        self.assertEqual(video_markup.inline_keyboard[0][0].callback_data, "video_repeat:7:42")

    def test_character_list_has_menu_back(self):
        markup = character_list([(1, "Anna")], "character")
        self.assertEqual(markup.inline_keyboard[-1][0].callback_data, "menu:open")

    def test_chat_character_list_uses_chat_callbacks(self):
        markup = character_list([(1, "Anna")], "chat")
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "chat:1")


if __name__ == "__main__":
    unittest.main()
