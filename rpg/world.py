"""ECLIPSE RPG world layer — original high-fantasy regions."""
import random

REGIONS = {
    "moonlit_vale": {"name":"Moonlit Vale","icon":"🌙","danger":1,"travel":0,"description":"A silver-green valley where ancient roads disappear beneath wildflowers.","enemies":["shadow_beast","ironfang_wolf"],"loot_bonus":0.02},
    "whispering_wood": {"name":"Whispering Wood","icon":"🌲","danger":2,"travel":20,"description":"An old forest that seems to remember every traveler who enters it.","enemies":["shadow_beast","ironfang_wolf","hollow_knight"],"loot_bonus":0.06},
    "ashen_crown": {"name":"Ashen Crown","icon":"🔥","danger":3,"travel":35,"description":"A volcanic frontier ruled by ruins, black rain, and things that refuse to die.","enemies":["ironfang_wolf","hollow_knight","ash_drake"],"loot_bonus":0.10},
    "starfall_coast": {"name":"Starfall Coast","icon":"🌊","danger":4,"travel":50,"description":"A luminous coast where fragments of fallen stars are said to sleep beneath the tide.","enemies":["hollow_knight","ash_drake"],"loot_bonus":0.14},
}
START_REGION = "moonlit_vale"

def get_region(region_id):
    return REGIONS.get(str(region_id).lower())

def list_regions():
    return list(REGIONS.items())

def random_region_event(region_id):
    region = get_region(region_id) or REGIONS[START_REGION]
    events = [
        ("old_waystone","You find an ancient waystone humming beneath the moss.",20,18),
        ("silver_deer","A pale stag watches you from the trees, then vanishes into the mist.",12,22),
        ("forgotten_coin","Something glints beneath the earth.",35,10),
        ("quiet_shrine","A forgotten shrine answers your presence with a brief warmth.",8,28),
    ]
    event_id,text,gold,xp = random.choice(events)
    return {"id":event_id,"text":text,"gold":gold*region["danger"],"xp":xp*region["danger"]}
