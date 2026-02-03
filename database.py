import os
import aiosqlite
from pathlib import Path

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", Path(__file__).parent / "archive_bot.db"))


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paywall_sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT UNIQUE NOT NULL,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def add_paywall_site(domain: str, added_by: str) -> bool:
    """Add a domain to the paywall sites list. Returns True if added, False if exists."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO paywall_sites (domain, added_by) VALUES (?, ?)",
                (domain, added_by)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_paywall_site(domain: str) -> bool:
    """Remove a domain from the paywall sites list. Returns True if removed."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM paywall_sites WHERE domain = ?",
            (domain,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_paywall_sites() -> list[str]:
    """Get all paywall site domains."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT domain FROM paywall_sites ORDER BY domain")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def is_paywall_site(domain: str) -> bool:
    """Check if a domain is in the paywall sites list."""
    domain = domain.lower().strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM paywall_sites WHERE ? LIKE '%' || domain || '%' LIMIT 1",
            (domain,)
        )
        row = await cursor.fetchone()
        return row is not None
