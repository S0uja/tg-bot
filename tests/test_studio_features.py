from pathlib import Path


def test_generation_model_has_favorite_field():
    text = Path("app/domain/models.py").read_text(encoding="utf-8")
    assert "favorite: int = 0" in text


def test_database_migrates_favorite():
    text = Path("app/infrastructure/database/connection.py").read_text(encoding="utf-8")
    assert 'favorite INTEGER NOT NULL DEFAULT 0' in text
    assert '"favorite": "INTEGER NOT NULL DEFAULT 0"' in text


def test_library_and_media_actions_exist():
    bot = Path("app/presentation/telegram/bot.py").read_text(encoding="utf-8")
    gen = Path("app/presentation/telegram/keyboards/generation.py").read_text(encoding="utf-8")
    menu = Path("app/presentation/telegram/keyboards/menu.py").read_text(encoding="utf-8")
    assert 'F.data == "menu:library"' in bot
    assert 'F.data.startswith("library:item:")' in bot
    assert 'F.data.startswith("favorite:")' in bot
    assert 'F.data.startswith("prompt:")' in bot
    assert 'callback_data="menu:library"' in menu
    assert 'callback_data=f"favorite:{generation_id}"' in gen


def test_character_duplicate_action_exists():
    kb = Path("app/presentation/telegram/keyboards/characters.py").read_text(encoding="utf-8")
    bot = Path("app/presentation/telegram/bot.py").read_text(encoding="utf-8")
    service = Path("app/application/characters/service.py").read_text(encoding="utf-8")
    assert 'clonecharacter:{character_id}' in kb
    assert 'F.data.startswith("clonecharacter:")' in bot
    assert 'async def duplicate(' in service
