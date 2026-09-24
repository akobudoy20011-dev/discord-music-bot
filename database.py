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
import random

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
    bank_balance INTEGER NOT NULL DEFAULT 0,
    last_bank_interest REAL,
    equipped_title TEXT,
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
    game_rewards INTEGER NOT NULL DEFAULT 1,
    music_volume REAL NOT NULL DEFAULT 0.5,
    music_loop_mode TEXT NOT NULL DEFAULT 'off',
    music_autoplay INTEGER NOT NULL DEFAULT 0,
    music_24_7 INTEGER NOT NULL DEFAULT 0,
    music_auto_disconnect INTEGER NOT NULL DEFAULT 1,
    music_queue_limit INTEGER NOT NULL DEFAULT 50,
    music_search_behavior TEXT NOT NULL DEFAULT 'youtube',
    music_dj_role_id TEXT,
    music_voice_channel_id TEXT
);

CREATE TABLE IF NOT EXISTS rpg_players (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    class_key TEXT NOT NULL DEFAULT 'knight',
    level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    hp INTEGER NOT NULL DEFAULT 120,
    max_hp INTEGER NOT NULL DEFAULT 120,
    mp INTEGER NOT NULL DEFAULT 40,
    max_mp INTEGER NOT NULL DEFAULT 40,
    strength INTEGER NOT NULL DEFAULT 12,
    defense INTEGER NOT NULL DEFAULT 10,
    magic INTEGER NOT NULL DEFAULT 8,
    agility INTEGER NOT NULL DEFAULT 8,
    gold INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_adventure REAL,
    region TEXT NOT NULL DEFAULT 'moonlit_vale',
    travel_until REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS rpg_items (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    equipped INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, item_id)
);

CREATE TABLE IF NOT EXISTS rpg_quests (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    claimed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, quest_id)
);

CREATE TABLE IF NOT EXISTS rpg_battles (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    enemy_id TEXT NOT NULL,
    enemy_name TEXT NOT NULL,
    enemy_hp INTEGER NOT NULL,
    enemy_max_hp INTEGER NOT NULL,
    enemy_attack INTEGER NOT NULL,
    turn INTEGER NOT NULL DEFAULT 1,
    guarding INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS rpg_worlds (
    guild_id TEXT PRIMARY KEY,
    season TEXT NOT NULL DEFAULT 'eclipse',
    day INTEGER NOT NULL DEFAULT 1,
    weather TEXT NOT NULL DEFAULT 'clear',
    instability INTEGER NOT NULL DEFAULT 0,
    active_event TEXT,
    event_until REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rpg_guardians (
    guild_id TEXT NOT NULL,
    region_id TEXT NOT NULL,
    defeated INTEGER NOT NULL DEFAULT 0,
    defeated_by TEXT,
    defeated_at REAL,
    PRIMARY KEY (guild_id, region_id)
);

CREATE TABLE IF NOT EXISTS rpg_discoveries (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    discovery_id TEXT NOT NULL,
    discovered_at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id, discovery_id)
);

CREATE TABLE IF NOT EXISTS rpg_skills (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    unlocked INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, user_id, skill_id)
);

CREATE TABLE IF NOT EXISTS rpg_materials (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, material_id)
);

CREATE TABLE IF NOT EXISTS eclipse_world_events (
    guild_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    target INTEGER NOT NULL DEFAULT 5000,
    progress INTEGER NOT NULL DEFAULT 0,
    reward_coins INTEGER NOT NULL DEFAULT 1000,
    reward_xp INTEGER NOT NULL DEFAULT 100,
    ends_at REAL NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS eclipse_world_contributors (
    guild_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    contribution INTEGER NOT NULL DEFAULT 0,
    rewarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, event_id, user_id)
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,    moderator_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

DEFAULT_USER = {
    "balance": STARTING_BALANCE,
    "last_daily": None,    "last_work": None,
    "daily_streak": 0,
    "messages": 0,
    "wins": 0,
    "games": 0,
    "xp": 0,
    "level": 1,
    "achievements": [],
    "bank_balance": 0,
    "last_bank_interest": None,
    "equipped_title": None
}


class Database:

    def __init__(self, path=DB_PATH):
        self.path = path
        self._conn = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        cur = await self._conn.execute("PRAGMA table_info(rpg_players)")
        columns = {row["name"] for row in await cur.fetchall()}
        if "region" not in columns:
            await self._conn.execute("ALTER TABLE rpg_players ADD COLUMN region TEXT NOT NULL DEFAULT 'moonlit_vale'")
        if "travel_until" not in columns:
            await self._conn.execute("ALTER TABLE rpg_players ADD COLUMN travel_until REAL NOT NULL DEFAULT 0")

        user_cur = await self._conn.execute("PRAGMA table_info(users)")
        user_columns = {row["name"] for row in await user_cur.fetchall()}
        user_columns_to_add = {
            "bank_balance": "INTEGER NOT NULL DEFAULT 0",
            "last_bank_interest": "REAL",
            "equipped_title": "TEXT",
        }
        for name, definition in user_columns_to_add.items():
            if name not in user_columns:
                await self._conn.execute(
                    f"ALTER TABLE users ADD COLUMN {name} {definition}"
                )

        guild_cur = await self._conn.execute("PRAGMA table_info(guild_config)")
        guild_columns = {row["name"] for row in await guild_cur.fetchall()}
        music_columns = {
            "music_volume": "REAL NOT NULL DEFAULT 0.5",
            "music_loop_mode": "TEXT NOT NULL DEFAULT 'off'",
            "music_autoplay": "INTEGER NOT NULL DEFAULT 0",
            "music_24_7": "INTEGER NOT NULL DEFAULT 0",
            "music_auto_disconnect": "INTEGER NOT NULL DEFAULT 1",
            "music_queue_limit": "INTEGER NOT NULL DEFAULT 50",
            "music_search_behavior": "TEXT NOT NULL DEFAULT 'youtube'",
            "music_dj_role_id": "TEXT",
            "music_voice_channel_id": "TEXT",
        }
        for name, definition in music_columns.items():
            if name not in guild_columns:
                await self._conn.execute(
                    f"ALTER TABLE guild_config ADD COLUMN {name} {definition}"
                )

        world_cur = await self._conn.execute("PRAGMA table_info(rpg_worlds)")
        world_columns = {row["name"] for row in await world_cur.fetchall()}
        if "active_event" not in world_columns:
            await self._conn.execute("ALTER TABLE rpg_worlds ADD COLUMN active_event TEXT")
        if "event_until" not in world_columns:
            await self._conn.execute("ALTER TABLE rpg_worlds ADD COLUMN event_until REAL")

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
    # ECLIPSE PROFILE / BANK / WORLD
    # ------------------------------------------------------------

    async def set_equipped_title(self, guild_id, user_id, title):
        await self.get_user(guild_id, user_id)
        await self._conn.execute(
            "UPDATE users SET equipped_title=? WHERE guild_id=? AND user_id=?",
            (title, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return await self.get_user(guild_id, user_id)

    async def deposit_bank(self, guild_id, user_id, amount):
        amount = int(amount)
        if amount <= 0:
            return False, "amount"
        user = await self.get_user(guild_id, user_id)
        if int(user["balance"]) < amount:
            return False, "balance"
        await self._conn.execute(
            "UPDATE users SET balance=balance-?, bank_balance=bank_balance+? WHERE guild_id=? AND user_id=?",
            (amount, amount, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return True, await self.get_user(guild_id, user_id)

    async def withdraw_bank(self, guild_id, user_id, amount):
        amount = int(amount)
        if amount <= 0:
            return False, "amount"
        user = await self.get_user(guild_id, user_id)
        if int(user["bank_balance"]) < amount:
            return False, "balance"
        await self._conn.execute(
            "UPDATE users SET balance=balance+?, bank_balance=bank_balance-? WHERE guild_id=? AND user_id=?",
            (amount, amount, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return True, await self.get_user(guild_id, user_id)

    async def apply_bank_interest(self, guild_id, user_id, rate=0.01, period=86400):
        user = await self.get_user(guild_id, user_id)
        now = time.time()
        last = user["last_bank_interest"]
        if last is None:
            last = now
        elapsed_periods = int(max(0, now - float(last)) // period)
        if elapsed_periods <= 0:
            return 0, user
        balance = int(user["bank_balance"])
        if balance <= 0:
            await self.update_user(guild_id, user_id, last_bank_interest=now)
            return 0, await self.get_user(guild_id, user_id)
        interest = int(balance * rate * elapsed_periods)
        if interest <= 0:
            await self.update_user(guild_id, user_id, last_bank_interest=now)
            return 0, await self.get_user(guild_id, user_id)
        await self._conn.execute(
            "UPDATE users SET bank_balance=bank_balance+?, last_bank_interest=? WHERE guild_id=? AND user_id=?",
            (interest, now, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return interest, await self.get_user(guild_id, user_id)

    async def get_world_event(self, guild_id):
        cur = await self._conn.execute(
            "SELECT * FROM eclipse_world_events WHERE guild_id=?",
            (str(guild_id),)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def create_world_event(self, guild_id, event_id, title, description, target, reward_coins, reward_xp, ends_at):
        await self._conn.execute(
            "INSERT INTO eclipse_world_events "
            "(guild_id,event_id,title,description,target,progress,reward_coins,reward_xp,ends_at,completed,created_at) "
            "VALUES (?,?,?,?,?,0,?,?,?,0,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET event_id=excluded.event_id,title=excluded.title,"
            "description=excluded.description,target=excluded.target,progress=0,reward_coins=excluded.reward_coins,"
            "reward_xp=excluded.reward_xp,ends_at=excluded.ends_at,completed=0,created_at=excluded.created_at",
            (str(guild_id), event_id, title, description, int(target), int(reward_coins), int(reward_xp), float(ends_at), time.time())
        )
        await self._conn.commit()
        return await self.get_world_event(guild_id)

    async def contribute_world_event(self, guild_id, user_id, amount):
        event = await self.get_world_event(guild_id)
        if not event or event["completed"] or float(event["ends_at"]) <= time.time():
            return False, "inactive"
        amount = int(amount)
        if amount <= 0:
            return False, "amount"
        user = await self.get_user(guild_id, user_id)
        if int(user["balance"]) < amount:
            return False, "balance"
        await self._conn.execute(
            "UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=?",
            (amount, str(guild_id), str(user_id))
        )
        await self._conn.execute(
            "INSERT INTO eclipse_world_contributors(guild_id,event_id,user_id,contribution,rewarded) "
            "VALUES(?,?,?, ?,0) ON CONFLICT(guild_id,event_id,user_id) DO UPDATE SET contribution=contribution+excluded.contribution",
            (str(guild_id), event["event_id"], str(user_id), amount)
        )
        new_progress=min(int(event["target"]), int(event["progress"])+amount)
        completed=1 if new_progress>=int(event["target"]) else 0
        await self._conn.execute(
            "UPDATE eclipse_world_events SET progress=?, completed=? WHERE guild_id=?",
            (new_progress, completed, str(guild_id))
        )
        await self._conn.commit()
        return True, await self.get_world_event(guild_id)

    async def reward_world_event_contributors(self, guild_id):
        event = await self.get_world_event(guild_id)
        if not event or not event["completed"]:
            return 0
        cur = await self._conn.execute(
            "SELECT user_id FROM eclipse_world_contributors WHERE guild_id=? AND event_id=? AND rewarded=0",
            (str(guild_id), event["event_id"])
        )
        rows = await cur.fetchall()
        count=0
        for row in rows:
            await self.add_balance(guild_id, row["user_id"], int(event["reward_coins"]))
            await self.add_xp(guild_id, row["user_id"], int(event["reward_xp"]))
            await self._conn.execute(
                "UPDATE eclipse_world_contributors SET rewarded=1 WHERE guild_id=? AND event_id=? AND user_id=?",
                (str(guild_id), event["event_id"], row["user_id"])
            )
            count+=1
        await self._conn.commit()
        return count

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
                "game_rewards": 1,
                "music_volume": 0.5,
                "music_loop_mode": "off",
                "music_autoplay": 0,
                "music_24_7": 0,
                "music_auto_disconnect": 1,
                "music_queue_limit": 50,
                "music_search_behavior": "youtube",
                "music_dj_role_id": None,
                "music_voice_channel_id": None
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

    async def get_music_config(self, guild_id):
        config = await self.get_guild_config(guild_id)
        return {
            "volume": float(config.get("music_volume", 0.5)),
            "loop_mode": str(config.get("music_loop_mode", "off") or "off"),
            "autoplay": bool(config.get("music_autoplay", 0)),
            "twentyfour_seven": bool(config.get("music_24_7", 0)),
            "auto_disconnect": bool(config.get("music_auto_disconnect", 1)),
            "queue_limit": max(1, min(250, int(config.get("music_queue_limit", 50)))),
            "search_behavior": str(config.get("music_search_behavior", "youtube") or "youtube"),
            "dj_role_id": str(config["music_dj_role_id"]) if config.get("music_dj_role_id") else None,
            "voice_channel_id": str(config["music_voice_channel_id"]) if config.get("music_voice_channel_id") else None,
        }

    async def set_music_config(self, guild_id, **fields):
        mapping = {
            "volume": "music_volume",
            "loop_mode": "music_loop_mode",
            "autoplay": "music_autoplay",
            "twentyfour_seven": "music_24_7",
            "auto_disconnect": "music_auto_disconnect",
            "queue_limit": "music_queue_limit",
            "search_behavior": "music_search_behavior",
            "dj_role_id": "music_dj_role_id",
            "voice_channel_id": "music_voice_channel_id",
        }
        clean = {}
        for key, value in fields.items():
            if key in mapping:
                clean[mapping[key]] = value
        if clean:
            await self.set_guild_config(guild_id, **clean)
        return await self.get_music_config(guild_id)

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
            (str(guild_id), str(user_id))        )
        rows = await cur.fetchall()

        return [dict(r) for r in rows]

    # ------------------------------------------------------------
    # RPG
    # ------------------------------------------------------------

    async def get_rpg_player(self, guild_id, user_id):
        guild_id, user_id = str(guild_id), str(user_id)

        cur = await self._conn.execute(
            "SELECT * FROM rpg_players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()

        if row is None:
            await self._conn.execute(
                "INSERT INTO rpg_players "
                "(guild_id, user_id, created_at) VALUES (?, ?, ?)",
                (guild_id, user_id, time.time())
            )
            await self._conn.commit()

            cur = await self._conn.execute(
                "SELECT * FROM rpg_players WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            row = await cur.fetchone()

        return dict(row)

    async def update_rpg_player(self, guild_id, user_id, **fields):
        guild_id, user_id = str(guild_id), str(user_id)
        await self.get_rpg_player(guild_id, user_id)

        allowed = {
            "class_key", "level", "xp", "hp", "max_hp",
            "mp", "max_mp", "strength", "defense",
            "magic", "agility", "gold", "last_adventure", "region", "travel_until"
        }
        fields = {k: v for k, v in fields.items() if k in allowed}

        if not fields:
            return await self.get_rpg_player(guild_id, user_id)

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [guild_id, user_id]

        await self._conn.execute(
            f"UPDATE rpg_players SET {set_clause} "
            f"WHERE guild_id = ? AND user_id = ?",
            values
        )
        await self._conn.commit()

        return await self.get_rpg_player(guild_id, user_id)

    async def spend_rpg_gold(self, guild_id, user_id, amount):
        player = await self.get_rpg_player(guild_id, user_id)
        amount = int(amount)
        if amount < 0:
            raise ValueError("amount must be non-negative")
        if int(player["gold"]) < amount:
            return False, int(player["gold"])
        player = await self.update_rpg_player(
            guild_id, user_id, gold=int(player["gold"]) - amount        )
        return True, int(player["gold"])

    async def add_rpg_xp(self, guild_id, user_id, amount):
        player = await self.get_rpg_player(guild_id, user_id)
        xp = max(0, int(player["xp"]) + int(amount))
        level = int(player["level"])
        old_level = level

        while xp >= level * 100:
            xp -= level * 100
            level += 1

        if level != old_level:
            hp_gain = (level - old_level) * 12
            mp_gain = (level - old_level) * 4
            player = await self.update_rpg_player(
                guild_id, user_id,
                level=level,
                xp=xp,
                max_hp=int(player["max_hp"]) + hp_gain,
                hp=int(player["max_hp"]) + hp_gain,
                max_mp=int(player["max_mp"]) + mp_gain,
                mp=int(player["max_mp"]) + mp_gain,
            )
        else:
            player = await self.update_rpg_player(
                guild_id, user_id, xp=xp
            )

        return old_level, level, player



    async def get_rpg_world(self, guild_id):
        guild_id = str(guild_id)
        cur = await self._conn.execute(
            "SELECT * FROM rpg_worlds WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row is None:
            await self._conn.execute(
                "INSERT INTO rpg_worlds (guild_id, updated_at) VALUES (?, ?)",
                (guild_id, time.time())
            )
            await self._conn.commit()
            cur = await self._conn.execute(
                "SELECT * FROM rpg_worlds WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
        return dict(row)

    async def update_rpg_world(self, guild_id, **fields):
        allowed = {"season", "day", "weather", "instability", "active_event", "event_until", "updated_at"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return await self.get_rpg_world(guild_id)
        await self.get_rpg_world(guild_id)
        clause = ", ".join(f"{k} = ?" for k in fields)
        await self._conn.execute(
            f"UPDATE rpg_worlds SET {clause} WHERE guild_id = ?",
            list(fields.values()) + [str(guild_id)]
        )
        await self._conn.commit()
        return await self.get_rpg_world(guild_id)

    async def advance_rpg_world(self, guild_id, event_id=None, event_until=None):
        world = await self.get_rpg_world(guild_id)
        weather = random.choice(["clear", "mist", "rain", "moonlight", "ashfall"])
        instability = min(10, max(0, int(world["instability"]) + random.choice([-1, 0, 0, 1])))
        return await self.update_rpg_world(
            guild_id,
            day=int(world["day"]) + 1,
            weather=weather,
            instability=instability,
            active_event=event_id,
            event_until=event_until,
            updated_at=time.time()
        )

    async def get_rpg_guardian(self, guild_id, region_id):
        cur = await self._conn.execute(
            "SELECT * FROM rpg_guardians WHERE guild_id=? AND region_id=?",
            (str(guild_id), str(region_id))
        )
        row = await cur.fetchone()
        if row is None:
            await self._conn.execute(
                "INSERT INTO rpg_guardians (guild_id, region_id) VALUES (?, ?)",
                (str(guild_id), str(region_id))
            )
            await self._conn.commit()
            return {"guild_id":str(guild_id),"region_id":str(region_id),"defeated":0,"defeated_by":None,"defeated_at":None}
        return dict(row)

    async def defeat_rpg_guardian(self, guild_id, region_id, user_id):
        await self.get_rpg_guardian(guild_id, region_id)
        await self._conn.execute(
            "UPDATE rpg_guardians SET defeated=1, defeated_by=?, defeated_at=? WHERE guild_id=? AND region_id=?",
            (str(user_id), time.time(), str(guild_id), str(region_id))
        )
        await self._conn.commit()
        return await self.get_rpg_guardian(guild_id, region_id)

    async def get_rpg_discoveries(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT discovery_id, discovered_at FROM rpg_discoveries WHERE guild_id=? AND user_id=? ORDER BY discovered_at",
            (str(guild_id), str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def has_rpg_discovery(self, guild_id, user_id, discovery_id):
        cur = await self._conn.execute(
            "SELECT 1 FROM rpg_discoveries WHERE guild_id=? AND user_id=? AND discovery_id=?",
            (str(guild_id), str(user_id), str(discovery_id))
        )
        return await cur.fetchone() is not None

    async def add_rpg_discovery(self, guild_id, user_id, discovery_id):
        await self._conn.execute(
            "INSERT OR IGNORE INTO rpg_discoveries (guild_id,user_id,discovery_id,discovered_at) VALUES (?,?,?,?)",
            (str(guild_id),str(user_id),str(discovery_id),time.time())
        )
        await self._conn.commit()
        return True

    async def get_rpg_quests(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT * FROM rpg_quests WHERE guild_id=? AND user_id=? ORDER BY quest_id",
            (str(guild_id), str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_rpg_quest(self, guild_id, user_id, quest_id):
        cur = await self._conn.execute(
            "SELECT * FROM rpg_quests WHERE guild_id=? AND user_id=? AND quest_id=?",
            (str(guild_id), str(user_id), str(quest_id))
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_rpg_quest(self, guild_id, user_id, quest_id, progress=0, completed=0, claimed=0):
        await self._conn.execute(
            "INSERT INTO rpg_quests (guild_id,user_id,quest_id,progress,completed,claimed) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,quest_id) DO UPDATE SET progress=excluded.progress, completed=excluded.completed, claimed=excluded.claimed",
            (str(guild_id),str(user_id),str(quest_id),int(progress),int(completed),int(claimed))
        )
        await self._conn.commit()

    async def get_rpg_battle(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT * FROM rpg_battles WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id))
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_rpg_battle(self, guild_id, user_id, **fields):
        guild_id, user_id = str(guild_id), str(user_id)
        allowed = {"enemy_id","enemy_name","enemy_hp","enemy_max_hp","enemy_attack","turn","guarding","created_at"}
        fields = {k:v for k,v in fields.items() if k in allowed}
        await self._conn.execute(
            "INSERT INTO rpg_battles (guild_id,user_id,enemy_id,enemy_name,enemy_hp,enemy_max_hp,enemy_attack,turn,guarding,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET " +
            ",".join(f"{k}=excluded.{k}" for k in fields),
            (guild_id,user_id,fields.get("enemy_id",""),fields.get("enemy_name",""),int(fields.get("enemy_hp",0)),int(fields.get("enemy_max_hp",0)),int(fields.get("enemy_attack",0)),int(fields.get("turn",1)),int(fields.get("guarding",0)),float(fields.get("created_at",time.time()))
        )
        await self._conn.commit()

    async def delete_rpg_battle(self, guild_id, user_id):
        await self._conn.execute("DELETE FROM rpg_battles WHERE guild_id=? AND user_id=?", (str(guild_id),str(user_id)))
        await self._conn.commit()

    async def get_rpg_items(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT item_id, amount, equipped FROM rpg_items "
            "WHERE guild_id = ? AND user_id = ? AND amount > 0 "
            "ORDER BY item_id",
            (str(guild_id), str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def add_rpg_item(self, guild_id, user_id, item_id, amount=1):
        await self._conn.execute(
            "INSERT INTO rpg_items "
            "(guild_id, user_id, item_id, amount) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, item_id) "
            "DO UPDATE SET amount = amount + excluded.amount",
            (str(guild_id), str(user_id), str(item_id), int(amount))
        )
        await self._conn.commit()