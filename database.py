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
import time
import os
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
    arcade_plays INTEGER NOT NULL DEFAULT 0,
    arcade_wins INTEGER NOT NULL DEFAULT 0,
    arcade_wagered INTEGER NOT NULL DEFAULT 0,
    arcade_net INTEGER NOT NULL DEFAULT 0,
    arcade_best_streak INTEGER NOT NULL DEFAULT 0,
    tournament_wins INTEGER NOT NULL DEFAULT 0,
    tournament_entries INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_progression (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    total_xp INTEGER NOT NULL DEFAULT 0,
    prestige INTEGER NOT NULL DEFAULT 0,
    milestone_claimed INTEGER NOT NULL DEFAULT 0,
    xp_boost REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS economy_progression (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    lifetime_earned INTEGER NOT NULL DEFAULT 0,
    lifetime_spent INTEGER NOT NULL DEFAULT 0,
    tier INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS economy_effects (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    effect_id TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    uses INTEGER NOT NULL DEFAULT 0,
    expires_at REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id, effect_id)
);

CREATE TABLE IF NOT EXISTS economy_trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    buyer_id TEXT,
    item_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    price INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS economy_auctions (
    auction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    highest_bid INTEGER NOT NULL DEFAULT 0,
    highest_bidder_id TEXT,
    created_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS economy_collectibles (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    collectible_id TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, collectible_id)
);

CREATE TABLE IF NOT EXISTS economy_investments (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    investment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    principal INTEGER NOT NULL,
    multiplier REAL NOT NULL,
    created_at REAL NOT NULL,
    matures_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS game_stats (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    game_id TEXT NOT NULL,
    plays INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    ties INTEGER NOT NULL DEFAULT 0,
    wagered INTEGER NOT NULL DEFAULT 0,
    net_coins INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, game_id)
);

CREATE TABLE IF NOT EXISTS arcade_tournaments (
    guild_id TEXT NOT NULL,
    tournament_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    entry_fee INTEGER NOT NULL DEFAULT 0,
    prize_pool INTEGER NOT NULL DEFAULT 0,
    max_players INTEGER NOT NULL DEFAULT 16,
    winner_id TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    prize_awarded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arcade_tournament_players (
    tournament_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    seed INTEGER NOT NULL,
    eliminated INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tournament_id, user_id)
);

CREATE TABLE IF NOT EXISTS arcade_tournament_matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    round INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    player_a TEXT,
    player_b TEXT,
    winner_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS arcade_seasons (
    guild_id TEXT NOT NULL,
    season_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    starts_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    created_by TEXT,
    winner_id TEXT,
    winner_points INTEGER NOT NULL DEFAULT 0,
    reward_coins INTEGER NOT NULL DEFAULT 0,
    reward_xp INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arcade_season_stats (
    season_id INTEGER NOT NULL,
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    plays INTEGER NOT NULL DEFAULT 0,
    net_coins INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (season_id, user_id)
);

CREATE TABLE IF NOT EXISTS arcade_daily (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    day_key TEXT NOT NULL,
    challenge_id TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    claimed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, day_key)
);

CREATE TABLE IF NOT EXISTS inventory (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, item_id)
);

CREATE TABLE IF NOT EXISTS music_premium (
    guild_id TEXT PRIMARY KEY,
    plan TEXT NOT NULL DEFAULT 'premium',
    expires_at REAL NOT NULL,
    granted_at REAL NOT NULL,
    granted_by TEXT,
    updated_at REAL NOT NULL
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

CREATE TABLE IF NOT EXISTS rpg_specials (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    special_id TEXT NOT NULL,
    unlocked INTEGER NOT NULL DEFAULT 1,
    unlocked_at REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'level',
    PRIMARY KEY (guild_id, user_id, special_id)
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

CREATE TABLE IF NOT EXISTS guilds (
    guild_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    treasury INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_members (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at REAL NOT NULL,
    contribution INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_invites (
    invite_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    inviter_id TEXT NOT NULL,
    invitee_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS guild_events (
    guild_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    target INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    reward_coins INTEGER NOT NULL DEFAULT 0,
    reward_xp INTEGER NOT NULL DEFAULT 0,
    ends_at REAL NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY (guild_id, event_id)
);

CREATE TABLE IF NOT EXISTS guild_event_contributors (
    guild_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    contribution INTEGER NOT NULL DEFAULT 0,
    rewarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, event_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_bosses (
    guild_id TEXT PRIMARY KEY,
    boss_id TEXT NOT NULL,
    name TEXT NOT NULL,
    max_hp INTEGER NOT NULL,
    hp INTEGER NOT NULL,
    attack INTEGER NOT NULL DEFAULT 50,
    reward_coins INTEGER NOT NULL DEFAULT 10000,
    reward_xp INTEGER NOT NULL DEFAULT 1000,
    ends_at REAL NOT NULL,
    defeated INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_boss_contributors (
    guild_id TEXT NOT NULL,
    boss_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    damage INTEGER NOT NULL DEFAULT 0,
    rewarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, boss_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_wars (
    war_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    opponent_guild_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    guild_score INTEGER NOT NULL DEFAULT 0,
    opponent_score INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    winner_guild_id TEXT
);

CREATE TABLE IF NOT EXISTS guild_raids (
    raid_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    raid_id_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    boss_hp INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    reward_coins INTEGER NOT NULL DEFAULT 25000,
    reward_xp INTEGER NOT NULL DEFAULT 2500,
    ends_at REAL NOT NULL,
    created_at REAL NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS guild_raid_contributors (
    raid_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    damage INTEGER NOT NULL DEFAULT 0,
    rewarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (raid_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_legendary_equipment (
    guild_id TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    rarity TEXT NOT NULL DEFAULT 'legendary',
    acquired_at REAL NOT NULL,
    PRIMARY KEY (guild_id, equipment_id)
);

CREATE TABLE IF NOT EXISTS guild_server_events (
    guild_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    ends_at REAL NOT NULL,
    created_at REAL NOT NULL
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
    "achievements": [],
    "bank_balance": 0,
    "last_bank_interest": None,
    "equipped_title": None,
    "arcade_plays": 0,
    "arcade_wins": 0,
    "arcade_wagered": 0,
    "arcade_net": 0,
    "arcade_best_streak": 0,
    "tournament_wins": 0,
    "tournament_entries": 0
}


class Database:

    def __init__(self, path=DB_PATH):
        self.path = path
        self._conn = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        cur = await self._conn.execute("PRAGMA table_info(rpg_players)")
        columns = {row["name"] for row in await cur.fetchall()}
        if "region" not in columns:
            await self._conn.execute("ALTER TABLE rpg_players ADD COLUMN region TEXT NOT NULL DEFAULT 'moonlit_vale'")
        if "travel_until" not in columns:
            await self._conn.execute("ALTER TABLE rpg_players ADD COLUMN travel_until REAL NOT NULL DEFAULT 0")

        battle_cur = await self._conn.execute("PRAGMA table_info(rpg_battles)")
        battle_columns = {row["name"] for row in await battle_cur.fetchall()}
        if "effects" not in battle_columns:
            await self._conn.execute("ALTER TABLE rpg_battles ADD COLUMN effects TEXT NOT NULL DEFAULT '{}'")
        if "special_cooldowns" not in battle_columns:
            await self._conn.execute("ALTER TABLE rpg_battles ADD COLUMN special_cooldowns TEXT NOT NULL DEFAULT '{}'")

        tournament_cur = await self._conn.execute("PRAGMA table_info(arcade_tournaments)")
        tournament_columns = {row["name"] for row in await tournament_cur.fetchall()}
        if "prize_awarded" not in tournament_columns:
            await self._conn.execute("ALTER TABLE arcade_tournaments ADD COLUMN prize_awarded INTEGER NOT NULL DEFAULT 0")

        user_cur = await self._conn.execute("PRAGMA table_info(users)")
        user_columns = {row["name"] for row in await user_cur.fetchall()}
        for name, definition in {
            "bank_balance": "INTEGER NOT NULL DEFAULT 0",
            "last_bank_interest": "REAL",
            "equipped_title": "TEXT",
            "arcade_plays": "INTEGER NOT NULL DEFAULT 0",
            "arcade_wins": "INTEGER NOT NULL DEFAULT 0",
            "arcade_wagered": "INTEGER NOT NULL DEFAULT 0",
            "arcade_net": "INTEGER NOT NULL DEFAULT 0",
            "arcade_best_streak": "INTEGER NOT NULL DEFAULT 0",
            "tournament_wins": "INTEGER NOT NULL DEFAULT 0",
            "tournament_entries": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in user_columns:
                await self._conn.execute(
                    f"ALTER TABLE users ADD COLUMN {name} {definition}"
                )

        guild_cur = await self._conn.execute("PRAGMA table_info(guild_config)")
        guild_columns = {row["name"] for row in await guild_cur.fetchall()}
        for name, definition in {
            "music_volume": "REAL NOT NULL DEFAULT 0.5",
            "music_loop_mode": "TEXT NOT NULL DEFAULT 'off'",
            "music_autoplay": "INTEGER NOT NULL DEFAULT 0",
            "music_24_7": "INTEGER NOT NULL DEFAULT 0",
            "music_auto_disconnect": "INTEGER NOT NULL DEFAULT 1",
            "music_queue_limit": "INTEGER NOT NULL DEFAULT 50",
            "music_search_behavior": "TEXT NOT NULL DEFAULT 'youtube'",
            "music_dj_role_id": "TEXT",
            "music_voice_channel_id": "TEXT",
        }.items():
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

        guilds_cur = await self._conn.execute("PRAGMA table_info(guilds)")
        guild_columns_existing = {row["name"] for row in await guilds_cur.fetchall()}
        if "server_id" not in guild_columns_existing:
            await self._conn.execute("ALTER TABLE guilds ADD COLUMN server_id TEXT NOT NULL DEFAULT ''")

        auction_cur = await self._conn.execute("PRAGMA table_info(economy_auctions)")
        auction_columns = {row["name"] for row in await auction_cur.fetchall()}
        if "asset_type" not in auction_columns:
            await self._conn.execute("ALTER TABLE economy_auctions ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'item'")
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
                "INSERT OR IGNORE INTO users (guild_id, user_id, balance) "
                "VALUES (?, ?, ?)",
                (guild_id, user_id, STARTING_BALANCE)
            )
            await self._conn.commit()
            cur = await self._conn.execute(
                "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            row = await cur.fetchone()

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

    async def record_economy_activity(self, guild_id, user_id, earned=0, spent=0):
        guild_id, user_id = str(guild_id), str(user_id)
        earned = max(0, int(earned))
        spent = max(0, int(spent))
        await self.get_user(guild_id, user_id)
        await self._conn.execute(
            "INSERT OR IGNORE INTO economy_progression (guild_id,user_id) VALUES (?,?)",
            (guild_id, user_id)
        )
        await self._conn.execute(
            "UPDATE economy_progression SET lifetime_earned=lifetime_earned+?, lifetime_spent=lifetime_spent+? WHERE guild_id=? AND user_id=?",
            (earned, spent, guild_id, user_id)
        )
        await self._conn.commit()
        return await self.get_economy_progression(guild_id, user_id)

    async def get_economy_progression(self, guild_id, user_id):
        guild_id, user_id = str(guild_id), str(user_id)
        await self.get_user(guild_id, user_id)
        await self._conn.execute(
            "INSERT OR IGNORE INTO economy_progression (guild_id,user_id) VALUES (?,?)",
            (guild_id, user_id)
        )
        cur = await self._conn.execute(
            "SELECT * FROM economy_progression WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()
        data = dict(row)
        earned = int(data["lifetime_earned"])
        spent = int(data["lifetime_spent"])
        tier = 1 + min(9, earned // 10000 + spent // 25000)
        if tier != int(data["tier"]):
            await self._conn.execute(
                "UPDATE economy_progression SET tier=? WHERE guild_id=? AND user_id=?",
                (tier, guild_id, user_id)
            )
            await self._conn.commit()
            data["tier"] = tier
        return data

    async def health_check(self):
        """Return a lightweight database health snapshot."""
        started = time.perf_counter()
        await self._conn.execute("SELECT 1")
        await self._conn.commit()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {"ok": True, "latency_ms": round(elapsed_ms, 2)}

    async def claim_daily(self, guild_id, user_id, now, daily_amount, streak_bonus, streak_cap, cooldown, grace):
        """Atomically claim the daily reward and advance its streak."""
        guild_id, user_id = str(guild_id), str(user_id)
        now = float(now)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._conn.execute("INSERT OR IGNORE INTO users (guild_id,user_id,balance) VALUES (?,?,?)", (guild_id,user_id,STARTING_BALANCE))
            cur = await self._conn.execute("SELECT balance,last_daily,daily_streak FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            row = await cur.fetchone()
            last = row["last_daily"]
            if last is not None and now - float(last) < float(cooldown):
                await self._conn.rollback()
                return {"ok":False,"reason":"cooldown","remaining":float(cooldown)-(now-float(last))}
            streak = min(int(row["daily_streak"] or 0)+1,9999) if last is not None and now-float(last)<=float(grace) else 1
            reward = int(daily_amount) + min(streak,int(streak_cap))*int(streak_bonus)
            await self._conn.execute("UPDATE users SET balance=balance+?,last_daily=?,daily_streak=? WHERE guild_id=? AND user_id=?", (reward,now,streak,guild_id,user_id))
            cur = await self._conn.execute("SELECT balance FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            balance = int((await cur.fetchone())["balance"])
            await self._conn.commit()
            return {"ok":True,"reward":reward,"streak":streak,"balance":balance}
        except Exception:
            await self._conn.rollback()
            raise

    async def claim_work(self, guild_id, user_id, now, minimum, maximum, cooldown):
        """Atomically claim a work reward and advance its cooldown."""
        guild_id, user_id = str(guild_id), str(user_id)
        now = float(now)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._conn.execute("INSERT OR IGNORE INTO users (guild_id,user_id,balance) VALUES (?,?,?)", (guild_id,user_id,STARTING_BALANCE))
            cur = await self._conn.execute("SELECT balance,last_work FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            row = await cur.fetchone()
            last = row["last_work"]
            if last is not None and now-float(last)<float(cooldown):
                await self._conn.rollback()
                return {"ok":False,"reason":"cooldown","remaining":float(cooldown)-(now-float(last))}
            earned=random.randint(int(minimum),int(maximum))
            await self._conn.execute("UPDATE users SET balance=balance+?,last_work=? WHERE guild_id=? AND user_id=?", (earned,now,guild_id,user_id))
            cur=await self._conn.execute("SELECT balance FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            balance=int((await cur.fetchone())["balance"])
            await self._conn.commit()
            return {"ok":True,"earned":earned,"balance":balance}
        except Exception:
            await self._conn.rollback()
            raise

    async def transfer_balance(self, guild_id, sender_id, recipient_id, amount):
        """Atomically transfer coins without allowing an overdraft."""
        guild_id=str(guild_id); sender_id=str(sender_id); recipient_id=str(recipient_id); amount=int(amount)
        if amount<=0: return False,"invalid",None
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            for uid in (sender_id,recipient_id):
                await self._conn.execute("INSERT OR IGNORE INTO users (guild_id,user_id,balance) VALUES (?,?,?)", (guild_id,uid,STARTING_BALANCE))
            cur=await self._conn.execute("UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?", (amount,guild_id,sender_id,amount))
            if cur.rowcount != 1:
                cur=await self._conn.execute("SELECT balance FROM users WHERE guild_id=? AND user_id=?", (guild_id,sender_id))
                balance=int((await cur.fetchone())["balance"])
                await self._conn.rollback()
                return False,"balance",balance
            await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?", (amount,guild_id,recipient_id))
            await self._conn.commit()
            return True,"ok",None
        except Exception:
            await self._conn.rollback(); raise

    async def purchase_item(self, guild_id, user_id, item_id, price, amount=1):
        """Atomically charge a user and add an inventory item."""
        guild_id=str(guild_id); user_id=str(user_id); item_id=str(item_id); price=int(price); amount=int(amount)
        if price<0 or amount<=0: return False,"invalid",None
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._conn.execute("INSERT OR IGNORE INTO users (guild_id,user_id,balance) VALUES (?,?,?)", (guild_id,user_id,STARTING_BALANCE))
            cur=await self._conn.execute("UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?", (price,guild_id,user_id,price))
            if cur.rowcount != 1:
                cur=await self._conn.execute("SELECT balance FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
                balance=int((await cur.fetchone())["balance"]); await self._conn.rollback()
                return False,"balance",balance
            await self._conn.execute("INSERT INTO inventory (guild_id,user_id,item_id,amount) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount", (guild_id,user_id,item_id,amount))
            cur=await self._conn.execute("SELECT balance FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            balance=int((await cur.fetchone())["balance"])
            await self._conn.commit(); return True,"ok",balance
        except Exception:
            await self._conn.rollback(); raise

    async def bank_deposit(self, guild_id, user_id, amount):
        guild_id, user_id = str(guild_id), str(user_id)
        amount = int(amount)
        if amount <= 0:
            return False, "amount", 0
        await self.get_user(guild_id, user_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "UPDATE users SET balance=balance-?, bank_balance=bank_balance+? "
                "WHERE guild_id=? AND user_id=? AND balance>=?",
                (amount, amount, guild_id, user_id, amount)
            )
            if cur.rowcount != 1:
                await self._conn.rollback()
                user = await self.get_user(guild_id, user_id)
                return False, "balance", int(user["balance"])
            await self._conn.commit()
            return True, "ok", amount
        except Exception:
            await self._conn.rollback()
            raise

    async def bank_withdraw(self, guild_id, user_id, amount):
        guild_id, user_id = str(guild_id), str(user_id)
        amount = int(amount)
        if amount <= 0:
            return False, "amount", 0
        await self.get_user(guild_id, user_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "UPDATE users SET bank_balance=bank_balance-?, balance=balance+? "
                "WHERE guild_id=? AND user_id=? AND bank_balance>=?",
                (amount, amount, guild_id, user_id, amount)
            )
            if cur.rowcount != 1:
                await self._conn.rollback()
                user = await self.get_user(guild_id, user_id)
                return False, "bank", int(user["bank_balance"])
            await self._conn.commit()
            return True, "ok", amount
        except Exception:
            await self._conn.rollback()
            raise

    async def apply_bank_interest(self, guild_id, user_id, now=None, rate=0.01):
        guild_id, user_id = str(guild_id), str(user_id)
        now = float(now or time.time())
        await self.get_user(guild_id, user_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "SELECT bank_balance,last_bank_interest FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )
            row = await cur.fetchone()
            bank = int(row["bank_balance"])
            last = row["last_bank_interest"]
            if bank <= 0:
                await self._conn.execute(
                    "UPDATE users SET last_bank_interest=? WHERE guild_id=? AND user_id=?",
                    (now, guild_id, user_id)
                )
                await self._conn.commit()
                return 0, bank
            if last is not None and now - float(last) < 24 * 3600:
                await self._conn.rollback()
                return 0, bank
            interest = max(1, int(bank * max(0.0, float(rate))))
            await self._conn.execute(
                "UPDATE users SET bank_balance=bank_balance+?,last_bank_interest=? WHERE guild_id=? AND user_id=?",
                (interest, now, guild_id, user_id)
            )
            await self._conn.commit()
            return interest, bank + interest
        except Exception:
            await self._conn.rollback()
            raise

    async def withdraw_balance(self, guild_id, user_id, amount):
        """Atomically withdraw coins; never allows an overdraft."""
        guild_id, user_id = str(guild_id), str(user_id)
        amount = int(amount)
        if amount <= 0:
            return False, "amount", 0
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._conn.execute(
                "INSERT OR IGNORE INTO users (guild_id,user_id,balance) VALUES (?,?,?)",
                (guild_id, user_id, STARTING_BALANCE),
            )
            cur = await self._conn.execute(
                "UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",
                (amount, guild_id, user_id, amount),
            )
            if cur.rowcount != 1:
                cur = await self._conn.execute(
                    "SELECT balance FROM users WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                row = await cur.fetchone()
                await self._conn.rollback()
                return False, "balance", int(row["balance"])
            cur = await self._conn.execute(
                "SELECT balance FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            balance = int((await cur.fetchone())["balance"])
            await self._conn.commit()
            return True, "ok", balance
        except Exception:
            await self._conn.rollback()
            raise

    async def settle_expired_marketplace(self, guild_id):
        """Return escrowed marketplace items from every expired open listing."""
        guild_id = str(guild_id)
        now = time.time()
        await self._conn.execute("BEGIN IMMEDIATE")
        returned = 0
        try:
            cur = await self._conn.execute(
                "SELECT * FROM economy_trades WHERE guild_id=? AND status='open' AND expires_at<=?",
                (guild_id, now),
            )
            rows = await cur.fetchall()
            for row in rows:
                await self._conn.execute(
                    "INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) "
                    "ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",
                    (guild_id, row["seller_id"], row["item_id"], int(row["amount"])),
                )
                await self._conn.execute(
                    "UPDATE economy_trades SET status='expired' WHERE trade_id=?",
                    (int(row["trade_id"]),),
                )
                returned += 1
            await self._conn.commit()
            return returned
        except Exception:
            await self._conn.rollback()
            raise

    async def create_trade(self, guild_id, seller_id, item_id, amount, price, expires_in=3600):
        guild_id, seller_id, item_id = str(guild_id), str(seller_id), str(item_id)
        amount, price = int(amount), int(price)
        if amount <= 0 or price <= 0:
            return None, "invalid"
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "UPDATE inventory SET amount=amount-? WHERE guild_id=? AND user_id=? AND item_id=? AND amount>=?",
                (amount, guild_id, seller_id, item_id, amount),
            )
            if cur.rowcount != 1:
                await self._conn.rollback()
                return None, "item"
            await self._conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_id=? AND amount<=0",
                (guild_id, seller_id, item_id),
            )
            now = time.time()
            cur = await self._conn.execute(
                "INSERT INTO economy_trades(guild_id,seller_id,item_id,amount,price,status,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                (guild_id,seller_id,item_id,amount,price,"open",now,now+max(60,int(expires_in))),
            )
            await self._conn.commit()
            return int(cur.lastrowid), "ok"
        except Exception:
            await self._conn.rollback()
            raise

    async def get_open_trades(self, guild_id, limit=10):
        await self.settle_expired_marketplace(guild_id)
        cur = await self._conn.execute(
            "SELECT * FROM economy_trades WHERE guild_id=? AND status='open' ORDER BY trade_id DESC LIMIT ?",
            (str(guild_id), int(limit)),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def cancel_trade(self, guild_id, seller_id, trade_id):
        guild_id, seller_id = str(guild_id), str(seller_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "SELECT * FROM economy_trades WHERE trade_id=? AND guild_id=? AND seller_id=? AND status='open'",
                (int(trade_id), guild_id, seller_id),
            )
            row = await cur.fetchone()
            if not row:
                await self._conn.rollback()
                return None
            if float(row["expires_at"]) <= time.time():
                await self._conn.execute("UPDATE economy_trades SET status='expired' WHERE trade_id=?", (int(trade_id),))
                await self._conn.execute(
                    "INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) "
                    "ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",
                    (guild_id,seller_id,row["item_id"],int(row["amount"])),
                )
                await self._conn.commit()
                return None
            await self._conn.execute("UPDATE economy_trades SET status='cancelled' WHERE trade_id=?", (int(trade_id),))
            await self._conn.execute(
                "INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",
                (guild_id,seller_id,row["item_id"],int(row["amount"])),
            )
            await self._conn.commit()
            return dict(row)
        except Exception:
            await self._conn.rollback()
            raise

    async def buy_trade(self, guild_id, buyer_id, trade_id):
        guild_id,buyer_id=str(guild_id),str(buyer_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("SELECT * FROM economy_trades WHERE trade_id=? AND guild_id=? AND status='open'",(int(trade_id),guild_id))
            row=await cur.fetchone()
            if not row:
                await self._conn.rollback()
                return None,"missing"
            if float(row["expires_at"])<=time.time():
                await self._conn.execute("UPDATE economy_trades SET status='expired' WHERE trade_id=?",(int(trade_id),))
                await self._conn.execute(
                    "INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) "
                    "ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",
                    (guild_id,row["seller_id"],row["item_id"],int(row["amount"])),
                )
                await self._conn.commit()
                return None,"missing"
            if row["seller_id"]==buyer_id:
                await self._conn.rollback(); return None,"self"
            await self._conn.execute("INSERT OR IGNORE INTO users(guild_id,user_id,balance) VALUES(?,?,?)",(guild_id,buyer_id,STARTING_BALANCE))
            cur=await self._conn.execute("UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",(int(row["price"]),guild_id,buyer_id,int(row["price"])))
            if cur.rowcount!=1:
                await self._conn.rollback(); return None,"balance"
            await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",(int(row["price"]),guild_id,row["seller_id"]))
            await self._conn.execute("INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",(guild_id,buyer_id,row["item_id"],int(row["amount"])))
            await self._conn.execute("UPDATE economy_trades SET buyer_id=?,status='sold' WHERE trade_id=?",(buyer_id,int(trade_id)))
            await self._conn.commit()
            return dict(row),"ok"
        except Exception:
            await self._conn.rollback(); raise

    async def create_auction(self, guild_id, seller_id, item_id, amount, starting_bid, minutes, asset_type="item"):
        guild_id, seller_id, item_id = str(guild_id), str(seller_id), str(item_id)
        amount, starting_bid, minutes = int(amount), int(starting_bid), int(minutes)
        if amount <= 0 or starting_bid <= 0:
            return None, "invalid"
        minutes = min(7 * 24 * 60, max(1, minutes))
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "UPDATE inventory SET amount=amount-? WHERE guild_id=? AND user_id=? AND item_id=? AND amount>=?",
                (amount,guild_id,seller_id,item_id,amount),
            )
            if cur.rowcount != 1:
                await self._conn.rollback()
                return None, "item"
            await self._conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_id=? AND amount<=0",
                (guild_id,seller_id,item_id),
            )
            now=time.time()
            cur=await self._conn.execute(
                "INSERT INTO economy_auctions(guild_id,seller_id,item_id,amount,highest_bid,highest_bidder_id,created_at,ends_at,status,asset_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (guild_id,seller_id,item_id,amount,starting_bid,None,now,now+minutes*60,"open",asset_type),
            )
            await self._conn.commit()
            return int(cur.lastrowid), "ok"
        except Exception:
            await self._conn.rollback()
            raise

    async def list_auctions(self, guild_id, limit=15):
        await self.settle_expired_auctions(guild_id)
        cur=await self._conn.execute(
            "SELECT * FROM economy_auctions WHERE guild_id=? AND status='open' ORDER BY auction_id DESC LIMIT ?",
            (str(guild_id),int(limit)),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def cancel_auction(self, guild_id, seller_id, auction_id):
        guild_id,seller_id=str(guild_id),str(seller_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute(
                "SELECT * FROM economy_auctions WHERE auction_id=? AND guild_id=? AND seller_id=? AND status='open'",
                (int(auction_id),guild_id,seller_id),
            )
            row=await cur.fetchone()
            if not row:
                await self._conn.rollback(); return None,"missing"
            if row["highest_bidder_id"]:
                await self._conn.rollback(); return None,"bid"
            await self._conn.execute(
                "INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",
                (guild_id,seller_id,row["item_id"],int(row["amount"])),
            )
            await self._conn.execute("UPDATE economy_auctions SET status='cancelled' WHERE auction_id=?",(int(auction_id),))
            await self._conn.commit()
            return dict(row),"ok"
        except Exception:
            await self._conn.rollback(); raise

    async def place_bid(self, guild_id, bidder_id, auction_id, amount):
        guild_id,bidder_id=str(guild_id),str(bidder_id)
        amount=int(amount)
        if amount<=0: return None,"invalid"
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute(
                "SELECT * FROM economy_auctions WHERE auction_id=? AND guild_id=? AND status='open'",
                (int(auction_id),guild_id),
            )
            row=await cur.fetchone()
            if not row: await self._conn.rollback(); return None,"missing"
            now=time.time()
            if float(row["ends_at"])<=now: await self._conn.rollback(); return None,"ended"
            if row["seller_id"]==bidder_id: await self._conn.rollback(); return None,"self"
            current=int(row["highest_bid"]); previous=row["highest_bidder_id"]
            delta=amount-current if previous==bidder_id else amount
            if previous==bidder_id and delta<=0: await self._conn.rollback(); return None,"raise"
            if previous!=bidder_id and amount<current: await self._conn.rollback(); return None,"low"
            await self._conn.execute("INSERT OR IGNORE INTO users(guild_id,user_id,balance) VALUES(?,?,?)",(guild_id,bidder_id,STARTING_BALANCE))
            cur=await self._conn.execute("UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",(delta,guild_id,bidder_id,delta))
            if cur.rowcount!=1: await self._conn.rollback(); return None,"balance"
            if previous and previous!=bidder_id:
                await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",(current,guild_id,previous))
            await self._conn.execute("UPDATE economy_auctions SET highest_bid=?,highest_bidder_id=? WHERE auction_id=?",(amount,bidder_id,int(auction_id)))
            await self._conn.commit()
            return {"auction":dict(row),"delta":delta,"previous":previous,"amount":amount},"ok"
        except Exception:
            await self._conn.rollback(); raise

    async def settle_auction(self, guild_id, auction_id, force=False):
        guild_id=str(guild_id)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("SELECT * FROM economy_auctions WHERE auction_id=? AND guild_id=? AND status='open'",(int(auction_id),guild_id))
            row=await cur.fetchone()
            if not row: await self._conn.rollback(); return None,"missing"
            if not force and float(row["ends_at"])>time.time(): await self._conn.rollback(); return None,"active"
            winner=row["highest_bidder_id"]
            if winner:
                await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",(int(row["highest_bid"]),guild_id,row["seller_id"]))
                await self._conn.execute("INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",(guild_id,winner,row["item_id"],int(row["amount"])))
            else:
                await self._conn.execute("INSERT INTO inventory(guild_id,user_id,item_id,amount) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+excluded.amount",(guild_id,row["seller_id"],row["item_id"],int(row["amount"])))
            await self._conn.execute("UPDATE economy_auctions SET status='ended' WHERE auction_id=?",(int(auction_id),))
            await self._conn.commit()
            return dict(row),"ok"
        except Exception:
            await self._conn.rollback(); raise

    async def settle_expired_auctions(self, guild_id):
        guild_id=str(guild_id)
        cur=await self._conn.execute(
            "SELECT auction_id FROM economy_auctions WHERE guild_id=? AND status='open' AND ends_at<=?",
            (guild_id,time.time()),
        )
        ids=[int(r["auction_id"]) for r in await cur.fetchall()]
        settled=[]
        for auction_id in ids:
            row,reason=await self.settle_auction(guild_id,auction_id)
            if row is not None and reason=="ok":
                settled.append(row)
        return settled

    async def get_collectibles(self, guild_id, user_id):
        cur=await self._conn.execute("SELECT collectible_id,amount FROM economy_collectibles WHERE guild_id=? AND user_id=? AND amount>0 ORDER BY amount DESC,collectible_id",(str(guild_id),str(user_id)))
        return [dict(r) for r in await cur.fetchall()]

    async def create_investment(self, guild_id, user_id, principal, multiplier, duration):
        guild_id, user_id = str(guild_id), str(user_id)
        principal = int(principal)
        multiplier = float(multiplier)
        duration = int(duration)
        if principal <= 0 or multiplier <= 1.0 or duration <= 0:
            return None, "invalid"
        await self.get_user(guild_id, user_id)
        now = time.time()
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",
                (principal, guild_id, user_id, principal)
            )
            if cur.rowcount != 1:
                await self._conn.rollback()
                return None, "balance"
            cur = await self._conn.execute(
                "INSERT INTO economy_investments "
                "(guild_id,user_id,principal,multiplier,created_at,matures_at,status) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id,user_id,principal,multiplier,now,now+duration,"active")
            )
            investment_id = cur.lastrowid
            await self._conn.commit()
            return int(investment_id), "ok"
        except Exception:
            await self._conn.rollback()
            raise

    async def get_investments(self, guild_id, user_id, active_only=False):
        query = "SELECT * FROM economy_investments WHERE guild_id=? AND user_id=?"
        params = [str(guild_id), str(user_id)]
        if active_only:
            query += " AND status='active'"
        query += " ORDER BY investment_id DESC"
        cur = await self._conn.execute(query, params)
        return [dict(row) for row in await cur.fetchall()]

    async def redeem_investment(self, guild_id, user_id, investment_id):
        guild_id, user_id = str(guild_id), str(user_id)
        investment_id = int(investment_id)
        now = time.time()
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "SELECT * FROM economy_investments WHERE investment_id=? AND guild_id=? AND user_id=? AND status='active'",
                (investment_id,guild_id,user_id)
            )
            row = await cur.fetchone()
            if row is None:
                await self._conn.rollback()
                return None, "missing"
            if now < float(row["matures_at"]):
                await self._conn.rollback()
                return None, float(row["matures_at"]) - now
            payout = int(int(row["principal"]) * float(row["multiplier"]))
            await self._conn.execute(
                "UPDATE economy_investments SET status='redeemed' WHERE investment_id=?",
                (investment_id,)
            )
            await self._conn.execute(
                "UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                (payout,guild_id,user_id)
            )
            await self._conn.commit()
            return payout, "ok"
        except Exception:
            await self._conn.rollback()
            raise

    async def add_balance(self, guild_id, user_id, amount):
        guild_id, user_id = str(guild_id), str(user_id)
        await self.get_user(guild_id, user_id)
        amount = int(amount)
        await self._conn.execute(
            "UPDATE users SET balance = MAX(0, balance + ?) "
            "WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )
        await self._conn.commit()
        cur = await self._conn.execute(
            "SELECT balance FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return int(row["balance"])

    async def add_xp(self, guild_id, user_id, amount):
        """Returns (old_level, new_level, new_xp)."""

        user = await self.get_user(guild_id, user_id)
        guild_id, user_id = str(guild_id), str(user_id)
        amount = max(0, int(amount))
        await self._conn.execute(
            "INSERT OR IGNORE INTO level_progression (guild_id,user_id,total_xp,prestige) VALUES (?,?,0,0)",
            (guild_id, user_id)
        )
        cur = await self._conn.execute(
            "SELECT xp_boost FROM level_progression WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        boost = float((await cur.fetchone())["xp_boost"])
        boosted_amount = int(amount * max(1.0, boost))
        await self._conn.execute(
            "UPDATE level_progression SET total_xp=total_xp+? WHERE guild_id=? AND user_id=?",
            (boosted_amount, guild_id, user_id)
        )

        xp = user["xp"] + boosted_amount
        level = user["level"]
        old_level = level

        while xp >= level * 100:
            xp -= level * 100
            level += 1

        await self.update_user(guild_id, user_id, xp=xp, level=level)

        return old_level, level, xp

    async def get_level_progression(self, guild_id, user_id):
        await self.get_user(guild_id, user_id)
        await self._conn.execute(
            "INSERT OR IGNORE INTO level_progression (guild_id,user_id) VALUES (?,?)",
            (str(guild_id), str(user_id))
        )
        await self._conn.commit()
        cur = await self._conn.execute(
            "SELECT * FROM level_progression WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id))
        )
        return dict(await cur.fetchone())

    async def prestige_user(self, guild_id, user_id):
        state = await self.get_level_progression(guild_id, user_id)
        user = await self.get_user(guild_id, user_id)
        if int(user["level"]) < 100:
            return None
        prestige = int(state["prestige"]) + 1
        await self.update_user(guild_id, user_id, level=1, xp=0)
        await self._conn.execute(
            "UPDATE level_progression SET prestige=?, milestone_claimed=0, xp_boost=? WHERE guild_id=? AND user_id=?",
            (prestige, 1.0 + min(prestige, 10) * 0.05, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return prestige

    async def grant_level_milestone(self, guild_id, user_id, level):
        if int(level) < 10 or int(level) % 10:
            return False
        state = await self.get_level_progression(guild_id, user_id)
        claimed = int(state["milestone_claimed"])
        if int(level) <= claimed:
            return False
        reward = int(level) * 100
        await self.add_balance(guild_id, user_id, reward)
        await self._conn.execute(
            "UPDATE level_progression SET milestone_claimed=? WHERE guild_id=? AND user_id=?",
            (int(level), str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return reward

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
    # ------------------------------------------------------------
    # ARCADE PERSISTENCE
    # ------------------------------------------------------------

    async def record_game(self, guild_id, user_id, game_id, result, wager=0, net=0):
        guild_id, user_id, game_id = str(guild_id), str(user_id), str(game_id)
        await self.get_user(guild_id, user_id)
        win = 1 if result == "win" else 0
        loss = 1 if result == "loss" else 0
        tie = 1 if result == "tie" else 0
        wager = max(0, int(wager))
        net = int(net)
        cur = await self._conn.execute(
            "SELECT current_streak, best_streak FROM game_stats "
            "WHERE guild_id=? AND user_id=? AND game_id=?",
            (guild_id, user_id, game_id)
        )
        row = await cur.fetchone()
        streak = int(row["current_streak"]) if row else 0
        best = int(row["best_streak"]) if row else 0
        streak = streak + 1 if win else 0
        best = max(best, streak)
        await self._conn.execute(
            "UPDATE users SET games=games+1, wins=wins+?, arcade_plays=arcade_plays+1, "
            "arcade_wins=arcade_wins+?, arcade_wagered=arcade_wagered+?, arcade_net=arcade_net+?, "
            "arcade_best_streak=MAX(arcade_best_streak, ?) WHERE guild_id=? AND user_id=?",
            (win, win, wager, net, best, guild_id, user_id)
        )
        await self._conn.execute(
            "INSERT INTO game_stats "
            "(guild_id,user_id,game_id,plays,wins,losses,ties,wagered,net_coins,best_streak,current_streak) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,game_id) DO UPDATE SET "
            "plays=plays+1,wins=wins+?,losses=losses+?,ties=ties+?,wagered=wagered+?,"
            "net_coins=net_coins+?,best_streak=?,current_streak=?",
            (guild_id,user_id,game_id,1,win,loss,tie,wager,net,best,streak,
             win,loss,tie,wager,net,best,streak)
        )
        await self._conn.commit()

    async def get_game_stats(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT * FROM game_stats WHERE guild_id=? AND user_id=? ORDER BY plays DESC",
            (str(guild_id), str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def game_leaderboard(self, guild_id, game_id, limit=10):
        cur = await self._conn.execute(
            "SELECT user_id,plays,wins,losses,ties,wagered,net_coins,best_streak "
            "FROM game_stats WHERE guild_id=? AND game_id=? "
            "ORDER BY wins DESC,best_streak DESC,net_coins DESC LIMIT ?",
            (str(guild_id), str(game_id), int(limit))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_arcade_season(self, guild_id, season_id=None):
        if season_id is None:
            cur = await self._conn.execute(
                "SELECT * FROM arcade_seasons WHERE guild_id=? AND status='active' ORDER BY season_id DESC LIMIT 1",
                (str(guild_id),)
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM arcade_seasons WHERE guild_id=? AND season_id=?",
                (str(guild_id), int(season_id))
            )
        row = await cur.fetchone()
        if not row:
            return None
        season = dict(row)
        if season["status"] == "active" and float(season["ends_at"]) <= time.time():
            cur = await self._conn.execute(
                "SELECT user_id,points FROM arcade_season_stats WHERE season_id=? AND guild_id=? "
                "ORDER BY points DESC,wins DESC,net_coins DESC LIMIT 1",
                (int(season["season_id"]), str(guild_id))
            )
            winner = await cur.fetchone()
            await self._conn.execute(
                "UPDATE arcade_seasons SET status='ended',winner_id=?,winner_points=? "
                "WHERE season_id=? AND guild_id=? AND status='active'",
                (winner["user_id"] if winner else None,
                 int(winner["points"]) if winner else 0,
                 int(season["season_id"]), str(guild_id))
            )
            await self._conn.commit()
            if winner:
                if int(season["reward_coins"]):
                    await self.add_balance(guild_id, winner["user_id"], int(season["reward_coins"]))
                if int(season["reward_xp"]):
                    await self.add_xp(guild_id, winner["user_id"], int(season["reward_xp"]))
            return None
        return season

    async def create_arcade_season(self, guild_id, name, duration_days=30, created_by=None, reward_coins=5000, reward_xp=2500):
        duration_days = max(1, min(365, int(duration_days)))
        now = time.time()
        active = await self.get_arcade_season(guild_id)
        if active:
            return None, "active"
        cur = await self._conn.execute(
            """INSERT INTO arcade_seasons
               (guild_id,name,status,starts_at,ends_at,created_by,reward_coins,reward_xp)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(guild_id), str(name)[:80], "active", now, now + duration_days * 86400,
             str(created_by) if created_by else None, int(reward_coins), int(reward_xp))
        )
        await self._conn.commit()
        return await self.get_arcade_season(guild_id, cur.lastrowid), "created"

    async def get_arcade_season_leaderboard(self, guild_id, season_id=None, limit=10):
        season = await self.get_arcade_season(guild_id, season_id)
        if not season:
            return []
        cur = await self._conn.execute(
            """SELECT user_id,points,wins,plays,net_coins
               FROM arcade_season_stats
               WHERE season_id=? AND guild_id=?
               ORDER BY points DESC,wins DESC,net_coins DESC
               LIMIT ?""",
            (int(season["season_id"]), str(guild_id), int(limit))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_arcade_season_stats(self, guild_id, user_id, season_id=None):
        season = await self.get_arcade_season(guild_id, season_id)
        if not season:
            return None
        cur = await self._conn.execute(
            "SELECT * FROM arcade_season_stats WHERE season_id=? AND guild_id=? AND user_id=?",
            (int(season["season_id"]), str(guild_id), str(user_id))
        )
        row = await cur.fetchone()
        return dict(row) if row else {
            "season_id": season["season_id"], "guild_id": str(guild_id),
            "user_id": str(user_id), "points": 0, "wins": 0, "plays": 0, "net_coins": 0
        }

    async def advance_arcade_season(self, guild_id, user_id, result, net_coins=0):
        season = await self.get_arcade_season(guild_id)
        if not season:
            return None
        points = {"win": 100, "tie": 40, "loss": 20}.get(result, 0)
        await self._conn.execute(
            """INSERT INTO arcade_season_stats
               (season_id,guild_id,user_id,points,wins,plays,net_coins)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(season_id,user_id) DO UPDATE SET
                 points=points+excluded.points,
                 wins=wins+excluded.wins,
                 plays=plays+excluded.plays,
                 net_coins=net_coins+excluded.net_coins""",
            (int(season["season_id"]), str(guild_id), str(user_id), points,
             1 if result == "win" else 0, 1, int(net_coins))
        )
        await self._conn.commit()
        return points

    async def finish_arcade_season(self, guild_id, season_id=None):
        season = await self.get_arcade_season(guild_id, season_id)
        if not season:
            return None
        rows = await self.get_arcade_season_leaderboard(guild_id, season["season_id"], 1)
        winner = rows[0] if rows else None
        await self._conn.execute(
            """UPDATE arcade_seasons SET status='ended',winner_id=?,winner_points=?
               WHERE season_id=? AND guild_id=? AND status='active'""",
            (winner["user_id"] if winner else None,
             int(winner["points"]) if winner else 0,
             int(season["season_id"]), str(guild_id))
        )
        await self._conn.commit()
        if winner:
            if int(season["reward_coins"]):
                await self.add_balance(guild_id, winner["user_id"], int(season["reward_coins"]))
            if int(season["reward_xp"]):
                await self.add_xp(guild_id, winner["user_id"], int(season["reward_xp"]))
        return winner

    async def get_arcade_daily(self, guild_id, user_id, day_key):
        challenges = (
            ("play3", "Play 3 PvP arcade games.", 3),
            ("win2", "Win 2 PvP arcade games.", 2),
            ("play5", "Play 5 PvP arcade games.", 5),
            ("win1", "Win 1 PvP arcade game.", 1),
        )
        index = sum(ord(c) for c in str(day_key)) % len(challenges)
        challenge_id, description, target = challenges[index]
        await self._conn.execute(
            "INSERT OR IGNORE INTO arcade_daily "
            "(guild_id,user_id,day_key,challenge_id) VALUES (?,?,?,?)",
            (str(guild_id), str(user_id), str(day_key), challenge_id)
        )
        cur = await self._conn.execute(
            "SELECT * FROM arcade_daily WHERE guild_id=? AND user_id=? AND day_key=?",
            (str(guild_id), str(user_id), str(day_key))
        )
        row = await cur.fetchone()
        data = dict(row)
        data["description"] = description
        data["target"] = target
        return data

    async def advance_arcade_daily(self, guild_id, user_id, day_key, result):
        data = await self.get_arcade_daily(guild_id, user_id, day_key)
        amount = 1 if (
            data["challenge_id"] in ("play3","play5")
            or data["challenge_id"] == "win2" and result == "win"
            or data["challenge_id"] == "win1" and result == "win"
        ) else 0
        if amount:
            await self._conn.execute(
                "UPDATE arcade_daily SET progress=MIN(progress+?,?) "
                "WHERE guild_id=? AND user_id=? AND day_key=? AND claimed=0",
                (amount,int(data["target"]),str(guild_id),str(user_id),str(day_key))
            )
            await self._conn.commit()

    async def claim_arcade_daily(self, guild_id, user_id, day_key):
        data = await self.get_arcade_daily(guild_id, user_id, day_key)
        if data["claimed"]:
            return False, "claimed", data
        if int(data["progress"]) < int(data["target"]):
            return False, "incomplete", data
        await self._conn.execute(
            "UPDATE arcade_daily SET claimed=1 "
            "WHERE guild_id=? AND user_id=? AND day_key=? AND claimed=0",
            (str(guild_id),str(user_id),str(day_key))
        )
        await self._conn.commit()
        await self.add_balance(guild_id, user_id, 500)
        await self.add_xp(guild_id, user_id, 150)
        return True, "claimed", data

    async def create_arcade_tournament(self, guild_id, game_id, name, entry_fee=0, max_players=16):
        cur = await self._conn.execute(
            "INSERT INTO arcade_tournaments(guild_id,game_id,name,entry_fee,max_players,created_at) VALUES(?,?,?,?,?,?)",
            (str(guild_id), str(game_id), str(name), int(entry_fee), int(max_players), time.time())
        )
        await self._conn.commit()
        return await self.get_arcade_tournament(guild_id, cur.lastrowid)

    async def get_arcade_tournament(self, guild_id, tournament_id=None):
        if tournament_id is None:
            cur = await self._conn.execute("SELECT * FROM arcade_tournaments WHERE guild_id=? AND status IN ('open','active') ORDER BY tournament_id DESC LIMIT 1", (str(guild_id),))
        else:
            cur = await self._conn.execute("SELECT * FROM arcade_tournaments WHERE guild_id=? AND tournament_id=?", (str(guild_id), int(tournament_id)))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def join_arcade_tournament(self, guild_id, tournament_id, user_id):
        tournament = await self.get_arcade_tournament(guild_id, tournament_id)
        if not tournament or tournament["status"] != "open": return False, "closed"
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM arcade_tournament_players WHERE tournament_id=?", (int(tournament_id),))
        count = (await cur.fetchone())["n"]
        if count >= int(tournament["max_players"]): return False, "full"
        cur = await self._conn.execute("SELECT 1 FROM arcade_tournament_players WHERE tournament_id=? AND user_id=?", (int(tournament_id), str(user_id)))
        if await cur.fetchone(): return False, "joined"
        fee=int(tournament["entry_fee"]); user=await self.get_user(guild_id,user_id)
        if int(user["balance"]) < fee: return False, "balance"
        if fee: await self.add_balance(guild_id,user_id,-fee)
        await self._conn.execute("UPDATE users SET tournament_entries=tournament_entries+1 WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
        await self._conn.execute("INSERT INTO arcade_tournament_players(tournament_id,user_id,seed) VALUES(?,?,?)",(int(tournament_id),str(user_id),count+1))
        await self._conn.execute("UPDATE arcade_tournaments SET prize_pool=prize_pool+? WHERE tournament_id=?",(fee,int(tournament_id)))
        await self._conn.commit(); return True, "joined"

    async def get_arcade_tournament_players(self, tournament_id):
        cur=await self._conn.execute("SELECT * FROM arcade_tournament_players WHERE tournament_id=? ORDER BY seed",(int(tournament_id),)); return [dict(r) for r in await cur.fetchall()]

    async def start_arcade_tournament(self, guild_id, tournament_id):
        t = await self.get_arcade_tournament(guild_id, tournament_id)
        players = await self.get_arcade_tournament_players(tournament_id) if t else []
        if not t or t["status"] != "open":
            return False, "closed", []
        if len(players) < 2:
            return False, "players", []
        size = 1
        while size < len(players):
            size *= 2
        while len(players) < size:
            players.append({"user_id": None, "seed": len(players) + 1})
        await self._conn.execute("UPDATE arcade_tournaments SET status='active',started_at=? WHERE tournament_id=?", (time.time(), int(tournament_id)))
        for i in range(0, size, 2):
            a = players[i]["user_id"]
            b = players[i + 1]["user_id"]
            status = "ready" if a and b else "bye"
            await self._conn.execute("INSERT INTO arcade_tournament_matches(tournament_id,round,slot,player_a,player_b,status,created_at) VALUES(?,?,?,?,?,?,?)", (int(tournament_id), 1, i // 2, a, b, status, time.time()))
        await self._conn.commit()
        await self._advance_tournament(int(tournament_id))
        return True, "started", players[:size]

    async def get_arcade_matches(self, tournament_id, round_no=None):
        q = "SELECT * FROM arcade_tournament_matches WHERE tournament_id=?"
        args = [int(tournament_id)]
        if round_no is not None:
            q += " AND round=?"
            args.append(int(round_no))
        q += " ORDER BY round,slot"
        cur = await self._conn.execute(q, args)
        return [dict(r) for r in await cur.fetchall()]

    async def _advance_tournament(self, tournament_id):
        tcur = await self._conn.execute("SELECT * FROM arcade_tournaments WHERE tournament_id=?", (int(tournament_id),))
        trow = await tcur.fetchone()
        if not trow or trow["status"] != "active":
            return None
        while True:
            cur = await self._conn.execute("SELECT * FROM arcade_tournament_matches WHERE tournament_id=? ORDER BY round,slot", (int(tournament_id),))
            matches = [dict(r) for r in await cur.fetchall()]
            if not matches:
                return None
            current_round = max(int(m["round"]) for m in matches)
            current = [m for m in matches if int(m["round"]) == current_round]
            changed = False
            for m in current:
                if m["status"] == "bye" and m["player_a"]:
                    await self._conn.execute("UPDATE arcade_tournament_matches SET winner_id=?,status='complete' WHERE match_id=?", (str(m["player_a"]), int(m["match_id"])))
                    changed = True
            if changed:
                await self._conn.commit()
                cur = await self._conn.execute("SELECT * FROM arcade_tournament_matches WHERE tournament_id=? AND round=? ORDER BY slot", (int(tournament_id), current_round))
                current = [dict(r) for r in await cur.fetchall()]
            if any(m["status"] != "complete" for m in current):
                return None
            winners = [m["winner_id"] for m in current if m["winner_id"]]
            if len(winners) == 1:
                champion = str(winners[0])
                payout = int(trow["prize_pool"])
                await self._conn.execute("UPDATE arcade_tournaments SET status='finished',winner_id=?,finished_at=?,prize_awarded=? WHERE tournament_id=? AND status='active'", (champion, time.time(), payout, int(tournament_id)))
                await self._conn.execute("UPDATE users SET tournament_wins=tournament_wins+1 WHERE guild_id=? AND user_id=?", (str(trow["guild_id"]), champion))
                if payout:
                    await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?", (payout, str(trow["guild_id"]), champion))
                await self._conn.commit()
                return {"finished": True, "winner_id": champion, "payout": payout}
            next_round = current_round + 1
            exists = await self._conn.execute("SELECT 1 FROM arcade_tournament_matches WHERE tournament_id=? AND round=? LIMIT 1", (int(tournament_id), next_round))
            if await exists.fetchone():
                return None
            for i in range(0, len(winners), 2):
                a = winners[i]
                b = winners[i + 1] if i + 1 < len(winners) else None
                status = "ready" if a and b else "bye"
                await self._conn.execute("INSERT INTO arcade_tournament_matches(tournament_id,round,slot,player_a,player_b,status,created_at) VALUES(?,?,?,?,?,?,?)", (int(tournament_id), next_round, i // 2, a, b, status, time.time()))
            await self._conn.commit()

    async def tournament_history(self, guild_id, limit=10):
        cur = await self._conn.execute("SELECT * FROM arcade_tournaments WHERE guild_id=? AND status='finished' ORDER BY finished_at DESC LIMIT ?", (str(guild_id), int(limit)))
        return [dict(r) for r in await cur.fetchall()]

    async def get_tournament_stats(self, guild_id, user_id):
        cur = await self._conn.execute("SELECT COUNT(*) AS entries, COALESCE(SUM(wins),0) AS match_wins FROM arcade_tournament_players WHERE tournament_id IN (SELECT tournament_id FROM arcade_tournaments WHERE guild_id=?) AND user_id=?", (str(guild_id), str(user_id)))
        row = await cur.fetchone()
        cur = await self._conn.execute("SELECT COUNT(*) AS championships, COALESCE(SUM(prize_awarded),0) AS prize_money FROM arcade_tournaments WHERE guild_id=? AND status='finished' AND winner_id=?", (str(guild_id), str(user_id)))
        champs = await cur.fetchone()
        return {"entries": int(row["entries"]), "match_wins": int(row["match_wins"]), "championships": int(champs["championships"]), "prize_money": int(champs["prize_money"])}

    async def cancel_arcade_tournament(self, guild_id, tournament_id):
        t = await self.get_arcade_tournament(guild_id, tournament_id)
        if not t or t["status"] != "open":
            return False, "closed", 0
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM arcade_tournament_players WHERE tournament_id=?", (int(tournament_id),))
        count = int((await cur.fetchone())["n"])
        fee = int(t["entry_fee"])
        refund = count * fee
        if refund:
            cur = await self._conn.execute("SELECT user_id FROM arcade_tournament_players WHERE tournament_id=?", (int(tournament_id),))
            for row in await cur.fetchall():
                await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?", (fee, str(guild_id), str(row["user_id"])))
        await self._conn.execute("UPDATE arcade_tournaments SET status='cancelled',finished_at=? WHERE tournament_id=?", (time.time(), int(tournament_id)))
        await self._conn.commit()
        return True, "cancelled", refund

    # ECLIPSE PROFILE / BANK / MUSIC / WORLD
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
        periods = int(max(0, now - float(last)) // period)
        if periods <= 0:
            return 0, user
        balance = int(user["bank_balance"])
        if balance <= 0:
            await self.update_user(guild_id, user_id, last_bank_interest=now)
            return 0, await self.get_user(guild_id, user_id)
        interest = int(balance * rate * periods)
        await self._conn.execute(
            "UPDATE users SET bank_balance=bank_balance+?, last_bank_interest=? WHERE guild_id=? AND user_id=?",
            (interest, now, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return interest, await self.get_user(guild_id, user_id)

    async def get_music_premium(self, guild_id):
        cur = await self._conn.execute(
            "SELECT * FROM music_premium WHERE guild_id=?",
            (str(guild_id),),
        )
        row = await cur.fetchone()
        if not row:
            return None
        premium = dict(row)
        if float(premium["expires_at"]) <= time.time():
            await self._conn.execute(
                "DELETE FROM music_premium WHERE guild_id=?",
                (str(guild_id),),
            )
            await self._conn.commit()
            return None
        return premium

    async def grant_music_premium(self, guild_id, days, granted_by=None, plan="premium"):
        days = max(1, int(days))
        now = time.time()
        current = await self.get_music_premium(guild_id)
        base = max(now, float(current["expires_at"])) if current else now
        expires_at = base + days * 86400
        await self._conn.execute(
            """INSERT INTO music_premium
               (guild_id, plan, expires_at, granted_at, granted_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 plan=excluded.plan,
                 expires_at=excluded.expires_at,
                 granted_by=excluded.granted_by,
                 updated_at=excluded.updated_at""",
            (str(guild_id), plan, expires_at, now, str(granted_by) if granted_by else None, now),
        )
        await self._conn.commit()
        return await self.get_music_premium(guild_id)

    async def revoke_music_premium(self, guild_id):
        await self._conn.execute(
            "DELETE FROM music_premium WHERE guild_id=?",
            (str(guild_id),),
        )
        await self._conn.commit()
        return True

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
        clean = {mapping[k]: v for k, v in fields.items() if k in mapping}
        if clean:
            await self.set_guild_config(guild_id, **clean)
        return await self.get_music_config(guild_id)

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

    async def consume_item(self, guild_id, user_id, item_id, amount=1):
        """Atomically consume inventory items. Returns remaining quantity or None."""
        guild_id, user_id = str(guild_id), str(user_id)
        item_id, amount = str(item_id), int(amount)
        if amount <= 0:
            return None
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "UPDATE inventory SET amount=amount-? "
                "WHERE guild_id=? AND user_id=? AND item_id=? AND amount>=?",
                (amount, guild_id, user_id, item_id, amount)
            )
            if cur.rowcount != 1:
                await self._conn.rollback()
                return None
            await self._conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_id=? AND amount<=0",
                (guild_id, user_id, item_id)
            )
            cur = await self._conn.execute(
                "SELECT COALESCE(amount,0) AS amount FROM inventory "
                "WHERE guild_id=? AND user_id=? AND item_id=?",
                (guild_id, user_id, item_id)
            )
            row = await cur.fetchone()
            remaining = int(row["amount"]) if row else 0
            await self._conn.commit()
            return remaining
        except Exception:
            await self._conn.rollback()
            raise

    async def add_economy_effect(self, guild_id, user_id, effect_id,
                                 multiplier=1.0, uses=0, expires_at=None):
        """Persist a temporary or next-use economy effect."""
        guild_id, user_id = str(guild_id), str(user_id)
        effect_id = str(effect_id)
        multiplier = max(1.0, float(multiplier))
        uses = max(0, int(uses))
        now = time.time()

        await self._conn.execute(
            "INSERT INTO economy_effects "
            "(guild_id,user_id,effect_id,multiplier,uses,expires_at,created_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,effect_id) DO UPDATE SET "
            "multiplier=MAX(economy_effects.multiplier, excluded.multiplier), "
            "uses=CASE WHEN excluded.uses > 0 "
            "THEN economy_effects.uses + excluded.uses ELSE economy_effects.uses END, "
            "expires_at=CASE "
            "WHEN excluded.expires_at IS NULL THEN economy_effects.expires_at "
            "WHEN economy_effects.expires_at IS NULL THEN excluded.expires_at "
            "ELSE MAX(economy_effects.expires_at, excluded.expires_at) END",
            (guild_id, user_id, effect_id, multiplier, uses, expires_at, now)
        )
        await self._conn.commit()

    async def get_economy_effects(self, guild_id, user_id):
        """Return active economy effects and remove expired ones."""
        guild_id, user_id = str(guild_id), str(user_id)
        now = time.time()
        await self._conn.execute(
            "DELETE FROM economy_effects "
            "WHERE guild_id=? AND user_id=? AND expires_at IS NOT NULL AND expires_at<=?",
            (guild_id, user_id, now)
        )
        await self._conn.commit()
        cur = await self._conn.execute(
            "SELECT * FROM economy_effects "
            "WHERE guild_id=? AND user_id=? ORDER BY effect_id",
            (guild_id, user_id)
        )
        return [dict(row) for row in await cur.fetchall()]

    async def consume_economy_effect(self, guild_id, user_id, effect_id):
        """Consume one next-use charge; timed effects are left untouched."""
        guild_id, user_id = str(guild_id), str(user_id)
        effect_id = str(effect_id)
        now = time.time()
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._conn.execute(
                "SELECT uses, expires_at FROM economy_effects "
                "WHERE guild_id=? AND user_id=? AND effect_id=?",
                (guild_id, user_id, effect_id)
            )
            row = await cur.fetchone()
            if row is None or (
                row["expires_at"] is not None and float(row["expires_at"]) <= now
            ):
                await self._conn.rollback()
                return False
            if int(row["uses"]) <= 0:
                await self._conn.rollback()
                return True
            await self._conn.execute(
                "UPDATE economy_effects SET uses=uses-1 "
                "WHERE guild_id=? AND user_id=? AND effect_id=? AND uses>0",
                (guild_id, user_id, effect_id)
            )
            await self._conn.execute(
                "DELETE FROM economy_effects WHERE guild_id=? AND user_id=? "
                "AND effect_id=? AND uses<=0 AND expires_at IS NULL",
                (guild_id, user_id, effect_id)
            )
            await self._conn.commit()
            return True
        except Exception:
            await self._conn.rollback()
            raise

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
            guild_id, user_id, gold=int(player["gold"]) - amount
        )
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



    # ------------------------------------------------------------
    # GUILDS / WORLD SYSTEM
    # ------------------------------------------------------------

    async def create_guild(self, server_id, guild_id, name, owner_id):
        server_id, guild_id, name, owner_id = map(str, (server_id, guild_id, name, owner_id))
        now=time.time()
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("SELECT 1 FROM guilds WHERE server_id=? AND lower(name)=lower(?)",(server_id,name))
            if await cur.fetchone():
                await self._conn.rollback(); return None,"name"
            cur=await self._conn.execute(
                "INSERT INTO guilds(guild_id,server_id,name,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (guild_id,server_id,name,owner_id,now,now),
            )
            await self._conn.execute(
                "INSERT INTO guild_members(guild_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                (guild_id,owner_id,"leader",now),
            )
            await self._conn.commit()
            return guild_id,"ok"
        except Exception:
            await self._conn.rollback(); raise

    async def get_guild(self, guild_id):
        cur=await self._conn.execute("SELECT * FROM guilds WHERE guild_id=?",(str(guild_id),))
        row=await cur.fetchone()
        return dict(row) if row else None

    async def get_user_guild(self, server_id, user_id):
        cur=await self._conn.execute(
            "SELECT g.* , gm.role, gm.contribution FROM guilds g JOIN guild_members gm ON gm.guild_id=g.guild_id "
            "WHERE g.server_id=? AND gm.user_id=? ORDER BY g.created_at LIMIT 1",
            (str(server_id),str(user_id)),
        )
        row=await cur.fetchone()
        return dict(row) if row else None

    async def get_server_guilds(self, server_id, limit=25):
        cur=await self._conn.execute("SELECT * FROM guilds WHERE server_id=? ORDER BY level DESC,created_at LIMIT ?",(str(server_id),int(limit)))
        return [dict(r) for r in await cur.fetchall()]

    async def get_guild_members(self, guild_id, limit=50):
        cur=await self._conn.execute("SELECT * FROM guild_members WHERE guild_id=? ORDER BY contribution DESC,joined_at LIMIT ?",(str(guild_id),int(limit)))
        return [dict(r) for r in await cur.fetchall()]

    async def join_guild(self, guild_id, user_id):
        guild_id,user_id=str(guild_id),str(user_id)
        guild=await self.get_guild(guild_id)
        if not guild: return False,"missing"
        current=await self.get_user_guild(guild["server_id"],user_id)
        if current: return False,"member"
        await self._conn.execute("INSERT OR IGNORE INTO guild_members(guild_id,user_id,role,joined_at) VALUES(?,?,?,?)",(guild_id,user_id,"member",time.time()))
        await self._conn.commit()
        return True,"ok"

    async def leave_guild(self, guild_id, user_id):
        guild_id,user_id=str(guild_id),str(user_id)
        guild=await self.get_guild(guild_id)
        if not guild: return False,"missing"
        if str(guild["owner_id"])==user_id: return False,"owner"
        await self._conn.execute("DELETE FROM guild_members WHERE guild_id=? AND user_id=?",(guild_id,user_id))
        await self._conn.commit()
        return True,"ok"

    async def set_guild_role(self, guild_id, user_id, role):
        role=str(role)
        if role not in {"leader","officer","member"}: return False
        await self._conn.execute("UPDATE guild_members SET role=? WHERE guild_id=? AND user_id=?",(role,str(guild_id),str(user_id)))
        await self._conn.commit()
        return True

    async def guild_treasury_deposit(self, guild_id, user_id, amount):
        guild_id,user_id=str(guild_id),str(user_id); amount=int(amount)
        if amount<=0: return False,"amount",0
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("SELECT 1 FROM guild_members WHERE guild_id=? AND user_id=?",(guild_id,user_id))
            if not await cur.fetchone(): await self._conn.rollback(); return False,"member",0
            g=await self.get_guild(guild_id)
            if not g:
                await self._conn.rollback(); return False,"missing",0
            cur=await self._conn.execute("UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",(amount,str(g["server_id"]),user_id,amount))
            if cur.rowcount!=1: await self._conn.rollback(); return False,"balance",0
            await self._conn.execute("UPDATE guilds SET treasury=treasury+?,xp=xp+?,updated_at=? WHERE guild_id=?",(amount,amount//10,time.time(),guild_id))
            await self._conn.execute("UPDATE guild_members SET contribution=contribution+? WHERE guild_id=? AND user_id=?",(amount,guild_id,user_id))
            await self._conn.commit()
            await self.recalculate_guild_level(guild_id)
            return True,"ok",amount
        except Exception:
            await self._conn.rollback(); raise

    async def guild_treasury_withdraw(self, guild_id, user_id, amount):
        guild_id,user_id=str(guild_id),str(user_id); amount=int(amount)
        if amount<=0: return False,"amount",0
        g=await self.get_guild(guild_id)
        if not g: return False,"missing",0
        member=await self._conn.execute("SELECT role FROM guild_members WHERE guild_id=? AND user_id=?",(guild_id,user_id))
        row=await member.fetchone()
        if not row or row["role"] not in {"leader","officer"}: return False,"permission",0
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("UPDATE guilds SET treasury=treasury-? WHERE guild_id=? AND treasury>=?",(amount,guild_id,amount))
            if cur.rowcount!=1: await self._conn.rollback(); return False,"treasury",0
            await self._conn.execute("INSERT OR IGNORE INTO users(guild_id,user_id,balance) VALUES(?,?,?)",(str(g["server_id"]),user_id,STARTING_BALANCE))
            await self._conn.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",(amount,str(g["server_id"]),user_id))
            await self._conn.commit()
            return True,"ok",amount
        except Exception:
            await self._conn.rollback(); raise

    async def recalculate_guild_level(self, guild_id):
        g=await self.get_guild(guild_id)
        if not g: return None
        level=min(20,1+int(g["xp"])//1000)
        if level!=int(g["level"]):
            await self._conn.execute("UPDATE guilds SET level=?,updated_at=? WHERE guild_id=?",(level,time.time(),guild_id))
            await self._conn.commit()
            g=await self.get_guild(guild_id)
        return g

    async def guild_multiplier(self, server_id, user_id):
        g=await self.get_user_guild(server_id,user_id)
        if not g: return 1.0
        return 1.0 + min(0.20,max(0,int(g["level"])-1)*0.01)

    async def create_guild_event(self, guild_id, event_id, title, description, target, reward_coins, reward_xp, duration):
        now=time.time()
        await self._conn.execute(
            "INSERT OR REPLACE INTO guild_events(guild_id,event_id,title,description,target,progress,reward_coins,reward_xp,ends_at,completed,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (str(guild_id),str(event_id),str(title),str(description),int(target),0,int(reward_coins),int(reward_xp),now+int(duration),0,now),
        )
        await self._conn.commit()
        return await self.get_guild_event(guild_id,event_id)

    async def get_guild_event(self,guild_id,event_id=None):
        q="SELECT * FROM guild_events WHERE guild_id=?"; p=[str(guild_id)]
        if event_id: q+=" AND event_id=?"; p.append(str(event_id))
        q+=" ORDER BY created_at DESC LIMIT 1"
        cur=await self._conn.execute(q,p); row=await cur.fetchone()
        return dict(row) if row else None

    async def contribute_guild_event(self,guild_id,user_id,amount):
        event=await self.get_guild_event(guild_id)
        if not event or event["completed"] or float(event["ends_at"])<=time.time(): return False,"inactive"
        amount=max(1,int(amount))
        g=await self.get_guild(guild_id)
        member=await self.get_user_guild(g["server_id"],user_id) if g else None
        if not member: return False,"member"
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            new=min(int(event["target"]),int(event["progress"])+amount)
            completed=1 if new>=int(event["target"]) else 0
            await self._conn.execute("INSERT INTO guild_event_contributors(guild_id,event_id,user_id,contribution) VALUES(?,?,?,?) ON CONFLICT(guild_id,event_id,user_id) DO UPDATE SET contribution=contribution+excluded.contribution",(guild_id,event["event_id"],str(user_id),amount))
            await self._conn.execute("UPDATE guild_events SET progress=?,completed=? WHERE guild_id=? AND event_id=?",(new,completed,guild_id,event["event_id"]))
            await self._conn.commit()
            return True,"completed" if completed else "ok"
        except Exception:
            await self._conn.rollback(); raise

    async def create_guild_boss(self,guild_id,boss_id,name,max_hp,attack,reward_coins,reward_xp,duration):
        now=time.time()
        await self._conn.execute("INSERT OR REPLACE INTO guild_bosses(guild_id,boss_id,name,max_hp,hp,attack,reward_coins,reward_xp,ends_at,defeated,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(str(guild_id),str(boss_id),str(name),int(max_hp),int(max_hp),int(attack),int(reward_coins),int(reward_xp),now+int(duration),0,now))
        await self._conn.commit()
        return await self.get_guild_boss(guild_id)

    async def get_guild_boss(self,guild_id):
        cur=await self._conn.execute("SELECT * FROM guild_bosses WHERE guild_id=?",(str(guild_id),))
        row=await cur.fetchone(); return dict(row) if row else None

    async def damage_guild_boss(self,guild_id,user_id,damage):
        damage=max(1,int(damage)); boss=await self.get_guild_boss(guild_id)
        if not boss or boss["defeated"] or float(boss["ends_at"])<=time.time(): return False,"inactive",0
        g=await self.get_guild(guild_id)
        if not g: return False,"missing",0
        member=await self.get_user_guild(g["server_id"],user_id)
        if not member: return False,"member",0
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("UPDATE guild_bosses SET hp=MAX(0,hp-?) WHERE guild_id=? AND defeated=0",(damage,guild_id))
            if cur.rowcount!=1: await self._conn.rollback(); return False,"inactive",0
            await self._conn.execute("INSERT INTO guild_boss_contributors(guild_id,boss_id,user_id,damage) VALUES(?,?,?,?) ON CONFLICT(guild_id,boss_id,user_id) DO UPDATE SET damage=damage+excluded.damage",(guild_id,boss["boss_id"],str(user_id),damage))
            cur=await self._conn.execute("SELECT hp FROM guild_bosses WHERE guild_id=?",(guild_id,)); hp=int((await cur.fetchone())["hp"])
            if hp<=0: await self._conn.execute("UPDATE guild_bosses SET defeated=1 WHERE guild_id=?",(guild_id,))
            await self._conn.commit()
            return True,"defeated" if hp<=0 else "ok",hp
        except Exception:
            await self._conn.rollback(); raise

    async def start_guild_raid(self,guild_id,raid_id_key,max_hp,reward_coins,reward_xp,duration):
        now=time.time()
        cur=await self._conn.execute("SELECT 1 FROM guild_raids WHERE guild_id=? AND status='active'",(str(guild_id),))
        if await cur.fetchone(): return None,"active"
        cur=await self._conn.execute("INSERT INTO guild_raids(guild_id,raid_id_key,status,boss_hp,max_hp,reward_coins,reward_xp,ends_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(str(guild_id),str(raid_id_key),"active",int(max_hp),int(max_hp),int(reward_coins),int(reward_xp),now+int(duration),now))
        await self._conn.commit(); return int(cur.lastrowid),"ok"

    async def get_guild_raid(self,guild_id,raid_id=None):
        q="SELECT * FROM guild_raids WHERE guild_id=?"; p=[str(guild_id)]
        if raid_id is not None: q+=" AND raid_id=?"; p.append(int(raid_id))
        q+=" ORDER BY raid_id DESC LIMIT 1"
        cur=await self._conn.execute(q,p); row=await cur.fetchone(); return dict(row) if row else None

    async def damage_guild_raid(self,guild_id,user_id,damage):
        damage=max(1,int(damage)); raid=await self.get_guild_raid(guild_id)
        if not raid or raid["status"]!="active" or float(raid["ends_at"])<=time.time(): return False,"inactive",0
        g=await self.get_guild(guild_id)
        member=await self.get_user_guild(g["server_id"],user_id) if g else None
        if not member: return False,"member",0
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("UPDATE guild_raids SET boss_hp=MAX(0,boss_hp-?) WHERE raid_id=? AND status='active'",(damage,int(raid["raid_id"])))
            if cur.rowcount!=1: await self._conn.rollback(); return False,"inactive",0
            await self._conn.execute("INSERT INTO guild_raid_contributors(raid_id,user_id,damage) VALUES(?,?,?) ON CONFLICT(raid_id,user_id) DO UPDATE SET damage=damage+excluded.damage",(int(raid["raid_id"]),str(user_id),damage))
            cur=await self._conn.execute("SELECT boss_hp FROM guild_raids WHERE raid_id=?",(int(raid["raid_id"]),)); hp=int((await cur.fetchone())["boss_hp"])
            if hp<=0: await self._conn.execute("UPDATE guild_raids SET status='completed',completed=1 WHERE raid_id=?",(int(raid["raid_id"]),))
            await self._conn.commit()
            return True,"completed" if hp<=0 else "ok",hp
        except Exception:
            await self._conn.rollback(); raise

    async def spend_guild_treasury(self, guild_id, amount):
        guild_id=str(guild_id); amount=int(amount)
        if amount<=0: return False
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cur=await self._conn.execute("UPDATE guilds SET treasury=treasury-?,updated_at=? WHERE guild_id=? AND treasury>=?",(amount,time.time(),guild_id,amount))
            if cur.rowcount!=1: await self._conn.rollback(); return False
            await self._conn.commit(); return True
        except Exception:
            await self._conn.rollback(); raise

    async def declare_guild_war(self, guild_id, opponent_guild_id, duration=86400):
        guild_id,opponent_guild_id=str(guild_id),str(opponent_guild_id)
        if guild_id==opponent_guild_id: return None,"self"
        a=await self.get_guild(guild_id); b=await self.get_guild(opponent_guild_id)
        if not a or not b or a["server_id"]!=b["server_id"]: return None,"guild"
        cur=await self._conn.execute("SELECT 1 FROM guild_wars WHERE status='open' AND ((guild_id=? AND opponent_guild_id=?) OR (guild_id=? AND opponent_guild_id=?))",(guild_id,opponent_guild_id,opponent_guild_id,guild_id))
        if await cur.fetchone(): return None,"active"
        cur=await self._conn.execute("INSERT INTO guild_wars(guild_id,opponent_guild_id,created_at,ends_at) VALUES(?,?,?,?,?)".replace("VALUES(?,?,?,?,?)","VALUES(?,?,?,?)"),(guild_id,opponent_guild_id,time.time(),time.time()+int(duration)))
        await self._conn.commit(); return int(cur.lastrowid),"ok"

    async def get_guild_war(self, war_id):
        cur=await self._conn.execute("SELECT * FROM guild_wars WHERE war_id=?",(int(war_id),))
        row=await cur.fetchone(); return dict(row) if row else None

    async def add_guild_war_score(self, war_id, guild_id, points=1):
        war=await self.get_guild_war(war_id)
        if not war or war["status"]!="open" or float(war["ends_at"])<=time.time(): return False,"inactive"
        guild_id=str(guild_id); points=max(1,int(points))
        if guild_id not in {str(war["guild_id"]),str(war["opponent_guild_id"])}: return False,"guild"
        column="guild_score" if guild_id==str(war["guild_id"]) else "opponent_score"
        await self._conn.execute(f"UPDATE guild_wars SET {column}={column}+? WHERE war_id=?",(points,int(war_id)))
        await self._conn.commit(); return True,"ok"

    async def end_guild_war(self, war_id):
        war=await self.get_guild_war(war_id)
        if not war or war["status"]!="open": return None
        if float(war["ends_at"])>time.time(): return None
        if int(war["guild_score"])>int(war["opponent_score"]): winner=war["guild_id"]
        elif int(war["opponent_score"])>int(war["guild_score"]): winner=war["opponent_guild_id"]
        else: winner=None
        await self._conn.execute("UPDATE guild_wars SET status='ended',winner_guild_id=? WHERE war_id=?",(winner,int(war_id)))
        await self._conn.commit(); return await self.get_guild_war(war_id)

    async def set_server_event(self, server_id, event_id, title, multiplier, duration):
        now=time.time()
        await self._conn.execute(
            "INSERT OR REPLACE INTO guild_server_events(guild_id,event_id,title,multiplier,ends_at,created_at) VALUES(?,?,?,?,?,?)",
            (str(server_id),str(event_id),str(title),float(multiplier),now+int(duration),now),
        )
        await self._conn.commit()

    async def get_server_event(self, server_id):
        cur=await self._conn.execute("SELECT * FROM guild_server_events WHERE guild_id=? AND ends_at>?",(str(server_id),time.time()))
        row=await cur.fetchone(); return dict(row) if row else None

    async def claim_guild_relic(self, guild_id, equipment_id, owner_id, cost=50000, min_level=10):
        g=await self.get_guild(guild_id)
        if not g or int(g["level"])<int(min_level): return False,"level"
        cur=await self._conn.execute("SELECT 1 FROM guild_legendary_equipment WHERE guild_id=? AND equipment_id=?",(str(guild_id),str(equipment_id)))
        if await cur.fetchone(): return False,"owned"
        if not await self.spend_guild_treasury(guild_id,cost): return False,"treasury"
        await self._conn.execute("INSERT INTO guild_legendary_equipment(guild_id,equipment_id,owner_id,rarity,acquired_at) VALUES(?,?,?,?,?)",(str(guild_id),str(equipment_id),str(owner_id),"legendary",time.time()))
        await self._conn.commit(); return True,"ok"

    async def get_guild_relics(self,guild_id):
        cur=await self._conn.execute("SELECT * FROM guild_legendary_equipment WHERE guild_id=? ORDER BY acquired_at",(str(guild_id),))
        return [dict(r) for r in await cur.fetchall()]

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
        allowed = {
            "enemy_id", "enemy_name", "enemy_hp", "enemy_max_hp",
            "enemy_attack", "turn", "guarding", "created_at",
            "effects", "special_cooldowns"
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        values = (
            guild_id,
            user_id,
            fields.get("enemy_id", ""),
            fields.get("enemy_name", ""),
            int(fields.get("enemy_hp", 0)),
            int(fields.get("enemy_max_hp", 0)),
            int(fields.get("enemy_attack", 0)),
            int(fields.get("turn", 1)),
            int(fields.get("guarding", 0)),
            float(fields.get("created_at", time.time())),
            str(fields.get("effects", "{}")),
            str(fields.get("special_cooldowns", "{}")),
        )
        sql = (
            "INSERT INTO rpg_battles "
            "(guild_id,user_id,enemy_id,enemy_name,enemy_hp,enemy_max_hp,"
            "enemy_attack,turn,guarding,created_at,effects,special_cooldowns) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "enemy_id=excluded.enemy_id, enemy_name=excluded.enemy_name, "
            "enemy_hp=excluded.enemy_hp, enemy_max_hp=excluded.enemy_max_hp, "
            "enemy_attack=excluded.enemy_attack, turn=excluded.turn, "
            "guarding=excluded.guarding, created_at=excluded.created_at, "
            "effects=excluded.effects, special_cooldowns=excluded.special_cooldowns"
        )
        await self._conn.execute(sql, values)
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

    async def set_rpg_item_equipped(self, guild_id, user_id, item_id, equipped=True):
        await self._conn.execute(
            "UPDATE rpg_items SET equipped = ? "
            "WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (1 if equipped else 0, str(guild_id), str(user_id), str(item_id))
        )
        await self._conn.commit()

    async def get_rpg_skills(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT skill_id FROM rpg_skills "
            "WHERE guild_id = ? AND user_id = ? AND unlocked = 1 "
            "ORDER BY skill_id",
            (str(guild_id), str(user_id))
        )
        return [r["skill_id"] for r in await cur.fetchall()]

    async def unlock_rpg_skill(self, guild_id, user_id, skill_id):
        await self._conn.execute(
            "INSERT INTO rpg_skills "
            "(guild_id, user_id, skill_id, unlocked) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(guild_id, user_id, skill_id) "
            "DO UPDATE SET unlocked = 1",
            (str(guild_id), str(user_id), str(skill_id))
        )
        await self._conn.commit()

    async def remove_rpg_item(self, guild_id, user_id, item_id, amount=1):
        amount = int(amount)
        if amount <= 0:
            return True
        cur = await self._conn.execute(
            "SELECT amount FROM rpg_items WHERE guild_id=? AND user_id=? AND item_id=?",
            (str(guild_id), str(user_id), str(item_id))
        )
        row = await cur.fetchone()
        if not row or int(row["amount"]) < amount:
            return False
        remaining = int(row["amount"]) - amount
        await self._conn.execute(
            "UPDATE rpg_items SET amount=?, equipped=CASE WHEN ?=0 THEN 0 ELSE equipped END "
            "WHERE guild_id=? AND user_id=? AND item_id=?",
            (remaining, remaining, str(guild_id), str(user_id), str(item_id))
        )
        if remaining <= 0:
            await self._conn.execute(
                "DELETE FROM rpg_items WHERE guild_id=? AND user_id=? AND item_id=?",
                (str(guild_id), str(user_id), str(item_id))
            )
        await self._conn.commit()
        return True

    async def get_rpg_materials(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT material_id, amount FROM rpg_materials "
            "WHERE guild_id=? AND user_id=? AND amount > 0 ORDER BY material_id",
            (str(guild_id), str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def add_rpg_material(self, guild_id, user_id, material_id, amount=1):
        amount = int(amount)
        if amount <= 0:
            return
        await self._conn.execute(
            "INSERT INTO rpg_materials (guild_id,user_id,material_id,amount) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,material_id) "
            "DO UPDATE SET amount=amount+excluded.amount",
            (str(guild_id), str(user_id), str(material_id), amount)
        )
        await self._conn.commit()

    async def remove_rpg_material(self, guild_id, user_id, material_id, amount=1):
        amount = int(amount)
        if amount <= 0:
            return True
        cur = await self._conn.execute(
            "SELECT amount FROM rpg_materials WHERE guild_id=? AND user_id=? AND material_id=?",
            (str(guild_id), str(user_id), str(material_id))
        )
        row = await cur.fetchone()
        if not row or int(row["amount"]) < amount:
            return False
        remaining = int(row["amount"]) - amount
        if remaining:
            await self._conn.execute(
                "UPDATE rpg_materials SET amount=? WHERE guild_id=? AND user_id=? AND material_id=?",
                (remaining, str(guild_id), str(user_id), str(material_id))
            )
        else:
            await self._conn.execute(
                "DELETE FROM rpg_materials WHERE guild_id=? AND user_id=? AND material_id=?",
                (str(guild_id), str(user_id), str(material_id))
            )
        await self._conn.commit()
        return True

    async def has_rpg_materials(self, guild_id, user_id, costs):
        rows = await self.get_rpg_materials(guild_id, user_id)
        have = {r["material_id"]: int(r["amount"]) for r in rows}
        return all(have.get(mid, 0) >= int(amount) for mid, amount in costs.items())


    async def get_rpg_specials(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT special_id FROM rpg_specials "
            "WHERE guild_id=? AND user_id=? AND unlocked=1 ORDER BY special_id",
            (str(guild_id), str(user_id))
        )
        return [r["special_id"] for r in await cur.fetchall()]

    async def unlock_rpg_special(self, guild_id, user_id, special_id, source="level"):
        await self._conn.execute(
            "INSERT INTO rpg_specials "
            "(guild_id,user_id,special_id,unlocked,unlocked_at,source) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,special_id) DO UPDATE SET unlocked=1",
            (str(guild_id), str(user_id), str(special_id), 1, time.time(), str(source))
        )
        await self._conn.commit()

    async def has_rpg_special(self, guild_id, user_id, special_id):
        cur = await self._conn.execute(
            "SELECT 1 FROM rpg_specials WHERE guild_id=? AND user_id=? AND special_id=? AND unlocked=1",
            (str(guild_id), str(user_id), str(special_id))
        )
        return await cur.fetchone() is not None

    async def clear_warnings(self, guild_id, user_id):
        await self._conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id))
        )
        await self._conn.commit()    async def claim_arcade_match(self, guild_id, match_id, user_id):
        cur = await self._conn.execute(
            "SELECT m.*, t.guild_id FROM arcade_tournament_matches m "
            "JOIN arcade_tournaments t ON t.tournament_id=m.tournament_id "
            "WHERE m.match_id=?",
            (int(match_id),)
        )
        m = await cur.fetchone()
        if not m or str(m["guild_id"]) != str(guild_id) or m["status"] != "ready":
            return False, None
        if str(user_id) not in {str(m["player_a"]), str(m["player_b"])}:
            return False, None
        update_cur = await self._conn.execute(
            "UPDATE arcade_tournament_matches SET status='playing' "
            "WHERE match_id=? AND status='ready'",
            (int(match_id),)
        )
        if update_cur.rowcount != 1:
            return False, None
        await self._conn.commit()
        cur = await self._conn.execute(
            "SELECT m.*, t.guild_id, t.game_id, t.name AS tournament_name "
            "FROM arcade_tournament_matches m "
            "JOIN arcade_tournaments t ON t.tournament_id=m.tournament_id "
            "WHERE m.match_id=?",
            (int(match_id),)
        )
        current = await cur.fetchone()
        if not current or current["status"] != "playing":
            return False, None
        return True, dict(current)

    async def reset_arcade_match(self, match_id):
        await self._conn.execute(
            "UPDATE arcade_tournament_matches SET status='ready' "
            "WHERE match_id=? AND status='playing'",
            (int(match_id),)
        )
        await self._conn.commit()
        cur = await self._conn.execute(
            "SELECT * FROM arcade_tournament_matches WHERE match_id=?",
            (int(match_id),)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def resolve_arcade_match(self, match_id, winner_id):
        cur = await self._conn.execute(
            "SELECT * FROM arcade_tournament_matches WHERE match_id=?",
            (int(match_id),)
        )
        m = await cur.fetchone()
        if not m or m["status"] not in ("ready", "playing"):
            return False, None
        if str(winner_id) not in {str(m["player_a"]), str(m["player_b"])}:
            return False, None
        await self._conn.execute(
            "UPDATE arcade_tournament_matches SET winner_id=?,status='complete' "
            "WHERE match_id=? AND status IN ('ready','playing')",
            (str(winner_id), int(match_id))
        )
        loser = m["player_b"] if str(winner_id) == str(m["player_a"]) else m["player_a"]
        await self._conn.execute(
            "UPDATE arcade_tournament_players SET wins=wins+1 "
            "WHERE tournament_id=? AND user_id=?",
            (m["tournament_id"], str(winner_id))
        )
        if loser:
            await self._conn.execute(
                "UPDATE arcade_tournament_players SET eliminated=1 "
                "WHERE tournament_id=? AND user_id=?",
                (m["tournament_id"], str(loser))
            )
        await self._conn.commit()
        result = await self._advance_tournament(int(m["tournament_id"]))
        return True, result or {
            "finished": False,
            "tournament_id": int(m["tournament_id"])
        }

    # ECLIPSE PROFILE / BANK / MUSIC / WORLD
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
        periods = int(max(0, now - float(last)) // period)
        if periods <= 0:
            return 0, user
        balance = int(user["bank_balance"])
        if balance <= 0:
            await self.update_user(guild_id, user_id, last_bank_interest=now)
            return 0, await self.get_user(guild_id, user_id)
        interest = int(balance * rate * periods)
        await self._conn.execute(
            "UPDATE users SET bank_balance=bank_balance+?, last_bank_interest=? WHERE guild_id=? AND user_id=?",
            (interest, now, str(guild_id), str(user_id))
        )
        await self._conn.commit()
        return interest, await self.get_user(guild_id, user_id)

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
        clean = {mapping[k]: v for k, v in fields.items() if k in mapping}
        if clean:
            await self.set_guild_config(guild_id, **clean)
        return await self.get_music_config(guild_id)

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
            guild_id, user_id, gold=int(player["gold"]) - amount
        )
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
        allowed = {
            "enemy_id", "enemy_name", "enemy_hp", "enemy_max_hp",
            "enemy_attack", "turn", "guarding", "created_at",
            "effects", "special_cooldowns"
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        values = (
            guild_id,
            user_id,
            fields.get("enemy_id", ""),
            fields.get("enemy_name", ""),
            int(fields.get("enemy_hp", 0)),
            int(fields.get("enemy_max_hp", 0)),
            int(fields.get("enemy_attack", 0)),
            int(fields.get("turn", 1)),
            int(fields.get("guarding", 0)),
            float(fields.get("created_at", time.time())),
            str(fields.get("effects", "{}")),
            str(fields.get("special_cooldowns", "{}")),
        )
        sql = (
            "INSERT INTO rpg_battles "
            "(guild_id,user_id,enemy_id,enemy_name,enemy_hp,enemy_max_hp,"
            "enemy_attack,turn,guarding,created_at,effects,special_cooldowns) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "enemy_id=excluded.enemy_id, enemy_name=excluded.enemy_name, "
            "enemy_hp=excluded.enemy_hp, enemy_max_hp=excluded.enemy_max_hp, "
            "enemy_attack=excluded.enemy_attack, turn=excluded.turn, "
            "guarding=excluded.guarding, created_at=excluded.created_at, "
            "effects=excluded.effects, special_cooldowns=excluded.special_cooldowns"
        )
        await self._conn.execute(sql, values)
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

    async def set_rpg_item_equipped(self, guild_id, user_id, item_id, equipped=True):
        await self._conn.execute(
            "UPDATE rpg_items SET equipped = ? "
            "WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (1 if equipped else 0, str(guild_id), str(user_id), str(item_id))
        )
        await self._conn.commit()

    async def get_rpg_skills(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT skill_id FROM rpg_skills "
            "WHERE guild_id = ? AND user_id = ? AND unlocked = 1 "
            "ORDER BY skill_id",
            (str(guild_id), str(user_id))
        )
        return [r["skill_id"] for r in await cur.fetchall()]

    async def unlock_rpg_skill(self, guild_id, user_id, skill_id):
        await self._conn.execute(
            "INSERT INTO rpg_skills "
            "(guild_id, user_id, skill_id, unlocked) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(guild_id, user_id, skill_id) "
            "DO UPDATE SET unlocked = 1",
            (str(guild_id), str(user_id), str(skill_id))
        )
        await self._conn.commit()

    async def remove_rpg_item(self, guild_id, user_id, item_id, amount=1):
        amount = int(amount)
        if amount <= 0:
            return True
        cur = await self._conn.execute(
            "SELECT amount FROM rpg_items WHERE guild_id=? AND user_id=? AND item_id=?",
            (str(guild_id), str(user_id), str(item_id))
        )
        row = await cur.fetchone()
        if not row or int(row["amount"]) < amount:
            return False
        remaining = int(row["amount"]) - amount
        await self._conn.execute(
            "UPDATE rpg_items SET amount=?, equipped=CASE WHEN ?=0 THEN 0 ELSE equipped END "
            "WHERE guild_id=? AND user_id=? AND item_id=?",
            (remaining, remaining, str(guild_id), str(user_id), str(item_id))
        )
        if remaining <= 0:
            await self._conn.execute(
                "DELETE FROM rpg_items WHERE guild_id=? AND user_id=? AND item_id=?",
                (str(guild_id), str(user_id), str(item_id))
            )
        await self._conn.commit()
        return True

    async def get_rpg_materials(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT material_id, amount FROM rpg_materials "
            "WHERE guild_id=? AND user_id=? AND amount > 0 ORDER BY material_id",
            (str(guild_id), str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def add_rpg_material(self, guild_id, user_id, material_id, amount=1):
        amount = int(amount)
        if amount <= 0:
            return
        await self._conn.execute(
            "INSERT INTO rpg_materials (guild_id,user_id,material_id,amount) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,material_id) "
            "DO UPDATE SET amount=amount+excluded.amount",
            (str(guild_id), str(user_id), str(material_id), amount)
        )
        await self._conn.commit()

    async def remove_rpg_material(self, guild_id, user_id, material_id, amount=1):
        amount = int(amount)
        if amount <= 0:
            return True
        cur = await self._conn.execute(
            "SELECT amount FROM rpg_materials WHERE guild_id=? AND user_id=? AND material_id=?",
            (str(guild_id), str(user_id), str(material_id))
        )
        row = await cur.fetchone()
        if not row or int(row["amount"]) < amount:
            return False
        remaining = int(row["amount"]) - amount
        if remaining:
            await self._conn.execute(
                "UPDATE rpg_materials SET amount=? WHERE guild_id=? AND user_id=? AND material_id=?",
                (remaining, str(guild_id), str(user_id), str(material_id))
            )
        else:
            await self._conn.execute(
                "DELETE FROM rpg_materials WHERE guild_id=? AND user_id=? AND material_id=?",
                (str(guild_id), str(user_id), str(material_id))
            )
        await self._conn.commit()
        return True

    async def has_rpg_materials(self, guild_id, user_id, costs):
        rows = await self.get_rpg_materials(guild_id, user_id)
        have = {r["material_id"]: int(r["amount"]) for r in rows}
        return all(have.get(mid, 0) >= int(amount) for mid, amount in costs.items())

    async def get_rpg_specials(self, guild_id, user_id):
        cur = await self._conn.execute(
            "SELECT special_id FROM rpg_specials "
            "WHERE guild_id=? AND user_id=? AND unlocked=1 ORDER BY special_id",
            (str(guild_id), str(user_id))
        )
        return [r["special_id"] for r in await cur.fetchall()]

    async def unlock_rpg_special(self, guild_id, user_id, special_id, source="level"):
        await self._conn.execute(
            "INSERT INTO rpg_specials "
            "(guild_id,user_id,special_id,unlocked,unlocked_at,source) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,special_id) DO UPDATE SET unlocked=1",
            (str(guild_id), str(user_id), str(special_id), 1, time.time(), str(source))
        )
        await self._conn.commit()

    async def has_rpg_special(self, guild_id, user_id, special_id):
        cur = await self._conn.execute(
            "SELECT 1 FROM rpg_specials "
            "WHERE guild_id=? AND user_id=? AND special_id=? AND unlocked=1",
            (str(guild_id), str(user_id), str(special_id))
        )
        return await cur.fetchone() is not None

    async def clear_warnings(self, guild_id, user_id):
        await self._conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id))
        )
        await self._conn.commit()
