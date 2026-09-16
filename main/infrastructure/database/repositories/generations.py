from datetime import datetime, timezone
from typing import Protocol

import aiosqlite

from main.domain.enums import GenerationKind, GenerationStatus
from main.domain.models import Generation
from main.infrastructure.database.connection import Database


class GenerationRepository(Protocol):
    async def create(self, **kwargs) -> int: ...
    async def set_status(self, generation_id: int, status: GenerationStatus) -> None: ...
    async def complete(self, generation_id: int, result_path: str | None = None, enhanced_prompt: str | None = None) -> None: ...
    async def fail(self, generation_id: int, error: str) -> None: ...
    async def get(self, user_id: int, generation_id: int) -> Generation | None: ...
    async def latest_image(self, user_id: int, character_id: int) -> Generation | None: ...
    async def toggle_favorite(self, user_id: int, generation_id: int) -> bool | None: ...
    async def list_recent(self, user_id: int, limit: int = 12) -> list[Generation]: ...
    async def list_favorites(self, user_id: int, limit: int = 12) -> list[Generation]: ...


class SQLiteGenerationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        *,
        user_id: int,
        character_id: int | None,
        kind: GenerationKind,
        prompt: str,
        pose: str | None = None,
        clothing: str | None = None,
        provider: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                """
                INSERT INTO generations
                    (user_id, character_id, kind, prompt, pose, clothing,
                     status, provider, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, character_id, kind.value, prompt, pose, clothing,
                    GenerationStatus.QUEUED.value, provider, now,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def set_status(self, generation_id: int, status: GenerationStatus) -> None:
        started_at = (
            datetime.now(timezone.utc).isoformat()
            if status == GenerationStatus.PROCESSING
            else None
        )
        async with aiosqlite.connect(self.database.path) as db:
            if started_at:
                await db.execute(
                    "UPDATE generations SET status = ?, started_at = ? WHERE id = ?",
                    (status.value, started_at, generation_id),
                )
            else:
                await db.execute(
                    "UPDATE generations SET status = ? WHERE id = ?",
                    (status.value, generation_id),
                )
            await db.commit()

    async def complete(
        self,
        generation_id: int,
        result_path: str | None = None,
        enhanced_prompt: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute(
                """
                UPDATE generations
                SET status = ?, result_path = COALESCE(?, result_path),
                    enhanced_prompt = COALESCE(?, enhanced_prompt),
                    completed_at = ?, error = NULL
                WHERE id = ?
                """,
                (
                    GenerationStatus.COMPLETED.value,
                    result_path,
                    enhanced_prompt,
                    now,
                    generation_id,
                ),
            )
            await db.commit()

    async def fail(self, generation_id: int, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute(
                """
                UPDATE generations
                SET status = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (GenerationStatus.FAILED.value, error[:2000], now, generation_id),
            )
            await db.commit()

    @staticmethod
    def _row(row) -> Generation:
        data = dict(row)
        data["kind"] = GenerationKind(data["kind"])
        data["status"] = GenerationStatus(data["status"])
        data.setdefault("favorite", 0)
        return Generation(**data)

    async def get(self, user_id: int, generation_id: int) -> Generation | None:
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM generations WHERE user_id = ? AND id = ? LIMIT 1",
                (user_id, generation_id),
            )
            row = await cursor.fetchone()
            return self._row(row) if row else None

    async def latest_image(self, user_id: int, character_id: int) -> Generation | None:
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM generations
                WHERE user_id = ? AND character_id = ? AND kind = 'image'
                  AND status = 'completed'
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, character_id),
            )
            row = await cursor.fetchone()
            return self._row(row) if row else None

    async def toggle_favorite(self, user_id: int, generation_id: int) -> bool | None:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(
                "SELECT favorite FROM generations WHERE user_id = ? AND id = ?",
                (user_id, generation_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            new_value = 0 if int(row[0] or 0) else 1
            await db.execute(
                "UPDATE generations SET favorite = ? WHERE user_id = ? AND id = ?",
                (new_value, user_id, generation_id),
            )
            await db.commit()
            return bool(new_value)

    async def list_recent(self, user_id: int, limit: int = 12) -> list[Generation]:
        limit = max(1, min(int(limit), 50))
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM generations
                WHERE user_id = ? AND status = 'completed' AND result_path IS NOT NULL
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            )
            return [self._row(row) for row in await cursor.fetchall()]

    async def list_favorites(self, user_id: int, limit: int = 12) -> list[Generation]:
        limit = max(1, min(int(limit), 50))
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM generations
                WHERE user_id = ? AND favorite = 1 AND status = 'completed' AND result_path IS NOT NULL
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            )
            return [self._row(row) for row in await cursor.fetchall()]
