"""ECLIPSE RPG active skill definitions."""

SKILLS = {
    "knight": [
        {"id":"shield_bash","name":"Shield Bash","cost":5,"power":1.35,"kind":"physical","description":"Strike with defense-backed force."},
        {"id":"iron_wall","name":"Iron Wall","cost":7,"power":0.0,"kind":"guard","description":"Brace against the next attack."},
    ],
    "arcanist": [
        {"id":"arcane_bolt","name":"Arcane Bolt","cost":6,"power":1.65,"kind":"magic","description":"Launch concentrated arcane energy."},
        {"id":"mana_surge","name":"Mana Surge","cost":8,"power":0.0,"kind":"restore","description":"Restore a portion of your mana."},
    ],
    "wraith": [
        {"id":"shadow_strike","name":"Shadow Strike","cost":6,"power":1.55,"kind":"physical","description":"A swift attack from the veil."},
        {"id":"vanish","name":"Vanish","cost":8,"power":0.0,"kind":"evasion","description":"Increase your chance to evade the next attack."},
    ],
    "paladin": [
        {"id":"radiant_smite","name":"Radiant Smite","cost":7,"power":1.45,"kind":"holy","description":"A holy blow against an enemy."},
        {"id":"divine_guard","name":"Divine Guard","cost":8,"power":0.0,"kind":"guard","description":"Reduce incoming damage."},
    ],
    "bloodreaver": [
        {"id":"blood_slash","name":"Blood Slash","cost":6,"power":1.65,"kind":"physical","description":"Deal heavy damage and recover some HP."},
        {"id":"reaver_frenzy","name":"Reaver Frenzy","cost":9,"power":0.0,"kind":"buff","description":"Temporarily amplify offensive power."},
    ],
}

def get_skills(class_key):
    return SKILLS.get(str(class_key).lower(), [])

def get_skill(class_key, skill_id):
    return next((s for s in get_skills(class_key) if s["id"] == str(skill_id).lower()), None)
