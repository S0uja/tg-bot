from main.domain.errors import NotFoundError, ValidationError
from main.domain.models import Character
from main.infrastructure.ai.llm.base import VisionDescriber
from main.infrastructure.database.repositories.characters import CharacterRepository
from main.infrastructure.storage.base import MediaStorage
from characters.analysis import normalize_analysis
from characters.face_reference import prepare_face_references


class CharacterService:
    def __init__(
        self,
        characters: CharacterRepository,
        vision: VisionDescriber,
        storage: MediaStorage,
    ) -> None:
        self.characters = characters
        self.vision = vision
        self.storage = storage

    async def analyze_reference(self, image: bytes) -> dict:
        raw = await self.vision.analyze_character(image)
        return normalize_analysis(raw)

    async def describe_face(self, image: bytes) -> str:
        analysis = await self.analyze_reference(image)
        return analysis.get("description", "")

    async def save_face(self, image: bytes, character_key: str) -> str:
        """Save the original and processed face references in one character folder."""
        folder = f"character_{character_key}"
        original_name = f"{folder}/character_{character_key}.jpg"
        original_path = await self.storage.save(image, original_name)
        try:
            tight, full = prepare_face_references(image)
            await self.storage.save(tight, f"{folder}/face_reference.jpg")
            await self.storage.save(full, f"{folder}/face_reference_full.jpg")
        except Exception:
            # The original reference is always preserved even if preprocessing fails.
            pass
        return original_path

    async def set_face_file(self, character_id: int, face_file_id: str) -> bool:
        return await self.characters.set_face_file(character_id, face_file_id)

    async def read_face(self, face_file_id: str | None) -> bytes | None:
        if not face_file_id:
            return None
        try:
            return await self.storage.read(face_file_id)
        except (FileNotFoundError, OSError):
            return None

    async def create(
        self,
        user_id: int,
        name: str,
        face_file_id: str,
        description: str,
        *,
        weight_profile: str | None = None,
        bust_size: int | None = None,
        age_category: str | None = None,
        hairstyle: str | None = None,
        hair_color: str | None = None,
    ) -> int:
        name = name.strip()[:80]
        description = description.strip()[:4000]
        if not name:
            raise ValidationError("Имя персонажа не может быть пустым.")
        character_id = await self.characters.create(
            user_id=user_id,
            name=name,
            face_file_id=face_file_id,
            description=description,
        )
        await self.update(
            user_id, character_id,
            weight_profile=weight_profile, bust_size=bust_size,
            age_category=age_category, hairstyle=hairstyle, hair_color=hair_color,
        )
        return character_id

    async def list(self, user_id: int) -> list[Character]:
        return await self.characters.list(user_id)

    async def get(self, user_id: int, character_id: int) -> Character:
        character = await self.characters.get(user_id, character_id)
        if character is None:
            raise NotFoundError("Персонаж не найден.")
        return character

    async def update(
        self,
        user_id: int,
        character_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        weight: float | None = None,
        bust: float | None = None,
        age: int | None = None,
        weight_profile: str | None = None,
        bust_size: int | None = None,
        age_category: str | None = None,
        hairstyle: str | None = None,
        hair_color: str | None = None,
        consistency_strength: str | None = None,
    ) -> bool:
        if name is not None:
            name = name.strip()[:80]
            if not name:
                raise ValidationError("Имя персонажа не может быть пустым.")
        if description is not None:
            description = description.strip()[:1000]
        if weight is not None and not (30 <= weight <= 300):
            raise ValidationError("Вес должен быть от 30 до 300 кг.")
        if bust is not None and not (50 <= bust <= 200):
            raise ValidationError("Объём груди должен быть от 50 до 200 см.")
        if age is not None and not (18 <= age <= 100):
            raise ValidationError("Возраст должен быть от 18 до 100 лет.")
        if weight_profile is not None and weight_profile not in {"Очень худая", "Худая", "Нормальная", "Пышная", "Толстая"}:
            raise ValidationError("Недопустимый вариант веса.")
        if bust_size is not None and bust_size not in {1, 2, 3, 4}:
            raise ValidationError("Размер груди должен быть 1, 2, 3 или 4.")
        if age_category is not None and age_category not in {"Молодая", "Милф", "Зрелая"}:
            raise ValidationError("Недопустимая возрастная категория.")
        if hairstyle is not None and hairstyle not in {
            "Длинные прямые", "Длинные волнистые", "Длинные кудрявые", "Каре",
            "Удлинённое каре", "Каскад", "Пикси", "Высокий хвост",
            "Низкий хвост", "Коса", "Пучок",
        }:
            raise ValidationError("Недопустимый вариант прически.")
        if hair_color is not None and hair_color not in {
            "Чёрные", "Тёмно-каштановые", "Каштановые", "Светло-каштановые",
            "Блонд", "Платиновый блонд", "Рыжие", "Тёмно-рыжие", "Седые",
        }:
            raise ValidationError("Недопустимый цвет волос.")
        if consistency_strength is not None and consistency_strength not in {"low", "medium", "high", "maximum"}:
            raise ValidationError("Недопустимая сила Character Consistency.")
        return await self.characters.update(
            user_id, character_id, name=name, description=description,
            weight=weight, bust=bust, age=age,
            weight_profile=weight_profile, bust_size=bust_size, age_category=age_category,
            hairstyle=hairstyle, hair_color=hair_color, consistency_strength=consistency_strength,
        )

    async def delete(self, user_id: int, character_id: int) -> bool:
        return await self.characters.delete(user_id, character_id)

    async def duplicate(self, user_id: int, character_id: int) -> int:
        source = await self.get(user_id, character_id)
        new_name = f"{source.name} копия"[:80]
        new_id = await self.characters.create(
            user_id=user_id,
            name=new_name,
            face_file_id=source.face_file_id,
            description=source.description,
        )
        await self.characters.update(
            user_id, new_id,
            weight=source.weight, bust=source.bust, age=source.age,
            weight_profile=source.weight_profile, bust_size=source.bust_size,
            age_category=source.age_category, hairstyle=source.hairstyle,
            hair_color=source.hair_color,
        )
        return new_id
