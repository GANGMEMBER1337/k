import os

import aiosqlite


def resolve_db_path() -> str:
    """Resolved at connect time so values from .env are already loaded.

    Priority: DB_PATH, then a Railway volume (RAILWAY_VOLUME_MOUNT_PATH is set
    automatically when a volume is attached), then a local data/ folder.
    """
    explicit = os.getenv("DB_PATH")
    if explicit:
        return explicit
    volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if volume:
        return os.path.join(volume, "bot.db")
    return "data/bot.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    mod_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reaction_roles (
    guild_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);
CREATE TABLE IF NOT EXISTS starboard_posts (
    guild_id INTEGER NOT NULL,
    message_id INTEGER PRIMARY KEY,
    star_message_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS lastfm_users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL
);
"""


class Database:
    def __init__(self):
        self.conn = None

    async def connect(self):
        path = resolve_db_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = await aiosqlite.connect(path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def execute(self, sql, params=()):
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    async def fetchone(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def get_setting(self, guild_id, key, default=None):
        row = await self.fetchone(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        return row["value"] if row else default

    async def set_setting(self, guild_id, key, value):
        await self.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, str(value)),
        )

    async def del_setting(self, guild_id, key):
        await self.execute(
            "DELETE FROM guild_settings WHERE guild_id=? AND key=?", (guild_id, key)
        )
