"""ECLIPSE RPG hunting progression.

Hunting is a progression layer on top of the persistent PvE combat engine.
It adds monster tiers, scaling, hunt XP, streaks, contracts, and kill records
without creating a second battle system.
"""
import random
import time

from .enemies import ENEMIES
from .world import REGIONS, get_region, START_REGION


HUNT_TIERS = {
    "common": {"icon": "🐾", "label": "Common", "hp": 1.00, "attack": 1.00, "xp": 1.00, "gold": 1.00, "chance": 0.72, "loot_bonus": 0.00},
    "elite": {"icon": "⚔️", "label": "Elite", "hp": 1.45, "attack": 1.22, "xp": 1.65, "gold": 1.55, "chance": 0.20, "loot_bonus": 0.08},
    "rare": {"icon": "💎", "label": "Rare", "hp": 1.90, "attack": 1.38, "xp": 2.35, "gold": 2.15, "chance": 0.065, "loot_bonus": 0.18},
    "champion": {"icon": "👑", "label": "Champion", "hp": 2.60, "attack": 1.62, "xp": 3.50, "gold": 3.20, "chance": 0.015, "loot_bonus": 0.30},
}

HUNT_XP_PER_LEVEL = 500
HUNT_STREAK_BONUS = 0.025
HUNT_STREAK_CAP = 0.50

# Region-specific target progression. The normal battle engine still controls
# actual turns, skills, specials, and defeat state.
REGION_TARGETS = {
    "moonlit_vale": ["shadow_beast", "ironfang_wolf"],
    "whispering_wood": ["shadow_beast", "ironfang_wolf", "hollow_knight"],
    "ashen_crown": ["ironfang_wolf", "hollow_knight", "ash_drake"],
    "starfall_coast": ["hollow_knight", "ash_drake"],
}


async def ensure_schema(db):
    await db._conn.executescript("""
    CREATE TABLE IF NOT EXISTS rpg_hunt_profiles (
        guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        hunt_level INTEGER NOT NULL DEFAULT 1,
        hunt_xp INTEGER NOT NULL DEFAULT 0,
        total_kills INTEGER NOT NULL DEFAULT 0,
        streak INTEGER NOT NULL DEFAULT 0,
        best_streak INTEGER NOT NULL DEFAULT 0,
        total_gold INTEGER NOT NULL DEFAULT 0,
        total_xp INTEGER NOT NULL DEFAULT 0,
        last_hunt REAL,
        PRIMARY KEY (guild_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS rpg_hunt_records (
        guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        kill_id INTEGER PRIMARY KEY AUTOINCREMENT,
        enemy_id TEXT NOT NULL,
        enemy_name TEXT NOT NULL,
        tier TEXT NOT NULL,
        monster_level INTEGER NOT NULL,
        xp INTEGER NOT NULL DEFAULT 0,
        gold INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    );
    """)
    await db._conn.commit()


async def get_profile(db, guild_id, user_id):
    await ensure_schema(db)
    await db._conn.execute(
        "INSERT OR IGNORE INTO rpg_hunt_profiles(guild_id,user_id) VALUES(?,?)",
        (str(guild_id), str(user_id)),
    )
    await db._conn.commit()
    cur = await db._conn.execute(
        "SELECT * FROM rpg_hunt_profiles WHERE guild_id=? AND user_id=?",
        (str(guild_id), str(user_id)),
    )
    return dict(await cur.fetchone())


def _tier_roll(rng=None):
    rng = rng or random.random()
    cursor = 0.0
    for tier, data in HUNT_TIERS.items():
        cursor += data["chance"]
        if rng <= cursor:
            return tier
    return "common"


def _monster_level(player_level, danger, tier):
    base = max(1, int(player_level) + max(0, int(danger) - 1) * 2)
    return base + {"common": 0, "elite": 1, "rare": 2, "champion": 4}[tier]


def build_hunt_target(enemy_id, player_level, region_id, tier=None, hunt_level=1):
    base = ENEMIES.get(str(enemy_id))
    if not base:
        return None
    region = get_region(region_id) or REGIONS[START_REGION]
    tier = tier or _tier_roll()
    tier_data = HUNT_TIERS[tier]
    level = _monster_level(player_level, region["danger"], tier) + max(0, int(hunt_level) - 1) // 5

    # Small level scaling prevents late-game hunts from becoming irrelevant
    # while keeping the original enemy identities and loot IDs intact.
    level_scale = 1.0 + max(0, level - 1) * 0.045
    hp = max(1, int(base["hp"] * tier_data["hp"] * level_scale))
    attack = max(1, int(base["attack"] * tier_data["attack"] * (1.0 + max(0, level - 1) * 0.025)))
    name = base["name"] if tier == "common" else f"{tier_data['label']} {base['name']}"

    return {
        "id": str(enemy_id),
        "name": name,
        "base_name": base["name"],
        "hp": hp,
        "attack": attack,
        "xp": max(1, int(base["xp"] * tier_data["xp"] * (1.0 + level * 0.02))),
        "gold": max(1, int(base["gold"] * tier_data["gold"] * (1.0 + level * 0.015))),
        "tier": tier,
        "monster_level": level,
        "icon": tier_data["icon"],
        "region": region["name"],
    }



async def board(db, guild_id, user_id):
    player = await db.get_rpg_player(guild_id, user_id)
    profile = await get_profile(db, guild_id, user_id)
    region_id = player.get("region") or START_REGION
    region = get_region(region_id) or REGIONS[START_REGION]
    targets = REGION_TARGETS.get(region_id, region.get("enemies", []))
    contracts = []
    for index in range(4):
        enemy_id = targets[index % len(targets)]
        tier = ("common", "elite", "rare", "champion")[index]
        target = build_hunt_target(enemy_id, player["level"], region_id, tier, profile["hunt_level"])
        if target:
            target["contract_id"] = f"{enemy_id}:{tier}"
            target["contract_reward_xp"] = int(target["xp"] * 0.35)
            target["contract_reward_gold"] = int(target["gold"] * 0.40)
            contracts.append(target)
    return {"profile": profile, "region": region, "contracts": contracts}


async def start_hunt(db, guild_id, user_id, target_id=None):
    profile = await get_profile(db, guild_id, user_id)
    player = await db.get_rpg_player(guild_id, user_id)
    region_id = player.get("region") or START_REGION
    region = get_region(region_id) or REGIONS[START_REGION]

    existing = await db.get_rpg_battle(guild_id, user_id)
    if existing:
        return {"ok": False, "battle": existing, "message": "You already have an active hunt."}

    targets = REGION_TARGETS.get(region_id, region.get("enemies", []))
    if not targets:
        return {"ok": False, "message": "No hunt targets are available in this realm."}

    if target_id:
        target_id = str(target_id).lower()
        # Accept base enemy IDs and contract IDs like ash_drake:elite.
        parts = target_id.split(":", 1)
        enemy_id = parts[0]
        requested_tier = parts[1] if len(parts) > 1 else None
        if enemy_id not in targets:
            return {"ok": False, "message": "That monster is not native to your current realm."}
        tier = requested_tier if requested_tier in HUNT_TIERS else "common"
    else:
        enemy_id = random.choice(targets)
        tier = _tier_roll()

    target = build_hunt_target(enemy_id, player["level"], region_id, tier, profile["hunt_level"])
    target["hunt_profile_level"] = profile["hunt_level"]
    target["streak"] = profile["streak"]

    await db.set_rpg_hunt_active(
        guild_id,
        user_id,
        enemy_id=enemy_id,
        tier=tier,
        monster_level=target["monster_level"],
        started_at=time.time(),
    )
    return {"ok": True, "target": target, "profile": profile, "region": region}


async def complete_hunt(db, guild_id, user_id, enemy_id, base_xp, base_gold):
    active = await db.get_rpg_hunt_active(guild_id, user_id)
    if not active:
        return {"active": False}

    profile = await get_profile(db, guild_id, user_id)
    tier = active["tier"]
    tier_data = HUNT_TIERS.get(tier, HUNT_TIERS["common"])
    streak = int(profile["streak"]) + 1
    streak_bonus = min(HUNT_STREAK_CAP, max(0, streak - 1) * HUNT_STREAK_BONUS)
    bonus_xp = int(base_xp * (0.20 + streak_bonus))
    bonus_gold = int(base_gold * (0.15 + streak_bonus))

    total_hunt_xp = int(profile["hunt_xp"]) + bonus_xp
    old_hunt_level = int(profile["hunt_level"])
    level = old_hunt_level
    level_ups = 0
    while total_hunt_xp >= level * HUNT_XP_PER_LEVEL:
        total_hunt_xp -= level * HUNT_XP_PER_LEVEL
        level += 1
        level_ups += 1

    level_reward_gold = sum(100 * new_level for new_level in range(old_hunt_level + 1, level + 1))
    if level_reward_gold:
        player = await db.get_rpg_player(guild_id, user_id)
        await db.update_rpg_player(
            guild_id, user_id, gold=int(player["gold"]) + level_reward_gold
        )

    await db._conn.execute(
        """UPDATE rpg_hunt_profiles
           SET hunt_level=?, hunt_xp=?, total_kills=total_kills+1,
               streak=?, best_streak=MAX(best_streak,?),
               total_gold=total_gold+?, total_xp=total_xp+?, last_hunt=?
           WHERE guild_id=? AND user_id=?""",
        (
            level, total_hunt_xp, streak, streak,
            bonus_gold, bonus_xp, time.time(),
            str(guild_id), str(user_id),
        ),
    )
    await db._conn.execute(
        """INSERT INTO rpg_hunt_records
           (guild_id,user_id,enemy_id,enemy_name,tier,monster_level,xp,gold,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            str(guild_id), str(user_id), enemy_id, active["enemy_name"],
            tier, int(active["monster_level"]), bonus_xp, bonus_gold, time.time(),
        ),
    )
    await db._conn.commit()
    await db.delete_rpg_hunt_active(guild_id, user_id)

    return {
        "active": True,
        "tier": tier,
        "tier_icon": tier_data["icon"],
        "streak": streak,
        "streak_bonus": streak_bonus,
        "hunt_xp": bonus_xp,
        "hunt_gold": bonus_gold,
        "hunt_level": level,
        "hunt_xp_current": total_hunt_xp,
        "hunt_level_ups": level_ups,
        "level_reward_gold": level_reward_gold,
    }


async def break_hunt_streak(db, guild_id, user_id):
    await get_profile(db, guild_id, user_id)
    await db._conn.execute(
        "UPDATE rpg_hunt_profiles SET streak=0 WHERE guild_id=? AND user_id=?",
        (str(guild_id), str(user_id)),
    )
    await db._conn.commit()


async def recent_kills(db, guild_id, user_id, limit=8):
    await ensure_schema(db)
    cur = await db._conn.execute(
        "SELECT * FROM rpg_hunt_records WHERE guild_id=? AND user_id=? ORDER BY kill_id DESC LIMIT ?",
        (str(guild_id), str(user_id), int(limit)),
    )
    return [dict(r) for r in await cur.fetchall()]
