"""RPG achievements for the expanded dungeon/gathering systems."""

from __future__ import annotations

ACHIEVEMENTS = {
    "first_delve": ("🕯️", "First Descent", "Complete your first dungeon delve.", 100),
    "deep_5": ("⚔️", "Into the Deep", "Reach dungeon floor 5.", 150),
    "deep_12": ("👑", "The Last Door", "Clear floor 12.", 500),
    "gather_100": ("🌿", "Hands of the Realm", "Gather 100 resources.", 150),
    "gather_500": ("⛏️", "Master Gatherer", "Gather 500 resources.", 350),
    "collection_10": ("📚", "Collector", "Discover 10 different resources.", 200),
    "collection_20": ("🌌", "Curator of the Veil", "Discover 20 different resources.", 500),
}

async def _schema(db):
    await db._conn.execute("""CREATE TABLE IF NOT EXISTS rpg_achievements (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, achievement_id TEXT NOT NULL,
        unlocked_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id,user_id,achievement_id))""")
    await db._conn.commit()

async def unlock(db, guild_id, user_id, achievement_id):
    import time
    await _schema(db)
    achievement = ACHIEVEMENTS.get(str(achievement_id))
    if not achievement:
        return False
    cur = await db._conn.execute(
        "SELECT 1 FROM rpg_achievements WHERE guild_id=? AND user_id=? AND achievement_id=?",
        (str(guild_id),str(user_id),str(achievement_id)))
    if await cur.fetchone():
        return False
    await db._conn.execute(
        "INSERT INTO rpg_achievements VALUES (?,?,?,?)",
        (str(guild_id),str(user_id),str(achievement_id),time.time()))
    reward = int(achievement[3])
    if reward:
        player = await db.get_rpg_player(guild_id,user_id)
        await db.update_rpg_player(guild_id,user_id,gold=int(player["gold"])+reward)
    await db._conn.commit()
    return True

async def check(db, guild_id, user_id):
    from .gathering import collections
    from .dungeons import status
    await _schema(db)
    cur = await db._conn.execute(
        "SELECT achievement_id FROM rpg_achievements WHERE guild_id=? AND user_id=?",
        (str(guild_id),str(user_id)))
    owned={r["achievement_id"] for r in await cur.fetchall()}
    unlocked=[]
    run=await status(db,guild_id,user_id)
    if run and run["status"]=="cleared":
        for a in ("first_delve",):
            if a not in owned and await unlock(db,guild_id,user_id,a): unlocked.append(a)
        if int(run["floor"])>=5 and "deep_5" not in owned and await unlock(db,guild_id,user_id,"deep_5"): unlocked.append("deep_5")
        if int(run["floor"])>=12 and "deep_12" not in owned and await unlock(db,guild_id,user_id,"deep_12"): unlocked.append("deep_12")
    row=await db._conn.execute(
        "SELECT COALESCE(SUM(total_gathered),0) total FROM rpg_gathering WHERE guild_id=? AND user_id=?",
        (str(guild_id),str(user_id)))
    total=int((await row.fetchone())["total"])
    for a,need in (("gather_100",100),("gather_500",500)):
        if total>=need and a not in owned and await unlock(db,guild_id,user_id,a): unlocked.append(a)
    cols=await collections(db,guild_id,user_id)
    for a,need in (("collection_10",10),("collection_20",20)):
        if len(cols)>=need and a not in owned and await unlock(db,guild_id,user_id,a): unlocked.append(a)
    return unlocked

async def list_unlocked(db,guild_id,user_id):
    await _schema(db)
    cur=await db._conn.execute(
        "SELECT achievement_id,unlocked_at FROM rpg_achievements WHERE guild_id=? AND user_id=? ORDER BY unlocked_at",
        (str(guild_id),str(user_id)))
    return [dict(r) for r in await cur.fetchall()]
