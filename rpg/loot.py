"""RPG loot rolls."""
import random
from .items import ITEMS

LOOT_TABLE=[("guardian_mail",.10),("mana_charm",.12),("iron_sword",.18),("moon_staff",.12),("shadow_dagger",.18)]

def roll_loot(enemy_id):
    if random.random() > .55: return None
    roll=random.random(); cursor=0
    for item_id,chance in LOOT_TABLE:
        cursor += chance
        if roll <= cursor: return item_id
    return None

def describe(item_id):
    item=ITEMS.get(item_id)
    return item["name"] if item else item_id
