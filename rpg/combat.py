"""Persistent PvE combat engine with skills, equipment, and special moves."""
import json
import random
import time

from .enemies import random_enemy
from .skills import get_skill
from .specials import get_special, available_specials, can_use_special
from .loot import roll_loot, describe
from .quests import progress as quest_progress
from .world import REGIONS, get_region
from .equipment import equipment_stats
from .crafting import MATERIALS
from .items import get_item
from .hunting import complete_hunt


def _json_loads(value, fallback):
    try:
        data = json.loads(value or "")
        return data if isinstance(data, dict) else fallback.copy()
    except (TypeError, ValueError):
        return fallback.copy()


async def _effective_stats(db, guild_id, user_id, player=None):
    player = player or await db.get_rpg_player(guild_id, user_id)
    gear = await equipment_stats(db, guild_id, user_id)
    return player, gear, {
        "strength": int(player["strength"]) + gear["strength"],
        "defense": int(player["defense"]) + gear["defense"],
        "magic": int(player["magic"]) + gear["magic"],
        "agility": int(player["agility"]) + gear["agility"],
        "max_hp": int(player["max_hp"]) + gear["max_hp"],
        "max_mp": int(player["max_mp"]) + gear["max_mp"],
        "power": gear["power"],
    }


async def _sync_special_unlocks(db, guild_id, user_id, player):
    for special_id, _data in available_specials(player["class_key"], player["level"]):
        if await db.is_rpg_special_revoked(guild_id, user_id, special_id):
            continue
        if not await db.has_rpg_special(guild_id, user_id, special_id):
            await db.unlock_rpg_special(guild_id, user_id, special_id, source="level")


def _status_text(effects):
    bits = []
    if effects.get("enemy_freeze_turns", 0):
        bits.append(f"❄️ frozen {effects['enemy_freeze_turns']}t")
    if effects.get("enemy_burn_turns", 0):
        bits.append(f"🔥 burning {effects['enemy_burn_turns']}t")
    if effects.get("enemy_weaken_turns", 0):
        bits.append(f"🕸️ weakened {effects['enemy_weaken_turns']}t")
    if effects.get("enemy_stagger_turns", 0):
        bits.append("⚡ staggered")
    if effects.get("player_guard_turns", 0):
        bits.append(f"🛡️ guard {effects['player_guard_turns']}t")
    if effects.get("player_blessing_turns", 0):
        bits.append(f"☀️ blessed {effects['player_blessing_turns']}t")
    if effects.get("player_bloom_turns", 0):
        bits.append(f"🌸 bloom {effects['player_bloom_turns']}t")
    if effects.get("player_evasion_turns", 0):
        bits.append(f"🫥 evasion {effects['player_evasion_turns']}t")
    return " · ".join(bits)


async def start(db, guild_id, user_id, enemy_override=None, hunt_mode=False):
    existing = await db.get_rpg_battle(guild_id, user_id)
    if existing:
        return {"ok": False, "battle": existing}
    if not hunt_mode and await db.get_rpg_hunt_active(guild_id, user_id):
        return {"ok": False, "message": "A monster hunt is already prepared. Finish or cancel the hunt first."}

    player = await db.get_rpg_player(guild_id, user_id)
    now = time.time()
    travel_until = float(player.get("travel_until") or 0)
    if travel_until > now:
        return {"ok": False, "message": f"You are still traveling. {travel_until - now:.0f}s remain."}
    try:
        from .dungeons import _get_run
        dungeon_run = await _get_run(db, guild_id, user_id)
        if dungeon_run and dungeon_run.get("status") == "active":
            return {"ok": False, "message": "You are inside an active dungeon. Advance or retreat before starting another battle."}
    except Exception:
        pass
    await _sync_special_unlocks(db, guild_id, user_id, player)
    enemy = enemy_override or random_enemy(player.get("region"))
    await db.set_rpg_battle(
        guild_id,
        user_id,
        enemy_id=enemy["id"],
        enemy_name=enemy["name"],
        enemy_hp=enemy["hp"],
        enemy_max_hp=enemy["hp"],
        enemy_attack=enemy["attack"],
        turn=1,
        guarding=0,
        effects="{}",
        special_cooldowns="{}",
        created_at=time.time(),
    )
    return {
        "ok": True,
        "battle": await db.get_rpg_battle(guild_id, user_id),
        "player": player,
        "hunt": hunt_result,
    }


def ENEMIES_REWARD(enemy_id, field):
    from .enemies import ENEMIES
    return ENEMIES[enemy_id][field]


async def _victory_rewards(db, guild_id, user_id, battle, player, damage):
    hunt_active = await db.get_rpg_hunt_active(guild_id, user_id)
    await db.delete_rpg_battle(guild_id, user_id)

    # Hunting variants use their scaled reward values; ordinary battles keep
    # the original enemy table rewards.
    if hunt_active:
        from .hunting import HUNT_TIERS, build_hunt_target
        region_id = player.get("region")
        scaled = build_hunt_target(
            battle["enemy_id"],
            player["level"],
            region_id,
            hunt_active.get("tier", "common"),
        )
        xp_reward = int(scaled["xp"]) if scaled else ENEMIES_REWARD(battle["enemy_id"], "xp")
        gold_reward = int(scaled["gold"]) if scaled else ENEMIES_REWARD(battle["enemy_id"], "gold")
        display_enemy_name = hunt_active.get("enemy_name") or battle["enemy_name"]
    else:
        xp_reward = ENEMIES_REWARD(battle["enemy_id"], "xp")
        gold_reward = ENEMIES_REWARD(battle["enemy_id"], "gold")
        display_enemy_name = battle["enemy_name"]
    old, new, player = await db.add_rpg_xp(guild_id, user_id, xp_reward)
    level_count = max(0, int(new) - int(old))
    hp_gain = level_count * 12
    mp_gain = level_count * 4
    player = await db.update_rpg_player(
        guild_id, user_id, gold=player["gold"] + gold_reward
    )

    region = get_region(player.get("region")) or REGIONS["moonlit_vale"]
    loot_bonus = float(region.get("loot_bonus", 0))
    if hunt_active:
        from .hunting import HUNT_TIERS
        loot_bonus += float(HUNT_TIERS.get(hunt_active.get("tier", "common"), HUNT_TIERS["common"]).get("loot_bonus", 0))
    loot = roll_loot(battle["enemy_id"], loot_bonus)
    guardian_regions = {
        r.get("guardian"): rid for rid, r in REGIONS.items() if r.get("guardian")
    }
    if battle["enemy_id"] in guardian_regions:
        await db.defeat_rpg_guardian(
            guild_id, guardian_regions[battle["enemy_id"]], user_id
        )
    if loot:
        await db.add_rpg_item(guild_id, user_id, loot, 1)
        loot_item = get_item(loot)
        if loot_item and loot_item.get("rarity") in {"rare", "epic", "legendary", "relic"}:
            from .expansion import assign_affixes
            await assign_affixes(db, guild_id, user_id, loot)

    region_materials = {
        "moonlit_vale": "moon_petal",
        "whispering_wood": "thorn_fiber",
        "ashen_crown": "ash_core",
        "starfall_coast": "star_fragment",
    }
    material_id = region_materials.get(region.get("id")) if region.get("id") else None
    if not material_id:
        for rid, data in REGIONS.items():
            if data.get("name") == region.get("name"):
                material_id = region_materials.get(rid)
                break
    material_gain = random.randint(1, 2) + (
        1 if battle["enemy_id"] in guardian_regions else 0
    )
    if material_id and material_id in MATERIALS:
        await db.add_rpg_material(
            guild_id, user_id, material_id, material_gain
        )
    if battle["enemy_id"] in guardian_regions:
        await db.add_rpg_material(guild_id, user_id, "guardian_essence", 3)

    hunt_result = await complete_hunt(
        db, guild_id, user_id, battle["enemy_id"], xp_reward, gold_reward
    )

    await quest_progress(
        db, guild_id, user_id, "kills", 1, battle["enemy_id"]
    )
    return {
        "ok": True,
        "victory": True,
        "defeated": True,
        "status": "defeated",
        "enemy_id": battle["enemy_id"],
        "enemy_name": display_enemy_name,
        "damage": damage,
        "xp": xp_reward,
        "gold": gold_reward,
        "loot": loot,
        "loot_name": describe(loot) if loot else None,
        "level_up": new > old,
        "old_level": old,
        "new_level": new,
        "level_count": level_count,
        "hp_gain": hp_gain,
        "mp_gain": mp_gain,
        "player": player,
        "hunt": hunt_result,
    }


async def _finish_turn(db, guild_id, user_id, battle, player, stats, effects, cooldowns, damage, special=False):
    enemy_hp = max(0, int(battle["enemy_hp"]) - int(damage))
    if enemy_hp <= 0:
        battle = dict(battle)
        battle["enemy_hp"] = enemy_hp
        return await _victory_rewards(db, guild_id, user_id, battle, player, damage)

    # Enemy-control effects are consumed by the enemy turn, not by the player's
    # cast. Infinite Darkness therefore preserves the original five-move freeze.
    frozen = int(effects.get("enemy_freeze_turns", 0))
    staggered = int(effects.get("enemy_stagger_turns", 0))
    enemy_skipped = frozen > 0 or staggered > 0

    incoming = 0
    if not enemy_skipped:
        incoming = max(1, int(battle["enemy_attack"] - stats["defense"] * 0.45))
        if effects.get("enemy_weaken_turns", 0):
            incoming = max(1, int(incoming * (1.0 - float(effects.get("enemy_weaken_pct", 0.25)))))

        if effects.get("player_blessing_turns", 0):
            incoming = max(1, int(incoming * 0.65))

        if effects.get("player_guard_turns", 0):
            incoming = max(1, int(incoming * 0.45))

        evasion_chance = min(0.35, stats["agility"] * 0.01)
        if effects.get("player_evasion_turns", 0):
            evasion_chance = max(evasion_chance, 0.70)
        if random.random() < evasion_chance:
            incoming = 0

    hp = max(0, int(player["hp"]) - incoming)
    await db.update_rpg_player(guild_id, user_id, hp=hp)

    if hp <= 0:
        await db.delete_rpg_battle(guild_id, user_id)
        hunt_active = await db.get_rpg_hunt_active(guild_id, user_id)
        if hunt_active:
            from .hunting import break_hunt_streak
            await db.delete_rpg_hunt_active(guild_id, user_id)
            await break_hunt_streak(db, guild_id, user_id)
        return {
            "ok": True,
            "defeat": True,
            "damage": damage,
            "incoming": incoming,
            "special": special,
        }

    if frozen > 0:
        effects["enemy_freeze_turns"] = frozen - 1
    elif staggered > 0:
        effects["enemy_stagger_turns"] = staggered - 1

    # Player-side duration ticks happen after the turn resolves.
    for key in ("player_guard_turns", "player_blessing_turns", "player_bloom_turns", "player_evasion_turns"):
        if effects.get(key, 0) > 0:
            effects[key] = max(0, int(effects[key]) - 1)

    if effects.get("enemy_burn_turns", 0) > 0:
        effects["enemy_burn_turns"] = max(0, int(effects["enemy_burn_turns"]) - 1)
    if effects.get("enemy_weaken_turns", 0) > 0:
        effects["enemy_weaken_turns"] = max(0, int(effects["enemy_weaken_turns"]) - 1)

    new_player = await db.get_rpg_player(guild_id, user_id)
    if effects.get("player_bloom_turns", 0) > 0:
        heal = max(4, int(stats["magic"] * 0.75))
        mp_gain = max(2, int(stats["magic"] * 0.18))
        new_player = await db.update_rpg_player(
            guild_id,
            user_id,
            hp=min(stats["max_hp"], int(new_player["hp"]) + heal),
            mp=min(stats["max_mp"], int(new_player["mp"]) + mp_gain),
        )
    elif effects.get("player_blessing_turns", 0) > 0:
        heal = max(2, int(stats["magic"] * 0.35))
        new_player = await db.update_rpg_player(
            guild_id,
            user_id,
            hp=min(stats["max_hp"], int(new_player["hp"]) + heal),
        )

    await db.set_rpg_battle(
        guild_id,
        user_id,
        enemy_hp=enemy_hp,
        turn=int(battle["turn"]) + 1,
        guarding=1 if effects.get("player_guard_turns", 0) else 0,
        effects=json.dumps(effects, separators=(",", ":")),
        special_cooldowns=json.dumps(cooldowns, separators=(",", ":")),
    )
    return {
        "ok": True,
        "victory": False,
        "damage": damage,
        "incoming": 0 if enemy_skipped else incoming,
        "enemy_skipped": enemy_skipped,
        "enemy_hp": enemy_hp,
        "enemy_max_hp": battle["enemy_max_hp"],
        "player": new_player,
        "effects": effects,
        "status": _status_text(effects),
        "special": special,
    }


async def attack(db, guild_id, user_id, skill_id=None):
    battle = await db.get_rpg_battle(guild_id, user_id)
    if not battle:
        return {"ok": False, "message": "No active battle."}

    player, gear, stats = await _effective_stats(db, guild_id, user_id)
    effects = _json_loads(battle.get("effects"), {})
    cooldowns = {
        key: max(0, int(value) - 1)
        for key, value in _json_loads(battle.get("special_cooldowns"), {}).items()
        if int(value) > 0
    }
    skill_cooldowns = {
        key: max(0, int(value) - 1)
        for key, value in _json_loads(effects.get("skill_cooldowns"), {}).items()
        if int(value) > 0
    }
    effects["skill_cooldowns"] = skill_cooldowns

    # Passive damage-over-time is applied before the player's next action.
    opening_damage = 0
    if effects.get("enemy_burn_turns", 0):
        opening_damage = max(1, int(effects.get("enemy_burn_damage", 1)))
        battle["enemy_hp"] = max(0, int(battle["enemy_hp"]) - opening_damage)
        if battle["enemy_hp"] <= 0:
            return await _victory_rewards(
                db, guild_id, user_id, battle, player, opening_damage
            )

    damage = max(
        1,
        int(
            (stats["strength"] + gear["power"])
            * random.uniform(0.85, 1.15)
            - int(battle["turn"]) * 0.15
        ),
    )
    mp_cost = 0

    if skill_id:
        skill = get_skill(player["class_key"], skill_id)
        owned = await db.get_rpg_skills(guild_id, user_id)
        if not skill or skill["id"] not in owned:
            return {"ok": False, "message": "That skill is not unlocked for you."}
        if int(player["level"]) < int(skill.get("level", 1)):
            return {"ok": False, "message": f"{skill['name']} unlocks at RPG level {skill.get('level', 1)}."}
        remaining = int(skill_cooldowns.get(skill["id"], 0))
        if remaining > 0:
            return {"ok": False, "message": f"{skill['name']} is cooling down for {remaining} turn(s)."}
        if player["mp"] < skill["cost"]:
            return {"ok": False, "message": f"Not enough MP. Need {skill['cost']}."}
        mp_cost = skill["cost"]
        if skill["kind"] in ("magic", "holy"):
            damage = max(1, int(stats["magic"] * skill["power"] + gear["power"] * 0.5))
        else:
            damage = max(1, int((stats["strength"] + gear["power"]) * skill["power"]))

        if skill["kind"] == "guard":
            effects["player_guard_turns"] = max(2, int(effects.get("player_guard_turns", 0)))
        elif skill["kind"] == "restore":
            player = await db.update_rpg_player(
                guild_id, user_id,
                mp=min(stats["max_mp"], int(player["mp"]) - mp_cost + max(8, int(stats["magic"] * 0.55)))
            )
            mp_cost = 0
        elif skill["kind"] == "evasion":
            effects["player_evasion_turns"] = max(2, int(effects.get("player_evasion_turns", 0)))
        elif skill["kind"] == "buff":
            damage = int(damage * 1.25)

        skill_cd = int(skill.get("cooldown", 0))
        if skill_cd > 0:
            skill_cooldowns[skill["id"]] = skill_cd

    player = await db.update_rpg_player(
        guild_id, user_id, mp=max(0, int(player["mp"]) - mp_cost)
    )
    result = await _finish_turn(
        db, guild_id, user_id, battle, player, stats, effects, cooldowns,
        damage, special=False
    )
    if opening_damage:
        result["damage"] += opening_damage
    return result


async def special(db, guild_id, user_id, special_id):
    battle = await db.get_rpg_battle(guild_id, user_id)
    if not battle:
        return {"ok": False, "message": "No active battle."}

    player, gear, stats = await _effective_stats(db, guild_id, user_id)
    await _sync_special_unlocks(db, guild_id, user_id, player)

    sid = str(special_id).strip().lower()
    data = get_special(sid)
    if not data:
        return {"ok": False, "message": "Unknown special."}

    unlocked = await db.has_rpg_special(guild_id, user_id, sid)
    class_allowed = can_use_special(player["class_key"], sid)
    if not class_allowed and not unlocked:
        return {"ok": False, "message": "That special is not part of your class path and has not been granted to you."}
    if not unlocked:
        return {
            "ok": False,
            "message": f"**{data['name']}** unlocks at level **{data['level']}** for its normal class path, or can be granted through a special access unlock.",
        }

    effects = _json_loads(battle.get("effects"), {})
    cooldowns = {
        key: max(0, int(value) - 1)
        for key, value in _json_loads(battle.get("special_cooldowns"), {}).items()
        if int(value) > 0
    }
    remaining = int(cooldowns.get(sid, 0))
    if remaining > 0:
        return {
            "ok": False,
            "message": f"**{data['name']}** is still cooling down for **{remaining}** turn(s).",
        }
    if int(player["mp"]) < int(data["cost"]):
        return {
            "ok": False,
            "message": f"Not enough MP. **{data['name']}** needs **{data['cost']} MP**.",
        }

    enemy_hp = int(battle["enemy_hp"])
    damage = 0
    message = data["description"]
    kind = data["kind"]

    if kind == "ice_wall":
        damage = max(1, int((stats["strength"] + gear["power"]) * data["power"]))
        effects["player_guard_turns"] = 2
        effects["enemy_stagger_turns"] = max(1, int(effects.get("enemy_stagger_turns", 0)))
        message = "The heavens crystallize. An ice wall rises around you."
    elif kind == "burn":
        damage = max(1, int(stats["magic"] * data["power"] + gear["power"]))
        effects["enemy_burn_turns"] = 3
        effects["enemy_burn_damage"] = max(3, int(stats["magic"] * 0.35))
        message = "A blazing garden takes root beneath the enemy."
    elif kind == "freeze":
        damage = max(1, int(stats["magic"] * data["power"] + stats["agility"] * 0.25))
        effects["enemy_freeze_turns"] = int(data["duration"])
        message = "Darkness closes over the enemy. It is frozen for five moves."
    elif kind == "holy":
        damage = max(1, int(stats["magic"] * data["power"] + stats["strength"] * 0.65))
        message = "Judgement descends from above."
    elif kind == "blessing":
        heal = max(12, int(stats["magic"] * 1.7))
        player = await db.update_rpg_player(
            guild_id, user_id,
            hp=min(stats["max_hp"], int(player["hp"]) + heal),
        )
        effects["player_blessing_turns"] = 3
        message = f"Amaterasu answers. You recover **{heal} HP** and gain radiant protection."
    elif kind == "reaver":
        damage = max(1, int((stats["strength"] + gear["power"]) * data["power"]))
        heal = max(1, int(damage * 0.35))
        player = await db.update_rpg_player(
            guild_id, user_id,
            hp=min(stats["max_hp"], int(player["hp"]) + heal),
        )
        message = f"Blood answers blood. You recover **{heal} HP**."
    elif kind == "bloom":
        heal = max(16, int(stats["magic"] * 1.9))
        player = await db.update_rpg_player(
            guild_id, user_id,
            hp=min(stats["max_hp"], int(player["hp"]) + heal),
        )
        effects["player_bloom_turns"] = 4
        message = f"The world blooms around you. You recover **{heal} HP**."
    elif kind == "overdrive":
        damage = max(1, int(stats["magic"] * data["power"] + gear["power"] * 1.5))
        message = "Your arcane core overloads the battlefield."
    elif kind == "fallen":
        base = max(1, int((stats["strength"] + gear["power"]) * data["power"]))
        damage = int(base * random.uniform(1.05, 1.25))
        message = "The fallen rise and strike as one."
    elif kind == "thunder":
        damage = max(1, int(stats["magic"] * data["power"] + stats["strength"] * 0.35))
        if random.random() < 0.65:
            effects["enemy_stagger_turns"] = max(1, int(effects.get("enemy_stagger_turns", 0)))
            message = "Celestial thunder crashes down and staggers the enemy."
        else:
            message = "Celestial thunder crashes down."
    elif kind == "abyss":
        damage = max(1, int((stats["strength"] + stats["magic"] * 0.45) * data["power"]))
        effects["enemy_weaken_turns"] = 3
        effects["enemy_weaken_pct"] = 0.30
        message = "The abyssal tide recedes, leaving the enemy weakened."
    elif kind == "tempest":
        damage = max(1, int(stats["magic"] * data["power"] + stats["agility"] * 0.5))
        if random.random() < 0.55:
            effects["enemy_stagger_turns"] = 1
        message = "A celestial tempest tears across the realm."
    elif kind == "worldbreaker":
        damage = max(1, int((stats["strength"] + gear["power"]) * data["power"]))
        if random.random() < 0.35:
            effects["enemy_stagger_turns"] = 1
        message = "The battlefield fractures beneath Worldbreaker's force."

    player = await db.update_rpg_player(
        guild_id, user_id, mp=int(player["mp"]) - int(data["cost"])
    )
    cooldowns[sid] = int(data["cooldown"])

    result = await _finish_turn(
        db, guild_id, user_id, battle, player, stats, effects, cooldowns,
        damage, special=True
    )
    result["special_id"] = sid
    result["special_name"] = data["name"]
    result["special_icon"] = data["icon"]
    result["special_message"] = message
    result["status"] = _status_text(result.get("effects", effects))
    return result


async def flee(db, guild_id, user_id):
    battle = await db.get_rpg_battle(guild_id, user_id)
    if not battle:
        return False
    await db.delete_rpg_battle(guild_id, user_id)
    hunt_active = await db.get_rpg_hunt_active(guild_id, user_id)
    if hunt_active:
        from .hunting import break_hunt_streak
        await db.delete_rpg_hunt_active(guild_id, user_id)
        await break_hunt_streak(db, guild_id, user_id)
    return True
