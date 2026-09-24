"""ECLIPSE RPG enemy and realm guardian pool."""
import random

ENEMIES = {
    "shadow_beast": {"name":"Shadow Beast","hp":90,"attack":13,"xp":55,"gold":35},
    "ironfang_wolf": {"name":"Ironfang Wolf","hp":75,"attack":16,"xp":65,"gold":45},
    "hollow_knight": {"name":"Hollow Knight","hp":125,"attack":18,"xp":95,"gold":70},
    "ash_drake": {"name":"Ash Drake","hp":160,"attack":22,"xp":130,"gold":100},

    "pale_stag": {"name":"The Pale Stag","hp":320,"attack":28,"xp":400,"gold":300,"boss":True},
    "rootbound_warden": {"name":"The Rootbound Warden","hp":520,"attack":34,"xp":650,"gold":500,"boss":True},
    "ashen_sovereign": {"name":"The Ashen Sovereign","hp":780,"attack":42,"xp":1000,"gold":800,"boss":True},
    "astral_leviathan": {"name":"The Astral Leviathan","hp":1100,"attack":52,"xp":1600,"gold":1400,"boss":True},
}

def random_enemy(region_id=None):
    from .world import get_region, START_REGION
    region = get_region(region_id or START_REGION)
    pool = region["enemies"] if region else list(ENEMIES)
    key=random.choice(pool)
    data=ENEMIES[key].copy(); data["id"]=key
    return data
