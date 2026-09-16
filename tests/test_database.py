import tempfile
import unittest
from pathlib import Path

from main.infrastructure.database.connection import Database
from main.infrastructure.database.repositories.characters import SQLiteCharacterRepository
from main.infrastructure.database.repositories.generations import SQLiteGenerationRepository
from main.domain.enums import GenerationKind, GenerationStatus


class DatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.sqlite3"))
        await self.db.init()
        self.characters = SQLiteCharacterRepository(self.db)
        self.generations = SQLiteGenerationRepository(self.db)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_character_crud_and_generation(self):
        character_id = await self.characters.create(
            10, "Alice", "telegram-file-id", "description"
        )

        item = await self.characters.get(10, character_id)
        self.assertEqual(item.name, "Alice")

        items = await self.characters.list(10)
        self.assertEqual(len(items), 1)

        updated = await self.characters.update(
            10, character_id, name="Alice 2", description=None
        )
        self.assertTrue(updated)

        generation_id = await self.generations.create(
            user_id=10,
            character_id=character_id,
            kind=GenerationKind.IMAGE,
            prompt="scene",
            pose="standing",
            clothing="casual outfit",
            provider="comfyui",
        )
        await self.generations.set_status(
            generation_id, GenerationStatus.PROCESSING
        )
        await self.generations.complete(
            generation_id,
            result_path="data/media/generation_1.png",
            enhanced_prompt="enhanced",
        )

        latest = await self.generations.latest_image(10, character_id)
        self.assertEqual(latest.prompt, "scene")
        self.assertEqual(latest.pose, "standing")
        self.assertEqual(latest.clothing, "casual outfit")
        self.assertEqual(latest.status, GenerationStatus.COMPLETED)

        deleted = await self.characters.delete(10, character_id)
        self.assertTrue(deleted)


if __name__ == "__main__":
    unittest.main()
