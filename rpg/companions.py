"""Data-driven RPG companion catalogue."""

COMPANIONS = {
    "moonfox": {
        "name": "Moonfox", "icon": "🦊", "cost": 5000,
        "description": "A lunar fox that sharpens agility and awareness.",
        "bonus": {"agility": 4, "magic": 2},
    },
    "emberwolf": {
        "name": "Emberwolf", "icon": "🐺", "cost": 7500,
        "description": "A fire-born wolf that strengthens physical attacks.",
        "bonus": {"strength": 5, "max_hp": 10},
    },
    "starowl": {
        "name": "Starowl", "icon": "🦉", "cost": 10000,
        "description": "A celestial owl that expands the mana pool.",
        "bonus": {"magic": 5, "max_mp": 18},
    },
    "voidcat": {
        "name": "Voidcat", "icon": "🐈‍⬛", "cost": 15000,
        "description": "A creature of the Veil that balances every attribute.",
        "bonus": {"strength": 3, "defense": 3, "magic": 3, "agility": 3},
    },
}
