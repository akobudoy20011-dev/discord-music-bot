"""Persistent RPG service layer."""
import random
import time
from .classes import get_class
from .quests import progress as quest_progress

ADVENTURE_COOLDOWN = 45

async def get_player(db, guild_id, user_id):
    return await db.get_rpg_player(guild_id, user_id)

async def choose_class(db, guild_id, user_id, key):
    key = str(key).lower().strip()
    chosen = get_class(key)
    if chosen is None:
        return None, await get_player(db, guild_id, user_id)
    stats = chosen["stats"]
    player = await db.update_rpg_player(guild_id,user_id,class_key=key,max_hp=stats["max_hp"],hp=stats["max_hp"],max_mp=stats["max_mp"],mp=stats["max_mp"],strength=stats["strength"],defense=stats["defense"],magic=stats["magic"],agility=stats["agility"])
    return chosen, player

async def adventure(db, guild_id, user_id):
    player = await get_player(db,guild_id,user_id)
    now=time.time(); last=player.get("last_adventure")
    if last is not None and now-last < ADVENTURE_COOLDOWN:
        return {"ok":False,"remaining":ADVENTURE_COOLDOWN-(now-last),"player":player}
    events=[("A ruined caravan",55,25,"You recover supplies from an abandoned caravan."),("A moonlit shrine",40,35,"A forgotten shrine answers your presence with a quiet blessing."),("A hostile beast",-18,70,"A wild creature attacks. You survive and claim its bounty."),("A hidden cache",90,50,"You uncover a sealed cache beneath the earth."),("A wandering scholar",25,80,"A wandering scholar rewards your curiosity with knowledge.")]
    name,gold,xp,narrative=random.choice(events)
    old_level,new_level,player=await db.add_rpg_xp(guild_id,user_id,xp)
    hp=max(1,min(int(player["max_hp"]),int(player["hp"])+random.randint(-8,6)))
    player=await db.update_rpg_player(guild_id,user_id,gold=max(0,int(player["gold"])+gold),hp=hp,last_adventure=now)
    await quest_progress(db,guild_id,user_id,"adventures",1)
    return {"ok":True,"event":name,"narrative":narrative,"gold":gold,"xp":xp,"old_level":old_level,"new_level":new_level,"player":player}

async def rest(db,guild_id,user_id):
    player=await get_player(db,guild_id,user_id)
    return await db.update_rpg_player(guild_id,user_id,hp=player["max_hp"],mp=player["max_mp"])
