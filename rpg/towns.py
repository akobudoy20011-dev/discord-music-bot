"""ECLIPSE RPG towns, services, merchants, and shrines."""
from .world import get_region
from .items import get_item

TOWNS = {
    "moonlit_vale": {
        "name":"Moonhaven","icon":"🏘️","description":"A lantern-lit settlement built around a moonstone spring.",
        "services":["inn","merchant","blacksmith","shrine"],
        "merchant":{"iron_sword":{"price":180,"stock":3},"moon_staff":{"price":220,"stock":3},"guardian_mail":{"price":260,"stock":2}},
    },
    "whispering_wood": {
        "name":"Thornmere","icon":"🌿","description":"A forest town of rope bridges, herbalists, and old stone homes.",
        "services":["inn","merchant","alchemist","shrine"],
        "merchant":{"shadow_dagger":{"price":300,"stock":3},"mana_charm":{"price":340,"stock":2},"guardian_mail":{"price":380,"stock":2}},
    },
    "ashen_crown": {
        "name":"Emberhold","icon":"🔥","description":"A fortified mining town whose furnaces never seem to cool.",
        "services":["inn","merchant","blacksmith","shrine"],
        "merchant":{"iron_sword":{"price":450,"stock":4},"shadow_dagger":{"price":500,"stock":3},"guardian_mail":{"price":600,"stock":2}},
    },
    "starfall_coast": {
        "name":"Starwatch","icon":"🌠","description":"A cliffside harbor where astronomers trade fragments of fallen stars.",
        "services":["inn","merchant","alchemist","shrine"],
        "merchant":{"moon_staff":{"price":750,"stock":3},"mana_charm":{"price":900,"stock":2},"guardian_mail":{"price":850,"stock":2}},
    },
}
INN_COST=35
SHRINE_COST=60
ALCHEMIST_COST=90

def get_town(region_id): return TOWNS.get(str(region_id).lower())
def list_towns(): return list(TOWNS.items())

async def town_status(db,guild_id,user_id):
    player=await db.get_rpg_player(guild_id,user_id)
    region_id=player.get("region") or "moonlit_vale"
    town=get_town(region_id)
    if not town: return {"ok":False,"message":"There is no settlement in this realm yet."}
    return {"ok":True,"player":player,"region":get_region(region_id),"town":town}

async def inn(db,guild_id,user_id):
    s=await town_status(db,guild_id,user_id)
    if not s["ok"]: return s
    ok,_=await db.spend_rpg_gold(guild_id,user_id,INN_COST)
    if not ok: return {"ok":False,"message":f"You need **{INN_COST} RPG gold** for a room."}
    p=await db.get_rpg_player(guild_id,user_id)
    p=await db.update_rpg_player(guild_id,user_id,hp=p["max_hp"],mp=p["max_mp"])
    return {"ok":True,"player":p,"town":s["town"],"cost":INN_COST}

async def shrine(db,guild_id,user_id):
    s=await town_status(db,guild_id,user_id)
    if not s["ok"]: return s
    ok,_=await db.spend_rpg_gold(guild_id,user_id,SHRINE_COST)
    if not ok: return {"ok":False,"message":f"You need **{SHRINE_COST} RPG gold** for the shrine blessing."}
    old,new,p=await db.add_rpg_xp(guild_id,user_id,50)
    return {"ok":True,"cost":SHRINE_COST,"xp":50,"old_level":old,"new_level":new,"town":s["town"]}

async def alchemist(db,guild_id,user_id):
    s=await town_status(db,guild_id,user_id)
    if not s["ok"]: return s
    ok,_=await db.spend_rpg_gold(guild_id,user_id,ALCHEMIST_COST)
    if not ok: return {"ok":False,"message":f"You need **{ALCHEMIST_COST} RPG gold** for a draught."}
    p=await db.get_rpg_player(guild_id,user_id)
    p=await db.update_rpg_player(guild_id,user_id,mp=p["max_mp"])
    return {"ok":True,"cost":ALCHEMIST_COST,"player":p,"town":s["town"]}

async def buy(db,guild_id,user_id,item_id):
    s=await town_status(db,guild_id,user_id)
    if not s["ok"]: return s
    item_id=str(item_id).lower()
    offer=s["town"]["merchant"].get(item_id)
    if not offer: return {"ok":False,"message":"That item is not sold in this settlement."}
    item=get_item(item_id)
    if not item: return {"ok":False,"message":"That item no longer exists."}
    ok,_=await db.spend_rpg_gold(guild_id,user_id,offer["price"])
    if not ok: return {"ok":False,"message":f"You need **{offer['price']:,} RPG gold**."}
    await db.add_rpg_item(guild_id,user_id,item_id,1)
    return {"ok":True,"item":item,"price":offer["price"],"town":s["town"]}
