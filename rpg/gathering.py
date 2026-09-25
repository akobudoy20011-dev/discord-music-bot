"""ECLIPSE RPG gathering and collection progression."""

from __future__ import annotations
import random

RESOURCE_NODES = {
    "mining": {"icon": "⛏️", "name": "Mining", "resources": {
        "moonlit_vale": [("copper_ore", 1, 4), ("moonstone", 0, 1)],
        "whispering_wood": [("iron_ore", 1, 5), ("moonstone", 1, 2)],
        "ashen_crown": [("ash_ore", 1, 5), ("ash_core", 0, 2)],
        "starfall_coast": [("star_fragment", 1, 4), ("astral_ore", 0, 2)],
    }},
    "woodcutting": {"icon": "🪓", "name": "Woodcutting", "resources": {
        "moonlit_vale": [("softwood", 1, 4)],
        "whispering_wood": [("thornwood", 2, 6), ("thorn_fiber", 1, 2)],
        "ashen_crown": [("charred_wood", 1, 4), ("ash_core", 0, 1)],
        "starfall_coast": [("starwood", 1, 4), ("star_fragment", 0, 1)],
    }},
    "hunting": {"icon": "🏹", "name": "Hunting", "resources": {
        "moonlit_vale": [("wolf_fang", 1, 3), ("pale_hide", 0, 1)],
        "whispering_wood": [("wolf_fang", 1, 4), ("beast_hide", 1, 2)],
        "ashen_crown": [("drake_scale", 1, 3), ("ash_core", 0, 1)],
        "starfall_coast": [("star_hide", 1, 2), ("leviathan_scale", 0, 1)],
    }},
    "fishing": {"icon": "🎣", "name": "Fishing", "resources": {
        "moonlit_vale": [("silverfish", 1, 4)],
        "whispering_wood": [("forest_trout", 1, 4), ("moonstone", 0, 1)],
        "ashen_crown": [("emberfish", 1, 3), ("ash_core", 0, 1)],
        "starfall_coast": [("starfish", 1, 4), ("star_fragment", 0, 1)],
    }},
    "alchemy": {"icon": "⚗️", "name": "Alchemy", "resources": {
        "moonlit_vale": [("moon_petal", 1, 3), ("moonstone", 0, 1)],
        "whispering_wood": [("thorn_fiber", 1, 4), ("moon_petal", 1, 2)],
        "ashen_crown": [("ash_core", 1, 3), ("drake_scale", 0, 1)],
        "starfall_coast": [("star_fragment", 1, 3), ("astral_ore", 0, 1)],
    }},
}

async def _schema(db):
    await db._conn.execute("""CREATE TABLE IF NOT EXISTS rpg_gathering (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, skill_id TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,
        total_gathered INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id,user_id,skill_id))""")
    await db._conn.execute("""CREATE TABLE IF NOT EXISTS rpg_collections (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, collection_id TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id,user_id,collection_id))""")
    await db._conn.commit()

def _next(level):
    return max(25, level * 50)

async def profile(db, guild_id, user_id):
    await _schema(db)
    cur = await db._conn.execute(
        "SELECT * FROM rpg_gathering WHERE guild_id=? AND user_id=? ORDER BY skill_id",
        (str(guild_id), str(user_id)))
    return [dict(r) for r in await cur.fetchall()]

async def gather(db, guild_id, user_id, skill_id):
    await _schema(db)
    skill_id = str(skill_id).lower()
    skill = RESOURCE_NODES.get(skill_id)
    if not skill:
        return {"ok": False, "message": "Unknown gathering skill."}
    player = await db.get_rpg_player(guild_id, user_id)
    region = player.get("region") or "moonlit_vale"
    pool = skill["resources"].get(region, skill["resources"]["moonlit_vale"])
    row = next((r for r in await profile(db, guild_id, user_id) if r["skill_id"] == skill_id), None)
    level = int(row["level"]) if row else 1
    xp = int(row["xp"]) if row else 0
    item_id, low, high = random.choice(pool)
    rare = random.random() < 0.06 + min(0.12, level * 0.01)
    amount = random.randint(max(1, high), max(1, high + 2)) if rare else random.randint(max(1, low), max(1, high))
    rarity = "rare" if rare else "normal"
    await db.add_rpg_material(guild_id, user_id, item_id, amount)
    gained_xp = 8 + level * 2
    xp += gained_xp
    total = (int(row["total_gathered"]) if row else 0) + amount
    while xp >= _next(level):
        xp -= _next(level)
        level += 1
    await db._conn.execute("""INSERT INTO rpg_gathering
        (guild_id,user_id,skill_id,level,xp,total_gathered) VALUES (?,?,?,?,?,?)
        ON CONFLICT(guild_id,user_id,skill_id) DO UPDATE SET
        level=excluded.level,xp=excluded.xp,total_gathered=excluded.total_gathered""",
        (str(guild_id),str(user_id),skill_id,level,xp,total))
    await db._conn.execute("""INSERT INTO rpg_collections
        (guild_id,user_id,collection_id,amount) VALUES (?,?,?,?)
        ON CONFLICT(guild_id,user_id,collection_id) DO UPDATE SET amount=amount+excluded.amount""",
        (str(guild_id),str(user_id),item_id,amount))
    await db._conn.commit()
    try:
        from .expansion import daily_progress
        await daily_progress(db, guild_id, user_id, "gather", amount)
    except Exception:
        pass
    achievements = []
    try:
        from .achievements import check
        achievements = await check(db, guild_id, user_id)
    except Exception:
        achievements = []
    return {"ok":True,"skill":skill,"item_id":item_id,"amount":amount,"rarity":rarity,
            "level":level,"xp":xp,"gained_xp":gained_xp,"region":region,
            "achievements":achievements}

async def collections(db, guild_id, user_id):
    await _schema(db)
    cur = await db._conn.execute(
        "SELECT collection_id,amount FROM rpg_collections WHERE guild_id=? AND user_id=? ORDER BY amount DESC, collection_id",
        (str(guild_id),str(user_id)))
    return [dict(r) for r in await cur.fetchall()]
