"""ECLIPSE RPG dungeon delve system.

Inspired by strong Discord RPG patterns: short room-based delves, push-your-luck
decisions, daily progression, data-driven rewards, and persistent runs. It does
not replace the existing combat engine; dungeon combat is an abstract encounter
layer.
"""

from __future__ import annotations
import random
import time

from .items import get_item

DAILY_COOLDOWN = 20 * 60 * 60
MAX_FLOOR = 12

DUNGEONS = {
    "mooncrypt": {
        "name": "Mooncrypt", "icon": "🕯️", "region": "moonlit_vale",
        "min_level": 1, "base_enemy": 22, "boss": "Gravebound Saint",
        "boss_power": 95, "loot": ["guardian_mail", "mana_charm"],
    },
    "rootvault": {
        "name": "Rootvault", "icon": "🌿", "region": "whispering_wood",
        "min_level": 4, "base_enemy": 38, "boss": "Rootbound Tyrant",
        "boss_power": 150, "loot": ["thornblade", "thornmantle", "veilring"],
    },
    "ashforge": {
        "name": "Ashforge", "icon": "🔥", "region": "ashen_crown",
        "min_level": 8, "base_enemy": 62, "boss": "Cinder Warlord",
        "boss_power": 240, "loot": ["embercleaver", "ashplate"],
    },
    "starvault": {
        "name": "Starvault", "icon": "🌠", "region": "starfall_coast",
        "min_level": 12, "base_enemy": 90, "boss": "Astral Devourer",
        "boss_power": 360, "loot": ["starfall_staff", "starweave"],
    },
}

def list_dungeons():
    return list(DUNGEONS.items())

async def _schema(db):
    await db._conn.execute("""
        CREATE TABLE IF NOT EXISTS rpg_dungeon_runs (
            guild_id TEXT NOT NULL, user_id TEXT NOT NULL, dungeon_id TEXT NOT NULL,
            floor INTEGER NOT NULL DEFAULT 0, hp INTEGER NOT NULL DEFAULT 0,
            gold INTEGER NOT NULL DEFAULT 0, xp INTEGER NOT NULL DEFAULT 0,
            rooms INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
            started_at REAL NOT NULL, completed_at REAL,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    await db._conn.execute("""
        CREATE TABLE IF NOT EXISTS rpg_dungeon_daily (
            guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
            last_completed REAL NOT NULL DEFAULT 0, best_floor INTEGER NOT NULL DEFAULT 0,
            total_clears INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    await db._conn.commit()

async def _get_run(db, guild_id, user_id):
    await _schema(db)
    cur = await db._conn.execute(
        "SELECT * FROM rpg_dungeon_runs WHERE guild_id=? AND user_id=?",
        (str(guild_id), str(user_id)),
    )
    row = await cur.fetchone()
    return dict(row) if row else None

async def start(db, guild_id, user_id, dungeon_id):
    await _schema(db)
    dungeon_id = str(dungeon_id).lower()
    dungeon = DUNGEONS.get(dungeon_id)
    if not dungeon:
        return {"ok": False, "message": "Unknown dungeon."}
    player = await db.get_rpg_player(guild_id, user_id)
    now = time.time()
    travel_until = float(player.get("travel_until") or 0)
    if travel_until > now:
        return {"ok": False, "message": f"You are still traveling. {travel_until - now:.0f}s remain."}
    if int(player["level"]) < dungeon["min_level"]:
        return {"ok": False, "message": f"You need RPG Level {dungeon['min_level']}."}
    active_battle = await db.get_rpg_battle(guild_id, user_id)
    if active_battle:
        return {"ok": False, "message": "You are already in combat. Finish or flee the battle before entering a dungeon."}
    hunt_active = await db.get_rpg_hunt_active(guild_id, user_id)
    if hunt_active:
        return {"ok": False, "message": "You have a prepared monster hunt. Finish or cancel the hunt before entering a dungeon."}
    cur = await db._conn.execute("SELECT last_completed FROM rpg_dungeon_daily WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
    daily = await cur.fetchone()
    if daily and float(daily["last_completed"] or 0) + DAILY_COOLDOWN > time.time():
        remaining = float(daily["last_completed"]) + DAILY_COOLDOWN - time.time()
        return {"ok": False, "message": f"Your daily dungeon is still on cooldown for {remaining / 3600:.1f}h."}
    existing = await _get_run(db, guild_id, user_id)
    if existing and existing["status"] == "active":
        return {"ok": False, "message": f"You already have an active delve in {dungeon['name']}."}
    now = time.time()
    await db._conn.execute(
        """INSERT INTO rpg_dungeon_runs
        (guild_id,user_id,dungeon_id,floor,hp,gold,xp,rooms,status,started_at,completed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
        ON CONFLICT(guild_id,user_id) DO UPDATE SET
        dungeon_id=excluded.dungeon_id,floor=0,hp=excluded.hp,gold=0,xp=0,
        rooms=0,status='active',started_at=excluded.started_at,completed_at=NULL""",
        (str(guild_id), str(user_id), dungeon_id, 0, int(player["hp"]), 0, 0, 0, "active", now),
    )
    await db._conn.commit()
    return {"ok": True, "dungeon": dungeon, "run": await _get_run(db, guild_id, user_id)}

async def status(db, guild_id, user_id):
    return await _get_run(db, guild_id, user_id)

async def advance(db, guild_id, user_id):
    run = await _get_run(db, guild_id, user_id)
    if not run or run["status"] != "active":
        return {"ok": False, "message": "No active dungeon. Use !rpg dungeon start <id>."}
    player = await db.get_rpg_player(guild_id, user_id)
    travel_until = float(player.get("travel_until") or 0)
    if travel_until > time.time():
        return {"ok": False, "message": f"You are still traveling. {travel_until - time.time():.0f}s remain."}
    dungeon = DUNGEONS[run["dungeon_id"]]
    floor = min(MAX_FLOOR, int(run["floor"]) + 1)
    threat = dungeon["base_enemy"] + floor * 8 + max(0, int(player["level"]) - dungeon["min_level"]) * 3
    roll = random.random()

    if floor >= MAX_FLOOR:
        damage = max(1, int(threat * random.uniform(0.35, 0.65)))
        reward_gold = int(threat * 21 + random.randint(300, 750))
        reward_xp = int(threat * 9 + 360)
        success = int(player["strength"]) + int(player["defense"]) + int(player["magic"]) + int(player["agility"]) + random.randint(0, 80) >= dungeon["boss_power"]
        if not success:
            await _finish(db, guild_id, user_id, "failed", floor)
            return {"ok": True, "result": "boss_failed", "dungeon": dungeon, "floor": floor, "damage": damage}
        reward_gold *= 3
        reward_xp *= 3
        boss = True
    else:
        boss = False
        if roll < 0.12:
            damage = 0
            reward_gold = random.randint(60, 120) + floor * 15
            reward_xp = 50 + floor * 12
            outcome = "treasure"
        elif roll < 0.28:
            damage = max(1, int(threat * random.uniform(0.05, 0.22)))
            reward_gold = random.randint(90, 180) + floor * 20
            reward_xp = 65 + floor * 15
            outcome = "elite"
        else:
            damage = max(1, int(threat * random.uniform(0.08, 0.30)))
            reward_gold = random.randint(35, 90) + floor * 12
            reward_xp = 45 + floor * 10
            outcome = "room"

    hp = max(0, int(player["hp"]) - int(damage))
    if hp <= 0:
        await db.update_rpg_player(guild_id, user_id, hp=1)
        await _finish(db, guild_id, user_id, "failed", floor)
        return {"ok": True, "result": "defeated", "dungeon": dungeon, "floor": floor, "damage": damage}

    old, new, player = await db.add_rpg_xp(guild_id, user_id, reward_xp)
    player = await db.update_rpg_player(guild_id, user_id, hp=hp, gold=int(player["gold"]) + reward_gold)

    if boss:
        item_id = random.choice(dungeon["loot"])
        await db.add_rpg_item(guild_id, user_id, item_id, 1)
        item = get_item(item_id)
        if item and item.get("rarity") in {"rare", "epic", "legendary", "relic"}:
            from .expansion import assign_affixes
            await assign_affixes(db, guild_id, user_id, item_id)
        await _finish(db, guild_id, user_id, "cleared", floor)
        return {"ok": True, "result": "boss_cleared", "dungeon": dungeon, "floor": floor,
                "damage": damage, "gold": reward_gold, "xp": reward_xp, "item": item_id,
                "old_level": old, "new_level": new}
    await db._conn.execute(
        "UPDATE rpg_dungeon_runs SET floor=?,hp=?,gold=gold+?,xp=xp+?,rooms=rooms+1 WHERE guild_id=? AND user_id=?",
        (floor, hp, reward_gold, reward_xp, str(guild_id), str(user_id)),
    )
    await db._conn.commit()
    return {"ok": True, "result": outcome, "dungeon": dungeon, "floor": floor,
            "damage": damage, "gold": reward_gold, "xp": reward_xp,
            "old_level": old, "new_level": new}

async def retreat(db, guild_id, user_id):
    run = await _get_run(db, guild_id, user_id)
    if not run or run["status"] != "active":
        return {"ok": False, "message": "No active dungeon."}
    player = await db.get_rpg_player(guild_id, user_id)
    bank_gold = max(0, int(run["gold"]))
    bank_xp = max(0, int(run["xp"]))
    old_level, new_level, player = await db.add_rpg_xp(guild_id, user_id, bank_xp) if bank_xp else (
        int(player["level"]), int(player["level"]), player
    )
    player = await db.update_rpg_player(
        guild_id, user_id, gold=int(player["gold"]) + bank_gold
    ) if bank_gold else player
    await _finish(db, guild_id, user_id, "retreated", int(run["floor"]))
    return {
        "ok": True,
        "floor": int(run["floor"]),
        "gold": bank_gold,
        "xp": bank_xp,
        "old_level": old_level,
        "new_level": new_level,
        "player": player,
    }

async def _finish(db, guild_id, user_id, status_value, floor):
    now = time.time()
    await db._conn.execute(
        "UPDATE rpg_dungeon_runs SET status=?,completed_at=? WHERE guild_id=? AND user_id=?",
        (status_value, now, str(guild_id), str(user_id)),
    )
    await db._conn.execute(
        """INSERT INTO rpg_dungeon_daily(guild_id,user_id,last_completed,best_floor,total_clears)
        VALUES (?,?,?,?,?)
        ON CONFLICT(guild_id,user_id) DO UPDATE SET
        last_completed=CASE WHEN excluded.last_completed > 0 THEN excluded.last_completed ELSE last_completed END,
        best_floor=MAX(best_floor,excluded.best_floor),
        total_clears=total_clears+excluded.total_clears""",
        (str(guild_id), str(user_id), now if status_value == "cleared" else 0, int(floor), 1 if status_value == "cleared" else 0),
    )
    await db._conn.commit()
