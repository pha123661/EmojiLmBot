import asyncio
import logging
from datetime import datetime

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.lock = asyncio.Lock()
        self.conn.row_factory = aiosqlite.Row

    @classmethod
    async def create_and_connect(cls, dsn: str, timeout=60, **kwargs):
        """Connect to the SQLite database."""
        del kwargs  # Unused in this context, but can be used for future extensions
        try:
            conn = await aiosqlite.connect(database=dsn, timeout=timeout)
            logger.info(f"SQLite connection to '{dsn}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating SQLite connection: {e}")
            raise

        db = cls(conn)
        await db.create_tables()
        return db

    async def close(self):
        """Closes the SQLite connection."""
        if self.conn:
            await self.conn.close()
            logger.info("SQLite connection closed.")

    async def create_tables(self):
        """Create required tables if they do not exist."""
        async with self.lock:
            await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                help_count INTEGER NOT NULL DEFAULT 0,
                block BOOLEAN,
                last_block TIMESTAMP,
                msg_count INTEGER NOT NULL DEFAULT 0,
                last_use TIMESTAMP,
                first_use TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                leave BOOLEAN,
                msg_count INTEGER NOT NULL DEFAULT 0,
                last_use TIMESTAMP,
                first_use TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input TEXT NOT NULL,
                output TEXT NOT NULL,
                user_id TEXT NOT NULL,
                create_time TIMESTAMP NOT NULL,
                preference INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """)
            await self.conn.commit()
        logger.info("Database tables created or verified successfully.")

    # --- User Methods ---

    async def upsert_user(self, user_id: str, help_count_inc: int = 0, block: bool = None, last_block: datetime = None, msg_count_inc: int = 0, last_use: datetime = None, first_use: datetime = None):
        """Inserts a new user or updates an existing one using ON CONFLICT."""
        query = """
            INSERT INTO users (id, help_count, block, last_block, msg_count, last_use, first_use)
            VALUES (?, ?, ?, ?, ?, COALESCE(?, ?), COALESCE(?, ?))
            ON CONFLICT(id) DO UPDATE SET
                help_count = help_count + excluded.help_count,
                msg_count = msg_count + excluded.msg_count,
                last_use = COALESCE(excluded.last_use, last_use),
                block = COALESCE(excluded.block, block),
                last_block = COALESCE(excluded.last_block, last_block);
        """
        params = (
            user_id, help_count_inc, block, last_block, msg_count_inc,
            last_use, first_use, first_use, last_use
        )
        async with self.lock:
            cursor = await self.conn.execute(query, params)
            await self.conn.commit()
        logger.debug(f"Upserted user: {user_id}")

    # --- Group Methods ---

    async def upsert_group(self, group_id: str, leave: bool = None, msg_count_inc: int = 0, last_use: datetime = None, first_use: datetime = None):
        """Inserts a new group or updates an existing one using ON CONFLICT."""
        query = """
            INSERT INTO groups (id, leave, msg_count, last_use, first_use)
            VALUES (?, ?, ?, COALESCE(?, ?), COALESCE(?, ?))
            ON CONFLICT(id) DO UPDATE SET
                leave = COALESCE(excluded.leave, leave),
                msg_count = msg_count + excluded.msg_count,
                last_use = COALESCE(excluded.last_use, last_use);
        """
        params = (
            group_id, leave, msg_count_inc,
            last_use, first_use, first_use, last_use
        )
        async with self.lock:
            await self.conn.execute(query, params)
            await self.conn.commit()
        logger.debug(f"Upserted group: {group_id}")

    # --- Feedback Methods ---

    async def insert_feedback(self, input_text: str, output_text: str, user_id: str, create_time: datetime) -> int:
        """Inserts a new feedback entry and returns its ID."""
        query = "INSERT INTO feedback (input, output, user_id, create_time) VALUES (?, ?, ?, ?)"
        params = (input_text, output_text, user_id, create_time)

        async with self.lock:
            cursor = await self.conn.execute(query, params)
            await self.conn.commit()
            return cursor.lastrowid

    async def update_feedback_preference(self, feedback_id: int, preference: int):
        """Updates the preference for a feedback entry."""
        query = "UPDATE feedback SET preference = ? WHERE id = ?"
        params = (preference, feedback_id)

        async with self.lock:
            await self.conn.execute(query, params)
            await self.conn.commit()
        logger.debug(
            f"Updated feedback {feedback_id} with preference {preference}")
