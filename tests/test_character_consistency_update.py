
import inspect
from main.infrastructure.database.repositories.characters import SQLiteCharacterRepository

def test_character_repository_update_accepts_consistency_strength():
    sig = inspect.signature(SQLiteCharacterRepository.update)
    assert "consistency_strength" in sig.parameters
