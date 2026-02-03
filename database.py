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
                domain TEXT UNIQUE NOT NULL,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def add_watched_site(domain: str, added_by: str) -> bool:
    """Add a domain to the watched sites list. Returns True if added, False if exists."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO watched_sites (domain, added_by) VALUES (?, ?)",
                (domain, added_by)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_watched_site(domain: str) -> bool:
    """Remove a domain from the watched sites list. Returns True if removed."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM watched_sites WHERE domain = ?",
            (domain,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_watched_sites() -> list[str]:
    """Get all watched site domains."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT domain FROM watched_sites ORDER BY domain")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def is_watched_site(domain: str) -> bool:
    """Check if a domain is in the watched sites list."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM watched_sites WHERE ? LIKE '%' || domain || '%' LIMIT 1",
            (domain,)
        )
        row = await cursor.fetchone()
        return row is not None
