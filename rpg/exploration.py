"""Exploration/travel service for the ECLIPSE fantasy world."""
import random
import time
from .world import REGIONS, START_REGION, get_region, random_region_event
from .enemies import ENEMIES

TRAVEL_LOCK_SECONDS = 15

async def world_status(db, guild_id):
    return await db.get_rpg_world(guild_id)

async def travel(db, guild_id, user_id, region_id):
    target = get_region(region_id)
    if target is None:
        return {"ok":False,"message":"That realm does not exist."}
    player = await db.get_rpg_player(guild_id,user_id)
    now = time.time()
    travel_until = float(player.get("travel_until") or 0)
    if travel_until > now:
        return {"ok":False,"message":f"You are still traveling. **{travel_until-now:.0f}s** remain."}
    current = get_region(player.get("region") or START_REGION)
    if current and current["name"] == target["name"]:
        return {"ok":False,"message":f"You are already in **{target['name']}**."}
    distance = abs(target["danger"]-(current["danger"] if current else 1))
    duration = TRAVEL_LOCK_SECONDS+target["travel"]+distance*5
    await db.update_rpg_player(guild_id,user_id,region=region_id,travel_until=now+duration)
    return {"ok":True,"region":target,"duration":duration,"from":current}

async def explore(db, guild_id, user_id):
    player = await db.get_rpg_player(guild_id,user_id)
    now = time.time()
    travel_until = float(player.get("travel_until") or 0)
    if travel_until > now:
        return {"ok":False,"message":f"You cannot explore while traveling. **{travel_until-now:.0f}s** remain."}
    region_id = player.get("region") or START_REGION
    region = get_region(region_id) or REGIONS[START_REGION]
    world = await db.get_rpg_world(guild_id)
    encounter_chance = 0.22+(region["danger"]*0.07)+(int(world["instability"])*0.01)
    if random.random() < encounter_chance:
        enemy_id = random.choice(region["enemies"])
        enemy = ENEMIES[enemy_id].copy()
        enemy["id"] = enemy_id
        scale = 1+max(0,region["danger"]-1)*0.08
        enemy["hp"] = int(enemy["hp"]*scale)
        enemy["attack"] = int(enemy["attack"]*scale)
        enemy["xp"] = int(enemy["xp"]*scale)
        enemy["gold"] = int(enemy["gold"]*scale)
        return {"ok":True,"kind":"enemy","region":region,"enemy":enemy,"world":world}
    event = random_region_event(region_id)
    old_level,new_level,player = await db.add_rpg_xp(guild_id,user_id,event["xp"])
    player = await db.update_rpg_player(guild_id,user_id,gold=max(0,int(player["gold"])+event["gold"]))
    await db.advance_rpg_world(guild_id)
    return {"ok":True,"kind":"event","region":region,"event":event,"old_level":old_level,"new_level":new_level,"player":player,"world":await db.get_rpg_world(guild_id)}
