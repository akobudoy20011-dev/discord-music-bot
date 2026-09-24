"""Persistent PvE combat engine with equipment-aware stats."""
import random
import time

from .enemies import random_enemy
from .skills import get_skill
from .loot import roll_loot, describe
from .quests import progress as quest_progress
from .world import REGIONS, get_region
from .equipment import equipment_stats
from .crafting import MATERIALS

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

async def start(db,guild_id,user_id,enemy_override=None):
    existing=await db.get_rpg_battle(guild_id,user_id)
    if existing:
        return {"ok":False,"battle":existing}
    player=await db.get_rpg_player(guild_id,user_id)
    enemy=enemy_override or random_enemy(player.get("region"))
    await db.set_rpg_battle(
        guild_id,user_id,
        enemy_id=enemy["id"], enemy_name=enemy["name"],
        enemy_hp=enemy["hp"], enemy_max_hp=enemy["hp"],
        enemy_attack=enemy["attack"], turn=1, guarding=0,
        created_at=time.time()
    )
    return {"ok":True,"battle":await db.get_rpg_battle(guild_id,user_id),"player":player}

async def attack(db,guild_id,user_id,skill_id=None):
    battle=await db.get_rpg_battle(guild_id,user_id)
    if not battle:
        return {"ok":False,"message":"No active battle."}

    player, gear, stats = await _effective_stats(db,guild_id,user_id)
    damage=max(
        1,
        int(
            (stats["strength"] + gear["power"])
            * random.uniform(.85,1.15)
            - battle["turn"]*.15
        )
    )
    mp_cost=0
    skill=None

    if skill_id:
        skill=get_skill(player["class_key"],skill_id)
        owned=await db.get_rpg_skills(guild_id,user_id)
        if not skill or skill["id"] not in owned:
            return {"ok":False,"message":"That skill is not unlocked for you."}
        if player["mp"]<skill["cost"]:
            return {"ok":False,"message":f"Not enough MP. Need {skill['cost']}."}
        mp_cost=skill["cost"]
        if skill["kind"] in ("magic","holy"):
            damage=max(1,int(stats["magic"]*skill["power"] + gear["power"]*.5))
        else:
            damage=max(1,int((stats["strength"] + gear["power"])*skill["power"]))

    enemy_hp=max(0,battle["enemy_hp"]-damage)
    player=await db.update_rpg_player(
        guild_id,user_id,mp=max(0,player["mp"]-mp_cost)
    )

    if enemy_hp<=0:
        await db.delete_rpg_battle(guild_id,user_id)
        xp_reward=ENEMIES_REWARD(battle["enemy_id"],"xp")
        gold_reward=ENEMIES_REWARD(battle["enemy_id"],"gold")
        old,new,player=await db.add_rpg_xp(guild_id,user_id,xp_reward)
        player=await db.update_rpg_player(
            guild_id,user_id,gold=player["gold"]+gold_reward
        )
        region=get_region(player.get("region")) or REGIONS["moonlit_vale"]
        loot=roll_loot(battle["enemy_id"],region.get("loot_bonus",0))
        guardian_regions={
            r.get("guardian"):rid for rid,r in REGIONS.items() if r.get("guardian")
        }
        if battle["enemy_id"] in guardian_regions:
            await db.defeat_rpg_guardian(
                guild_id,guardian_regions[battle["enemy_id"]],user_id
            )
        if loot:
            await db.add_rpg_item(guild_id,user_id,loot,1)

        # Every victory feeds the crafting economy. Regional materials are
        # common; guardian essence is reserved for realm guardians.
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
        material_gain = random.randint(1, 2) + (1 if battle["enemy_id"] in guardian_regions else 0)
        if material_id and material_id in MATERIALS:
            await db.add_rpg_material(guild_id,user_id,material_id,material_gain)
        if battle["enemy_id"] in guardian_regions:
            await db.add_rpg_material(guild_id,user_id,"guardian_essence",3)

        await quest_progress(
            db,guild_id,user_id,"kills",1,battle["enemy_id"]
        )
        return {
            "ok":True,"victory":True,"damage":damage,
            "xp":xp_reward,"gold":gold_reward,"loot":loot,
            "loot_name":describe(loot) if loot else None,
            "level_up":new>old,"player":player,
        }

    incoming=max(1,int(battle["enemy_attack"]-stats["defense"]*.45))
    if random.random()<min(.35,stats["agility"]*.01):
        incoming=0

    hp=max(0,player["hp"]-incoming)
    await db.update_rpg_player(guild_id,user_id,hp=hp)
    if hp<=0:
        await db.delete_rpg_battle(guild_id,user_id)
        return {
            "ok":True,"defeat":True,"damage":damage,
            "incoming":incoming
        }

    await db.set_rpg_battle(
        guild_id,user_id,enemy_hp=enemy_hp,
        turn=battle["turn"]+1,guarding=0
    )
    return {
        "ok":True,"victory":False,"damage":damage,
        "incoming":incoming,"enemy_hp":enemy_hp,
        "enemy_max_hp":battle["enemy_max_hp"],
        "player":await db.get_rpg_player(guild_id,user_id)
    }

async def flee(db,guild_id,user_id):
    battle=await db.get_rpg_battle(guild_id,user_id)
    if not battle:
        return False
    await db.delete_rpg_battle(guild_id,user_id)
    return True

def ENEMIES_REWARD(enemy_id,field):
    from .enemies import ENEMIES
    return ENEMIES[enemy_id][field]
