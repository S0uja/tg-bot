from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    face_file_id TEXT,
                    body_reference_file_id TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    weight REAL,
                    bust REAL,
                    age INTEGER,
                    weight_profile TEXT,
                    body_shape TEXT,
                    bust_size INTEGER,
                    bust_shape TEXT,
                    age_category TEXT,
                    hairstyle TEXT,
                    hair_color TEXT,
                    consistency_strength TEXT DEFAULT 'medium'
                );

                CREATE INDEX IF NOT EXISTS idx_characters_user_id
                    ON characters(user_id);

                CREATE TABLE IF NOT EXISTS generations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    character_id INTEGER,
                    kind TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    pose TEXT,
                    clothing TEXT,
                    status TEXT NOT NULL,
                    result_path TEXT,
                    provider TEXT,
                    provider_job_id TEXT,
                    enhanced_prompt TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(character_id)
                        REFERENCES characters(id)
                        ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_generations_user_character
                    ON generations(user_id, character_id, id DESC);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    character_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chat_messages_user_character
                    ON chat_messages(user_id, character_id, id DESC);
                """
            )
            await self._migrate(db)
            await db.commit()

    async def clear_all(self) -> dict[str, int]:
        """Delete all application data while preserving the database schema."""
        counts: dict[str, int] = {}
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = OFF")
            async with db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]

            for table in tables:
                async with db.execute(f"SELECT COUNT(*) FROM [{table}]") as cursor:
                    row = await cursor.fetchone()
                counts[table] = int(row[0] or 0)
                await db.execute(f"DELETE FROM [{table}]")

            # Reset AUTOINCREMENT counters when sqlite_sequence exists.
            try:
                await db.execute("DELETE FROM sqlite_sequence")
            except aiosqlite.OperationalError:
                pass

            await db.execute("PRAGMA foreign_keys = ON")
            await db.commit()
            await db.execute("VACUUM")

        return counts

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        async with db.execute("PRAGMA table_info(characters)") as cursor:
            character_columns = {row[1] for row in await cursor.fetchall()}
        if "updated_at" not in character_columns:
            await db.execute("ALTER TABLE characters ADD COLUMN updated_at TEXT")
        for name, sql_type in (("body_reference_file_id", "TEXT"), ("weight", "REAL"), ("bust", "REAL"), ("age", "INTEGER"), ("weight_profile", "TEXT"), ("body_shape", "TEXT"), ("bust_size", "INTEGER"), ("bust_shape", "TEXT"), ("age_category", "TEXT"), ("hairstyle", "TEXT"), ("hair_color", "TEXT"), ("consistency_strength", "TEXT")):
            if name not in character_columns:
                await db.execute(f"ALTER TABLE characters ADD COLUMN {name} {sql_type}")
        await db.execute(
            "UPDATE characters SET consistency_strength = 'medium' "
            "WHERE consistency_strength IS NULL OR TRIM(consistency_strength) = ''"
        )
        await db.execute(
            "UPDATE characters SET body_shape = 'Песочные часы' "
            "WHERE body_shape IS NULL OR TRIM(body_shape) = ''"
        )

        async with db.execute("PRAGMA table_info(generations)") as cursor:
            generation_columns = {row[1] for row in await cursor.fetchall()}

        additions = {
            "provider": "TEXT",
            "provider_job_id": "TEXT",
            "enhanced_prompt": "TEXT",
            "error": "TEXT",
            "started_at": "TEXT",
            "completed_at": "TEXT",
            "favorite": "INTEGER NOT NULL DEFAULT 0",
            "pose": "TEXT",
            "clothing": "TEXT",
            "result_path": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'queued'",
        }
        for name, sql_type in additions.items():
            if name not in generation_columns:
                await db.execute(
                    f"ALTER TABLE generations ADD COLUMN {name} {sql_type}"
                )
