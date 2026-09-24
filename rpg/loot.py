"""RPG loot rolls, including realm-guardian rewards."""
import random
from .items import ITEMS

LOOT_TABLE=[
    ("guardian_mail",.08),("mana_charm",.10),("iron_sword",.10),
    ("moon_staff",.10),("shadow_dagger",.10),("thornblade",.07),
    ("thornmantle",.06),("veilring",.05),("embercleaver",.04),
    ("ashplate",.04),("starfall_staff",.03),("starweave",.03),
]
BOSS_LOOT={
    "pale_stag":"pale_antler",
    "rootbound_warden":"rootheart",
    "ashen_sovereign":"sovereign_cinder",
    "astral_leviathan":"leviathan_eye",
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
