"""ECLIPSE RPG special-move codex.

Specials are the high-impact layer above normal active skills. They are
persistent unlocks, battle-only casts, and use the same MP resource as the
rest of the RPG combat system.
"""

SPECIALS = {
    "heaven_piercing_ice_wall": {"name":"Heaven Piercing Ice Wall","icon":"❄️","class_keys":["knight","paladin"],"level":3,"cost":14,"cooldown":5,"kind":"ice_wall","power":1.55,"description":"Shatter an enemy with frozen force and raise an ice barrier for two turns."},
    "scorching_garden": {"name":"Scorching Garden","icon":"🌺","class_keys":["arcanist"],"level":3,"cost":16,"cooldown":5,"kind":"burn","power":2.05,"description":"Turn the battlefield into a burning garden; the target keeps taking fire damage."},
    "infinite_darkness": {"name":"Infinite Darkness","icon":"🌑","class_keys":["wraith"],"level":3,"cost":18,"cooldown":7,"kind":"freeze","power":1.25,"duration":5,"description":"Drown the enemy in darkness and freeze it for five moves."},
    "heavenly_judgement": {"name":"Heavenly Judgement","icon":"⚖️","class_keys":["paladin"],"level":5,"cost":22,"cooldown":7,"kind":"holy","power":2.55,"description":"Call down a devastating holy sentence."},
    "amaterasus_blessing": {"name":"Amaterasu's Blessing","icon":"☀️","class_keys":["paladin","arcanist"],"level":5,"cost":18,"cooldown":6,"kind":"blessing","power":0.0,"description":"Restore health and wrap yourself in a three-turn radiant blessing."},
    "crimson_requiem": {"name":"Crimson Requiem","icon":"🩸","class_keys":["bloodreaver"],"level":3,"cost":15,"cooldown":5,"kind":"reaver","power":2.15,"description":"A blood-red execution that returns a portion of its damage as HP."},
    "worldbloom": {"name":"Worldbloom","icon":"🌸","class_keys":["arcanist","paladin"],"level":7,"cost":24,"cooldown":8,"kind":"bloom","power":0.0,"description":"Bloom life through the battlefield, healing you and restoring MP over time."},
    "arcane_overdrive": {"name":"Arcane Overdrive","icon":"🔮","class_keys":["arcanist"],"level":7,"cost":28,"cooldown":8,"kind":"overdrive","power":3.05,"description":"Overload the arcane core for an enormous burst of magic."},
    "army_of_the_fallen": {"name":"Army of the Fallen","icon":"☠️","class_keys":["wraith","bloodreaver"],"level":7,"cost":25,"cooldown":8,"kind":"fallen","power":2.35,"description":"Summon spectral soldiers for a sequence of brutal strikes."},
    "heavens_thunder": {"name":"Heaven's Thunder","icon":"⚡","class_keys":["arcanist","paladin"],"level":9,"cost":30,"cooldown":9,"kind":"thunder","power":3.35,"description":"Bring down celestial lightning with a chance to stun the enemy."},
    "abyssal_tide": {"name":"Abyssal Tide","icon":"🌊","class_keys":["bloodreaver","wraith"],"level":9,"cost":27,"cooldown":9,"kind":"abyss","power":2.75,"description":"A crushing tide from the abyss weakens the target for three turns."},
    "celestial_tempest": {"name":"Celestial Tempest","icon":"🌌","class_keys":["paladin","arcanist"],"level":11,"cost":34,"cooldown":10,"kind":"tempest","power":3.55,"description":"Unleash a storm of celestial force with a chance to stagger the enemy."},
    "worldbreaker": {"name":"Worldbreaker","icon":"💥","class_keys":["knight","bloodreaver"],"level":15,"cost":42,"cooldown":12,"kind":"worldbreaker","power":4.25,"description":"A realm-shattering strike reserved for the strongest warriors."},
}

def get_special(special_id):
    return SPECIALS.get(str(special_id).strip().lower())

def get_specials_for_class(class_key):
    key = str(class_key).strip().lower()
    return [(sid, data) for sid, data in SPECIALS.items() if key in data["class_keys"]]

def can_use_special(class_key, special_id):
    data = get_special(special_id)
    return bool(data and str(class_key).lower() in data["class_keys"])

def available_specials(class_key, level):
    return [(sid, data) for sid, data in get_specials_for_class(class_key) if int(level) >= int(data["level"])]
