"""ECLIPSE RPG world layer — original high-fantasy regions and world events."""
import random

REGIONS = {
    "moonlit_vale": {
        "name":"Moonlit Vale","icon":"🌙","danger":1,"travel":0,
        "description":"A silver-green valley where ancient roads disappear beneath wildflowers.",
        "enemies":["shadow_beast","ironfang_wolf"],"loot_bonus":0.02,
        "guardian":"pale_stag","discovery":"hollow_chapel"
    },
    "whispering_wood": {
        "name":"Whispering Wood","icon":"🌲","danger":2,"travel":20,
        "description":"An old forest that seems to remember every traveler who enters it.",
        "enemies":["shadow_beast","ironfang_wolf","hollow_knight"],"loot_bonus":0.06,
        "guardian":"rootbound_warden","discovery":"rootbound_grove"
    },
    "ashen_crown": {
        "name":"Ashen Crown","icon":"🔥","danger":3,"travel":35,
        "description":"A volcanic frontier ruled by ruins, black rain, and things that refuse to die.",
        "enemies":["ironfang_wolf","hollow_knight","ash_drake"],"loot_bonus":0.10,
        "guardian":"ashen_sovereign","discovery":"blackglass_keep"
    },
    "starfall_coast": {
        "name":"Starfall Coast","icon":"🌊","danger":4,"travel":50,
        "description":"A luminous coast where fragments of fallen stars are said to sleep beneath the tide.",
        "enemies":["hollow_knight","ash_drake"],"loot_bonus":0.14,
        "guardian":"astral_leviathan","discovery":"starwatch_ruins"
    },
}
START_REGION = "moonlit_vale"

WORLD_EVENTS = {
    "eclipse": {
        "name":"THE ECLIPSE",
        "icon":"🌑",
        "description":"The sky darkens. The Veil thins, and hostile encounters become more common.",
        "duration":180,
        "instability":2,
    },
    "starfall": {
        "name":"STARFALL",
        "icon":"🌠",
        "description":"Fragments of a distant star cross the sky. Exploration yields more rare finds.",
        "duration":180,
        "instability":1,
    },
    "ashfall": {
        "name":"ASHFALL",
        "icon":"🔥",
        "description":"Black ash covers the frontier. Ashen Crown becomes unusually dangerous.",
        "duration":180,
        "instability":2,
    },
    "silent_hour": {
        "name":"THE SILENT HOUR",
        "icon":"🕯️",
        "description":"The world falls strangely quiet. Hidden discoveries become easier to find.",
        "duration":150,
        "instability":-1,
    },
}

DISCOVERIES = {
    "hollow_chapel": {
        "name":"The Hollow Chapel","icon":"🕯️",
        "description":"A forgotten chapel where offerings are still being left for something unseen.",
        "region":"moonlit_vale","xp":80,"gold":60
    },
    "rootbound_grove": {
        "name":"The Rootbound Grove","icon":"🌿",
        "description":"An ancient grove whose roots form a perfect circle around a sealed stone door.",
        "region":"whispering_wood","xp":120,"gold":90
    },
    "blackglass_keep": {
        "name":"Blackglass Keep","icon":"🏰",
        "description":"A fortress of volcanic glass overlooking the oldest road into the Crown.",
        "region":"ashen_crown","xp":180,"gold":140
    },
    "starwatch_ruins": {
        "name":"Starwatch Ruins","icon":"🌠",
        "description":"Collapsed observatories built to watch the heavens before the first Eclipse.",
        "region":"starfall_coast","xp":250,"gold":200
    },
}

def get_region(region_id):
    return REGIONS.get(str(region_id).lower())

def list_regions():
    return list(REGIONS.items())

def get_event(event_id):
    return WORLD_EVENTS.get(str(event_id).lower())

def list_events():
    return list(WORLD_EVENTS.items())

def get_discovery(discovery_id):
    return DISCOVERIES.get(str(discovery_id).lower())

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

def roll_world_event():
    return random.choice(list(WORLD_EVENTS))

def roll_discovery(region_id):
    region = get_region(region_id) or REGIONS[START_REGION]
    return region.get("discovery")
