from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

import aiosqlite

from main.domain.models import Character
from main.infrastructure.database.connection import Database


class CharacterRepository(Protocol):
    async def create(self, user_id: int, name: str, face_file_id: str | None, description: str) -> int: ...
    async def list(self, user_id: int) -> list[Character]: ...
    async def list_all(self) -> list[Character]: ...
    async def set_face_file(self, character_id: int, face_file_id: str) -> bool: ...
    async def set_body_reference_file(self, character_id: int, body_reference_file_id: str) -> bool: ...
    async def get(self, user_id: int, character_id: int) -> Character | None: ...
    async def update(self, user_id: int, character_id: int, *, name: str | None = None, description: str | None = None, weight: float | None = None, bust: float | None = None, age: int | None = None, weight_profile: str | None = None, body_shape: str | None = None, bust_size: int | None = None, bust_shape: str | None = None, age_category: str | None = None, hairstyle: str | None = None, hair_color: str | None = None, consistency_strength: str | None = None) -> bool: ...
    async def delete(self, user_id: int, character_id: int) -> bool: ...


class SQLiteCharacterRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, user_id, name, face_file_id, description) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                """
                INSERT INTO characters
                    (user_id, name, face_file_id, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, name, face_file_id, description, now, now),
            )
            await db.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def _row(row) -> Character:
        return Character(**dict(row))

    async def list(self, user_id: int) -> list[Character]:
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM characters WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            )
            return [self._row(row) for row in await cursor.fetchall()]

    async def list_all(self) -> list[Character]:
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM characters ORDER BY id ASC")
            return [self._row(row) for row in await cursor.fetchall()]

    async def set_face_file(self, character_id: int, face_file_id: str) -> bool:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                "UPDATE characters SET face_file_id = ?, updated_at = ? WHERE id = ?",
                (face_file_id, datetime.now(timezone.utc).isoformat(), character_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def set_body_reference_file(self, character_id: int, body_reference_file_id: str) -> bool:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                "UPDATE characters SET body_reference_file_id = ?, updated_at = ? WHERE id = ?",
                (body_reference_file_id, datetime.now(timezone.utc).isoformat(), character_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get(self, user_id: int, character_id: int) -> Character | None:
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM characters WHERE user_id = ? AND id = ?",
                (user_id, character_id),
            )
            row = await cursor.fetchone()
            return self._row(row) if row else None

    async def update(
        self,
        user_id,
        character_id,
        *,
        name=None,
        description=None,
        weight=None,
        bust=None,
        age=None,
        weight_profile=None,
        body_shape=None,
        bust_size=None,
        bust_shape=None,
        age_category=None,
        hairstyle=None,
        hair_color=None,
        consistency_strength=None,
    ) -> bool:
        fields, values = [], []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if weight is not None:
            fields.append("weight = ?")
            values.append(weight)
        if bust is not None:
            fields.append("bust = ?")
            values.append(bust)
        if age is not None:
            fields.append("age = ?")
            values.append(age)
        if weight_profile is not None:
            fields.append("weight_profile = ?")
            values.append(weight_profile)
        if bust_size is not None:
            fields.append("bust_size = ?")
            values.append(bust_size)
        if age_category is not None:
            fields.append("age_category = ?")
            values.append(age_category)
        if hairstyle is not None:
            fields.append("hairstyle = ?")
            values.append(hairstyle)
        if hair_color is not None:
            fields.append("hair_color = ?")
            values.append(hair_color)
        if body_shape is not None:
            fields.append("body_shape = ?")
            values.append(body_shape)
        if bust_shape is not None:
            fields.append("bust_shape = ?")
            values.append(bust_shape)
        if consistency_strength is not None:
            fields.append("consistency_strength = ?")
            values.append(consistency_strength)
        if not fields:
            return False

        fields.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.extend((user_id, character_id))

        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                f"UPDATE characters SET {', '.join(fields)} "
                "WHERE user_id = ? AND id = ?",
                values,
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete(self, user_id: int, character_id: int) -> bool:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                "DELETE FROM characters WHERE user_id = ? AND id = ?",
                (user_id, character_id),
            )
            await db.commit()
            return cursor.rowcount > 0
