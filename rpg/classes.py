"""RPG class definitions kept separate from Discord presentation."""

CLASSES = {
    "knight": {"name":"Knight","icon":"⚔️","description":"A durable frontline fighter built around strength and defense.","stats":{"max_hp":150,"max_mp":30,"strength":15,"defense":14,"magic":5,"agility":7}},
    "arcanist": {"name":"Arcanist","icon":"🔮","description":"A high-magic caster with lower physical defenses.","stats":{"max_hp":95,"max_mp":80,"strength":6,"defense":7,"magic":17,"agility":9}},
    "wraith": {"name":"Wraith","icon":"🌑","description":"A fast shadow fighter focused on agility and critical strikes.","stats":{"max_hp":105,"max_mp":55,"strength":13,"defense":8,"magic":10,"agility":17}},
    "paladin": {"name":"Paladin","icon":"🪽","description":"A defensive holy warrior with balanced physical and magical power.","stats":{"max_hp":140,"max_mp":55,"strength":12,"defense":15,"magic":11,"agility":6}},
    "bloodreaver": {"name":"Bloodreaver","icon":"🩸","description":"An aggressive fighter that trades safety for raw damage.","stats":{"max_hp":130,"max_mp":35,"strength":18,"defense":9,"magic":6,"agility":10}},
}

def get_class(key):
    return CLASSES.get(str(key).lower())
