"""Data-driven RPG companion catalogue."""

COMPANIONS = {
    "moonfox": {
        "name": "Moonfox", "icon": "🦊", "cost": 5000,
        "description": "A lunar fox that sharpens agility and awareness.",
        "bonus": {"agility": 4, "magic": 2},
        "ability": {"name": "Moonstep", "cooldown": 60, "multiplier": 1.35},
    },
    "emberwolf": {
        "name": "Emberwolf", "icon": "🐺", "cost": 7500,
        "description": "A fire-born wolf that strengthens physical attacks.",
        "bonus": {"strength": 5, "max_hp": 10},
        "ability": {"name": "Inferno Howl", "cooldown": 75, "multiplier": 1.50},
    },
    "starowl": {
        "name": "Starowl", "icon": "🦉", "cost": 10000,
        "description": "A celestial owl that expands the mana pool.",
        "bonus": {"magic": 5, "max_mp": 18},
        "ability": {"name": "Star Sight", "cooldown": 65, "multiplier": 1.40},
    },
    "voidcat": {
        "name": "Voidcat", "icon": "🐈‍⬛", "cost": 15000,
        "description": "A creature of the Veil that balances every attribute.",
        "bonus": {"strength": 3, "defense": 3, "magic": 3, "agility": 3},
        "ability": {"name": "Void Rend", "cooldown": 90, "multiplier": 1.65},
    },
}
