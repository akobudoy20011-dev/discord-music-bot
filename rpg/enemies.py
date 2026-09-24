"""Starter ECLIPSE PvE enemy pool."""
import random

ENEMIES = {
    "shadow_beast": {"name":"Shadow Beast","hp":90,"attack":13,"xp":55,"gold":35},
    "ironfang_wolf": {"name":"Ironfang Wolf","hp":75,"attack":16,"xp":65,"gold":45},
    "hollow_knight": {"name":"Hollow Knight","hp":125,"attack":18,"xp":95,"gold":70},
    "ash_drake": {"name":"Ash Drake","hp":160,"attack":22,"xp":130,"gold":100},
}

def random_enemy(region_id=None):
    from .world import get_region, START_REGION
    region = get_region(region_id or START_REGION)
    pool = region["enemies"] if region else list(ENEMIES)
    key=random.choice(pool)
    data=ENEMIES[key].copy(); data["id"]=key
    return data
