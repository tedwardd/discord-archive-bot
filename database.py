import os
import aiosqlite
from pathlib import Path

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", Path(__file__).parent / "archive_bot.db"))


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS watched_sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, domain)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_watched_sites_guild 
            ON watched_sites(guild_id)
        """)
        await db.commit()


async def add_watched_site(guild_id: str, domain: str, added_by: str) -> bool:
    """Add a domain to the watched sites list for a guild. Returns True if added, False if exists."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO watched_sites (guild_id, domain, added_by) VALUES (?, ?, ?)",
                (guild_id, domain, added_by)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_watched_site(guild_id: str, domain: str) -> bool:
    """Remove a domain from the watched sites list for a guild. Returns True if removed."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM watched_sites WHERE guild_id = ? AND domain = ?",
            (guild_id, domain)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_watched_sites(guild_id: str) -> list[str]:
    """Get all watched site domains for a guild."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT domain FROM watched_sites WHERE guild_id = ? ORDER BY domain",
            (guild_id,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def is_watched_site(guild_id: str, domain: str) -> bool:
    """Check if a domain is in the watched sites list for a guild."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM watched_sites WHERE guild_id = ? AND ? LIKE '%' || domain || '%' LIMIT 1",
            (guild_id, domain)
        )
        row = await cursor.fetchone()
        return row is not None
