"""
database.py
============
Async SQLite persistence layer for the bot.

Everything is keyed by (guild_id, user_id) so each server has its own
independent economy/levels/achievements — no more one global balance
shared across every server the bot is in.

NOTE ON HOSTING: SQLite is a huge improvement over the old economy.json
/ levels.json / shop.json files (atomic writes, no corruption on crash,
proper per-guild scoping) — but the *file* still lives on local disk.
On Render's free tier, local disk is wiped on every restart/redeploy,
so this alone does not guarantee your data survives a redeploy. To get
real persistence you need either:
  - a paid Render plan with a persistent disk mounted at DB_PATH, or
  - swapping this out for a hosted Postgres/MySQL (Railway, Supabase,
    Neon all have free tiers).
This module only talks to the DB through the functions below, so
swapping the backend later means editing this one file, not every cog.
"""

import json
import os
import time

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "bot.db")

STARTING_BALANCE = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 100,
    last_daily REAL,
    last_work REAL,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    messages INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    games INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    achievements TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, item_id)
);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id TEXT PRIMARY KEY,
    level_channel_id TEXT,
    music_channel_id TEXT,
    xp_enabled INTEGER NOT NULL DEFAULT 1,
    economy_enabled INTEGER NOT NULL DEFAULT 1,
    level_announce INTEGER NOT NULL DEFAULT 1,
    game_rewards INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    moderator_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

DEFAULT_USER = {
    "balance": STARTING_BALANCE,
    "last_daily": None,
    "last_work": None,
    "daily_streak": 0,
    "messages": 0,
    "wins": 0,
    "games": 0,
    "xp": 0,
    "level": 1,
    "achievements": []
}


class Database:

    def __init__(self, path=DB_PATH):
        self.path = path
        self._conn = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ------------------------------------------------------------
    # USERS
    # ------------------------------------------------------------

    async def get_user(self, guild_id, user_id):
        guild_id, user_id = str(guild_id), str(user_id)

        cur = await self._conn.execute(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()

        if row is None:
            await self._conn.execute(
                "INSERT INTO users (guild_id, user_id, balance) "
                "VALUES (?, ?, ?)",
                (guild_id, user_id, STARTING_BALANCE)
            )
            await self._conn.commit()

            data = dict(DEFAULT_USER)
            data["guild_id"] = guild_id
            data["user_id"] = user_id
            return data

        data = dict(row)
        data["achievements"] = json.loads(data["achievements"] or "[]")
        return data

    async def update_user(self, guild_id, user_id, **fields):
        """update_user(guild_id, user_id, balance=500, xp=10)"""

        guild_id, user_id = str(guild_id), str(user_id)

        # make sure the row exists first
        await self.get_user(guild_id, user_id)

        if "achievements" in fields:
            fields["achievements"] = json.dumps(fields["achievements"])

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [guild_id, user_id]

        await self._conn.execute(
            f"UPDATE users SET {set_clause} "
            f"WHERE guild_id = ? AND user_id = ?",
            values
        )
        await self._conn.commit()

    async def add_balance(self, guild_id, user_id, amount):
        user = await self.get_user(guild_id, user_id)
        new_balance = max(0, user["balance"] + amount)
        await self.update_user(guild_id, user_id, balance=new_balance)
        return new_balance

    async def add_xp(self, guild_id, user_id, amount):
        """Returns (old_level, new_level, new_xp)."""

        user = await self.get_user(guild_id, user_id)

        xp = user["xp"] + amount
        level = user["level"]
        old_level = level

        while xp >= level * 100:
            xp -= level * 100
            level += 1

        await self.update_user(guild_id, user_id, xp=xp, level=level)

        return old_level, level, xp

    async def add_achievement(self, guild_id, user_id, name):
        user = await self.get_user(guild_id, user_id)

        if name in user["achievements"]:
            return False

        user["achievements"].append(name)

        await self.update_user(
            guild_id, user_id, achievements=user["achievements"]
        )

        return True

    async def leaderboard(self, guild_id, order_by="balance", limit=10):
        assert order_by in (
            "balance", "level", "messages", "wins"
        )

        guild_id = str(guild_id)

        if order_by == "level":
            order_sql = "level DESC, xp DESC"
        else:
            order_sql = f"{order_by} DESC"

        cur = await self._conn.execute(
            f"SELECT * FROM users WHERE guild_id = ? "
            f"ORDER BY {order_sql} LIMIT ?",
            (guild_id, limit)
        )
        rows = await cur.fetchall()

        return [dict(r) for r in rows]

    async def rank_position(self, guild_id, user_id, order_by="level"):
        rows = await self.leaderboard(guild_id, order_by=order_by, limit=10_000)

        for i, row in enumerate(rows, start=1):
            if row["user_id"] == str(user_id):
                return i

        return len(rows) + 1

    # ------------------------------------------------------------
    # INVENTORY
    # ------------------------------------------------------------

    async def add_item(self, guild_id, user_id, item_id, amount=1):
        guild_id, user_id = str(guild_id), str(user_id)

        await self._conn.execute(
            "INSERT INTO inventory (guild_id, user_id, item_id, amount) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, item_id) "
            "DO UPDATE SET amount = amount + excluded.amount",
            (guild_id, user_id, item_id, amount)
        )
        await self._conn.commit()

    async def get_inventory(self, guild_id, user_id):
        guild_id, user_id = str(guild_id), str(user_id)

        cur = await self._conn.execute(
            "SELECT item_id, amount FROM inventory "
            "WHERE guild_id = ? AND user_id = ? AND amount > 0",
            (guild_id, user_id)
        )
        rows = await cur.fetchall()

        return {r["item_id"]: r["amount"] for r in rows}

    # ------------------------------------------------------------
    # GUILD CONFIG
    # ------------------------------------------------------------

    async def get_guild_config(self, guild_id):
        guild_id = str(guild_id)

        cur = await self._conn.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?",
            (guild_id,)
        )
        row = await cur.fetchone()

        if row is None:
            await self._conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES (?)",
                (guild_id,)
            )
            await self._conn.commit()

            return {
                "guild_id": guild_id,
                "level_channel_id": None,
                "music_channel_id": None,
                "xp_enabled": 1,
                "economy_enabled": 1,
                "level_announce": 1,
                "game_rewards": 1
            }

        return dict(row)

    async def set_guild_config(self, guild_id, **fields):
        guild_id = str(guild_id)

        await self.get_guild_config(guild_id)

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [guild_id]

        await self._conn.execute(
            f"UPDATE guild_config SET {set_clause} WHERE guild_id = ?",
            values
        )
        await self._conn.commit()

    # ------------------------------------------------------------
    # WARNINGS
    # ------------------------------------------------------------

    async def add_warning(self, guild_id, user_id, moderator_id, reason):
        await self._conn.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, "
            "reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(guild_id), str(user_id), str(moderator_id),
             reason, time.time())
        )
        await self._conn.commit()

    async def get_warnings(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? "
            "ORDER BY created_at DESC",
            (str(guild_id), str(user_id))
        )
        rows = await cur.fetchall()

        return [dict(r) for r in rows]

    async def clear_warnings(self, guild_id, user_id):
        await self._conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id))
        )
        await self._conn.commit()
