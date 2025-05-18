import logging
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create_and_connect(cls, dsn: str, min_size: int = 1, max_size: int = 10, timeout: int = 60):
        """Connect to the PostgreSQL database."""
        try:
            pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
            )
            logger.info("PostgreSQL connection pool created successfully.")
        except Exception as e:
            logger.error(f"Error creating PostgreSQL connection pool: {e}")
            raise  # Re-raise the exception to indicate failure

        return cls(pool)

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL connection pool closed.")

    # --- User Methods ---

    async def upsert_user(self, user_id: str, help_count_inc: int = 0, block: bool = None, last_block: datetime = None, msg_count_inc: int = 0, last_use: datetime = None, first_use: datetime = None):
        """Inserts a new user or updates an existing one."""
        async with self.pool.acquire() as conn:
            # Use a transaction for the upsert logic to ensure atomicity
            async with conn.transaction():
                existing_user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

                if existing_user:
                    update_query = """
                        UPDATE users
                        SET
                            help_count = help_count + $2,
                            msg_count = msg_count + $3,
                            last_use = COALESCE($4, last_use),
                            block = COALESCE($5, block),
                            last_block = COALESCE($6, last_block)
                        WHERE id = $1
                    """
                    await conn.execute(update_query, user_id, help_count_inc, msg_count_inc, last_use, block, last_block)
                    logger.debug(f"Updated user: {user_id}")
                else:
                    insert_query = """
                        INSERT INTO users (id, help_count, block, last_block, msg_count, last_use, first_use)
                        VALUES ($1, $2, $3, $4, $5, COALESCE($6, $7), COALESCE($7, $6))
                    """
                    await conn.execute(insert_query, user_id, help_count_inc, block, last_block, msg_count_inc, last_use, first_use)
                    logger.debug(f"Inserted new user: {user_id}")

    # --- Group Methods ---

    async def upsert_group(self, group_id: str, leave: bool = None, msg_count_inc: int = 0, last_use: datetime = None, first_use: datetime = None):
        """Inserts a new group or updates an existing one."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing_group = await conn.fetchrow("SELECT * FROM groups WHERE id = $1", group_id)

                if existing_group:
                    update_query = """
                        UPDATE groups
                        SET
                            leave = COALESCE($2, leave),
                            msg_count = msg_count + $3,
                            last_use = COALESCE($4, last_use)
                        WHERE id = $1
                    """
                    await conn.execute(update_query, group_id, leave, msg_count_inc, last_use)
                    logger.debug(f"Updated group: {group_id}")
                else:
                    insert_query = """
                        INSERT INTO groups (id, leave, msg_count, last_use, first_use)
                        VALUES ($1, $2, $3, COALESCE($4, $5), COALESCE($5, $4))
                    """
                    await conn.execute(insert_query, group_id, leave, msg_count_inc, last_use, first_use)
                    logger.debug(f"Inserted new group: {group_id}")

    # --- Feedback Methods ---

    async def insert_feedback(self, input_text: str, output_text: str, user_id: str, create_time: datetime) -> int:
        """Inserts a new feedback entry and returns its ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO feedback (input, output, user_id, create_time)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, input_text, output_text, user_id, create_time)
            return row['id']

    async def update_feedback_preference(self, feedback_id: int, preference: int):
        """Updates the preference for a feedback entry."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE feedback SET preference = $1 WHERE id = $2
            """, preference, feedback_id)
            logger.debug(
                f"Updated feedback {feedback_id} with preference {preference}")
