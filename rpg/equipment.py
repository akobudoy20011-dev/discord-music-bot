"""Persistent RPG equipment service.

The original rpg_items table remains the inventory source of truth.  A
small dedicated rpg_equipment table stores one equipped item per slot and
its upgrade level, preserving compatibility with existing inventories.
"""

from .items import get_item, rarity_multiplier

EQUIPMENT_SLOTS = ("weapon", "armor", "accessory", "relic")

STARTER_WEAPONS = {
    "knight": "iron_sword",
    "arcanist": "moon_staff",
    "wraith": "shadow_dagger",
    "paladin": "iron_sword",
    "bloodreaver": "shadow_dagger",
}

async def _ensure_schema(db):
    await db._conn.execute("""
        CREATE TABLE IF NOT EXISTS rpg_equipment (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            item_id TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, user_id, slot)
        )
    """)
    await db._conn.commit()

async def grant_starter_gear(db, guild_id, user_id, class_key):
    await _ensure_schema(db)
    weapon = STARTER_WEAPONS.get(str(class_key).lower(), "iron_sword")
    items = await db.get_rpg_items(guild_id, user_id)
    if not any(x["item_id"] == weapon for x in items):
        await db.add_rpg_item(guild_id, user_id, weapon, 1)
    current = await get_equipment(db, guild_id, user_id)
    if "weapon" not in current:
        await equip(db, guild_id, user_id, weapon)
    return await db.get_rpg_items(guild_id, user_id)

async def get_equipment(db, guild_id, user_id):
    await _ensure_schema(db)
    cur = await db._conn.execute(
        "SELECT slot, item_id, level FROM rpg_equipment "
        "WHERE guild_id=? AND user_id=? ORDER BY slot",
        (str(guild_id), str(user_id)),
    )
    rows = await cur.fetchall()
    return [dict(row) for row in rows]

async def equipped_map(db, guild_id, user_id):
    return {row["slot"]: row for row in await get_equipment(db, guild_id, user_id)}

async def equip(db, guild_id, user_id, item_id):
    await _ensure_schema(db)
    item_id = str(item_id).lower()
    item = get_item(item_id)
    if not item:
        return {"ok": False, "message": "That item does not exist."}
    owned = await db.get_rpg_items(guild_id, user_id)
    row = next((x for x in owned if x["item_id"] == item_id and x["amount"] > 0), None)
    if not row:
        return {"ok": False, "message": "You do not own that item."}

    slot = item["slot"]
    cur = await db._conn.execute(
        "SELECT item_id, level FROM rpg_equipment "
        "WHERE guild_id=? AND user_id=? AND slot=?",
        (str(guild_id), str(user_id), slot),
    )
    previous = await cur.fetchone()
    level = int(previous["level"]) if previous and previous["item_id"] == item_id else 1

    await db._conn.execute(
        "INSERT INTO rpg_equipment (guild_id,user_id,slot,item_id,level) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(guild_id,user_id,slot) "
        "DO UPDATE SET item_id=excluded.item_id, level=excluded.level",
        (str(guild_id), str(user_id), slot, item_id, level),
    )
    await db._conn.execute(
        "UPDATE rpg_items SET equipped=0 WHERE guild_id=? AND user_id=?",
        (str(guild_id), str(user_id)),
    )
    equipped_rows = await db._conn.execute(
        "SELECT item_id FROM rpg_equipment WHERE guild_id=? AND user_id=?",
        (str(guild_id), str(user_id)),
    )
    for row in await equipped_rows.fetchall():
        await db._conn.execute(
            "UPDATE rpg_items SET equipped=1 WHERE guild_id=? AND user_id=? AND item_id=?",
            (str(guild_id), str(user_id), row["item_id"]),
        )
    await db._conn.commit()
    return {"ok": True, "item": item, "slot": slot, "level": level}

async def unequip(db, guild_id, user_id, slot):
    await _ensure_schema(db)
    slot = str(slot).lower()
    if slot not in EQUIPMENT_SLOTS:
        return {"ok": False, "message": f"Unknown slot. Use: {', '.join(EQUIPMENT_SLOTS)}."}
    cur = await db._conn.execute(
        "SELECT item_id FROM rpg_equipment WHERE guild_id=? AND user_id=? AND slot=?",
        (str(guild_id), str(user_id), slot),
    )
    row = await cur.fetchone()
    if not row:
        return {"ok": False, "message": f"Nothing is equipped in the {slot} slot."}
    await db._conn.execute(
        "DELETE FROM rpg_equipment WHERE guild_id=? AND user_id=? AND slot=?",
        (str(guild_id), str(user_id), slot),
    )
    await db._conn.execute(
        "UPDATE rpg_items SET equipped=0 WHERE guild_id=? AND user_id=? AND item_id=?",
        (str(guild_id), str(user_id), row["item_id"]),
    )
    await db._conn.commit()
    return {"ok": True, "item_id": row["item_id"], "slot": slot}

async def equipment_stats(db, guild_id, user_id):
    """Return aggregate combat/profile bonuses from equipped gear."""
    totals = {
        "power": 0, "strength": 0, "defense": 0, "magic": 0,
        "agility": 0, "max_hp": 0, "max_mp": 0,
    }
    for row in await get_equipment(db, guild_id, user_id):
        item = get_item(row["item_id"])
        if not item:
            continue
        scale = rarity_multiplier(item) * (1 + max(0, int(row["level"]) - 1) * 0.25)
        for key in totals:
            totals[key] += int(round(float(item.get(key, 0)) * scale))
    return totals

def upgrade_cost(item, level):
    rarity = rarity_multiplier(item)
    return int(100 * max(1, int(level)) * rarity + 50 * max(0, int(level) - 1))

async def upgrade(db, guild_id, user_id, item_id):
    await _ensure_schema(db)
    item_id = str(item_id).lower()
    item = get_item(item_id)
    if not item:
        return {"ok": False, "message": "That item does not exist."}
    cur = await db._conn.execute(
        "SELECT slot, level FROM rpg_equipment WHERE guild_id=? AND user_id=? AND item_id=?",
        (str(guild_id), str(user_id), item_id),
    )
    row = await cur.fetchone()
    if not row:
        return {"ok": False, "message": "Equip the item before upgrading it."}
    level = int(row["level"])
    if level >= 10:
        return {"ok": False, "message": "That item has reached the maximum upgrade level (10)."}
    cost = upgrade_cost(item, level)
    ok, _ = await db.spend_rpg_gold(guild_id, user_id, cost)
    if not ok:
        return {"ok": False, "message": f"You need **{cost:,} RPG gold** to upgrade it."}
    new_level = level + 1
    await db._conn.execute(
        "UPDATE rpg_equipment SET level=? WHERE guild_id=? AND user_id=? AND slot=?",
        (new_level, str(guild_id), str(user_id), row["slot"]),
    )
    await db._conn.commit()
    return {"ok": True, "item": item, "old_level": level, "new_level": new_level, "cost": cost}

async def inventory(db, guild_id, user_id):
    await _ensure_schema(db)
    rows = await db.get_rpg_items(guild_id, user_id)
    equipped = await equipped_map(db, guild_id, user_id)
    for row in rows:
        row["item"] = get_item(row["item_id"])
        row["equipped_level"] = equipped.get(
            row["item"].get("slot") if row.get("item") else "", {}
        ).get("level")
    return rows
