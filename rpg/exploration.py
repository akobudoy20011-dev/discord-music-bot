"""Exploration/travel service for the ECLIPSE fantasy world."""
import random
import time
from .world import (
    REGIONS, START_REGION, get_region, random_region_event,
    get_event, get_discovery, roll_world_event, roll_discovery
)
from .enemies import ENEMIES

TRAVEL_LOCK_SECONDS = 15
EVENT_CHANCE = 0.08
DISCOVERY_CHANCE = 0.07
GUARDIAN_CHANCE = 0.035

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

async def _world_event(db,guild_id,world):
    event_id=roll_world_event()
    event=get_event(event_id)
    until=time.time()+event["duration"]
    instability=max(0,min(10,int(world["instability"])+event["instability"]))
    await db.update_rpg_world(
        guild_id,active_event=event_id,event_until=until,
        instability=instability,updated_at=time.time()
    )
    return event

async def explore(db, guild_id, user_id):
    player = await db.get_rpg_player(guild_id,user_id)
    now = time.time()
    travel_until = float(player.get("travel_until") or 0)
    if travel_until > now:
        return {"ok":False,"message":f"You cannot explore while traveling. **{travel_until-now:.0f}s** remain."}
    try:
        from .dungeons import _get_run
        dungeon_run = await _get_run(db, guild_id, user_id)
        if dungeon_run and dungeon_run.get("status") == "active":
            return {"ok":False,"message":"You are inside an active dungeon. Advance or retreat before exploring."}
    except Exception:
        pass
    try:
        from .expansion import daily_progress
        await daily_progress(db, guild_id, user_id, "explore", 1)
    except Exception:
        pass

    region_id = player.get("region") or START_REGION
    region = get_region(region_id) or REGIONS[START_REGION]
    world = await db.get_rpg_world(guild_id)

    if world.get("event_until") and float(world["event_until"]) <= now:
        world=await db.update_rpg_world(guild_id,active_event=None,event_until=None,updated_at=now)

    event_bonus = 0.08 if world.get("active_event") == "eclipse" else 0.0
    if random.random() < EVENT_CHANCE and not world.get("active_event"):
        event=await _world_event(db,guild_id,world)
        return {"ok":True,"kind":"world_event","region":region,"event":event,"world":await db.get_rpg_world(guild_id)}

    guardian_id=region.get("guardian")
    if guardian_id:
        guardian_state=await db.get_rpg_guardian(guild_id,region_id)
        if not guardian_state["defeated"] and random.random() < GUARDIAN_CHANCE:
            enemy=ENEMIES[guardian_id].copy()
            enemy["id"]=guardian_id
            return {"ok":True,"kind":"guardian","region":region,"enemy":enemy,"world":world}

    discovery_id=roll_discovery(region_id)
    discovery=get_discovery(discovery_id) if discovery_id else None
    if discovery and not await db.has_rpg_discovery(guild_id,user_id,discovery_id):
        if random.random() < DISCOVERY_CHANCE + (0.08 if world.get("active_event")=="silent_hour" else 0.0):
            await db.add_rpg_discovery(guild_id,user_id,discovery_id)
            old_level,new_level,player=await db.add_rpg_xp(guild_id,user_id,discovery["xp"])
            player=await db.update_rpg_player(guild_id,user_id,gold=int(player["gold"])+discovery["gold"])
            await db.advance_rpg_world(guild_id)
            return {"ok":True,"kind":"discovery","region":region,"discovery":discovery,"old_level":old_level,"new_level":new_level,"player":player}

    encounter_chance=min(0.90,0.22+(region["danger"]*0.07)+(int(world["instability"])*0.01)+event_bonus)
    if random.random() < encounter_chance:
        enemy_id=random.choice(region["enemies"])
        enemy=ENEMIES[enemy_id].copy()
        enemy["id"]=enemy_id
        scale=1+max(0,region["danger"]-1)*0.08
        enemy["hp"]=int(enemy["hp"]*scale)
        enemy["attack"]=int(enemy["attack"]*scale)
        enemy["xp"]=int(enemy["xp"]*scale)
        enemy["gold"]=int(enemy["gold"]*scale)
        return {"ok":True,"kind":"enemy","region":region,"enemy":enemy,"world":world}

    event=random_region_event(region_id)
    old_level,new_level,player=await db.add_rpg_xp(guild_id,user_id,event["xp"])
    player=await db.update_rpg_player(guild_id,user_id,gold=max(0,int(player["gold"])+event["gold"]))
    await db.advance_rpg_world(guild_id)
    return {"ok":True,"kind":"event","region":region,"event":event,"old_level":old_level,"new_level":new_level,"player":player,"world":await db.get_rpg_world(guild_id)}
