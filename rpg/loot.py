"""RPG loot rolls, including realm-guardian rewards."""
import random
from .items import ITEMS

LOOT_TABLE=[("guardian_mail",.10),("mana_charm",.12),("iron_sword",.18),("moon_staff",.12),("shadow_dagger",.18)]
BOSS_LOOT={
    "pale_stag":"moon_staff",
    "rootbound_warden":"guardian_mail",
    "ashen_sovereign":"shadow_dagger",
    "astral_leviathan":"mana_charm",
}

def roll_loot(enemy_id, loot_bonus=0.0):
    if enemy_id in BOSS_LOOT:
        return BOSS_LOOT[enemy_id]
    chance=min(0.85,0.55+float(loot_bonus or 0))
    if random.random() > chance: return None
    roll=random.random(); cursor=0
    for item_id,chance in LOOT_TABLE:
        cursor += chance
        if roll <= cursor: return item_id
    return None

def describe(item_id):
    item=ITEMS.get(item_id)
    return item["name"] if item else item_id
