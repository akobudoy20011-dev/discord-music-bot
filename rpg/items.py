"""ECLIPSE RPG equipment catalogue.

Every item is intentionally data-driven so the equipment system can grow
without changing combat logic.
"""

RARITY_SCALE = {
    "common": 1.00,
    "uncommon": 1.20,
    "rare": 1.45,
    "epic": 1.75,
    "legendary": 2.10,
    "relic": 2.55,
}

ITEMS = {
    # Starter / common gear
    "iron_sword": {
        "name": "Iron Sword", "slot": "weapon", "rarity": "common",
        "icon": "⚔️", "power": 3, "strength": 1,
        "description": "A dependable starter blade.", "region": "moonlit_vale",
    },
    "moon_staff": {
        "name": "Moon Staff", "slot": "weapon", "rarity": "common",
        "icon": "🔮", "power": 2, "magic": 2, "max_mp": 4,
        "description": "A staff humming with lunar magic.", "region": "moonlit_vale",
    },
    "shadow_dagger": {
        "name": "Shadow Dagger", "slot": "weapon", "rarity": "common",
        "icon": "🗡️", "power": 2, "agility": 2,
        "description": "A light blade favored by wraiths.", "region": "moonlit_vale",
    },
    "guardian_mail": {
        "name": "Guardian Mail", "slot": "armor", "rarity": "uncommon",
        "icon": "🛡️", "defense": 4, "max_hp": 12,
        "description": "Reinforced armor built to endure.", "region": "moonlit_vale",
    },
    "mana_charm": {
        "name": "Mana Charm", "slot": "accessory", "rarity": "uncommon",
        "icon": "💠", "max_mp": 10, "magic": 1,
        "description": "A charm that deepens the wearer's mana pool.", "region": "whispering_wood",
    },

    # Regional weapons
    "thornblade": {
        "name": "Thornblade", "slot": "weapon", "rarity": "rare",
        "icon": "🌿", "power": 7, "strength": 2, "agility": 2,
        "description": "A living blade grown around an ancient thorn.", "region": "whispering_wood",
    },
    "embercleaver": {
        "name": "Embercleaver", "slot": "weapon", "rarity": "epic",
        "icon": "🔥", "power": 12, "strength": 5,
        "description": "A furnace-hot weapon forged in Emberhold.", "region": "ashen_crown",
    },
    "starfall_staff": {
        "name": "Starfall Staff", "slot": "weapon", "rarity": "legendary",
        "icon": "🌠", "power": 13, "magic": 7, "max_mp": 12,
        "description": "A staff set with a fragment of fallen starlight.", "region": "starfall_coast",
    },

    # Regional armor / accessories
    "thornmantle": {
        "name": "Thornmantle", "slot": "armor", "rarity": "rare",
        "icon": "🌲", "defense": 7, "agility": 3, "max_hp": 18,
        "description": "Forest armor that moves like woven branches.", "region": "whispering_wood",
    },
    "ashplate": {
        "name": "Ashplate", "slot": "armor", "rarity": "epic",
        "icon": "🛡️", "defense": 12, "strength": 3, "max_hp": 30,
        "description": "Heavy volcanic plate tempered beneath black rain.", "region": "ashen_crown",
    },
    "starweave": {
        "name": "Starweave", "slot": "armor", "rarity": "legendary",
        "icon": "✨", "defense": 10, "magic": 6, "max_hp": 35, "max_mp": 10,
        "description": "Luminous armor woven from fallen-star fibers.", "region": "starfall_coast",
    },
    "veilring": {
        "name": "Veilring", "slot": "accessory", "rarity": "rare",
        "icon": "💍", "agility": 5, "magic": 3, "max_mp": 8,
        "description": "A ring that lets its bearer move between moments.", "region": "whispering_wood",
    },

    # Guardian-exclusive equipment
    "pale_antler": {
        "name": "Pale Antler", "slot": "relic", "rarity": "legendary",
        "icon": "🦌", "agility": 7, "max_hp": 25, "max_mp": 10,
        "description": "A relic left behind by the guardian of Moonlit Vale.",
        "source": "pale_stag",
    },
    "rootheart": {
        "name": "Rootheart", "slot": "relic", "rarity": "legendary",
        "icon": "🌳", "defense": 9, "max_hp": 45, "strength": 3,
        "description": "The living heartwood of the Rootbound Warden.",
        "source": "rootbound_warden",
    },
    "sovereign_cinder": {
        "name": "Sovereign Cinder", "slot": "relic", "rarity": "relic",
        "icon": "🔥", "strength": 8, "magic": 8, "max_hp": 35,
        "description": "A coal that still remembers the Ashen Sovereign's crown.",
        "source": "ashen_sovereign",
    },
    "leviathan_eye": {
        "name": "Leviathan Eye", "slot": "relic", "rarity": "relic",
        "icon": "🌌", "magic": 12, "agility": 8, "max_mp": 35,
        "description": "A star-bright eye from the Astral Leviathan.",
        "source": "astral_leviathan",
    },
}

def get_item(item_id):
    return ITEMS.get(str(item_id).lower())

def rarity_multiplier(item):
    return RARITY_SCALE.get(item.get("rarity", "common"), 1.0)
