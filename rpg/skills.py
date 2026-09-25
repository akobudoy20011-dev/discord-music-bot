"""ECLIPSE RPG active skill definitions.

Skills are deliberately separate from specials: skills are repeatable combat
tools with lower costs and shorter cooldowns, while specials are class-defining
high-impact abilities.
"""

SKILLS = {
    "knight": [
        {"id":"shield_bash","name":"Shield Bash","cost":5,"power":1.35,"kind":"physical","level":1,"cooldown":0,"description":"Strike with defense-backed force."},
        {"id":"iron_wall","name":"Iron Wall","cost":7,"power":0.0,"kind":"guard","level":2,"cooldown":2,"description":"Brace against the next attacks."},
        {"id":"sweeping_strike","name":"Sweeping Strike","cost":8,"power":1.55,"kind":"physical","level":5,"cooldown":2,"description":"A broad weapon sweep that hits with crushing force."},
        {"id":"fortify","name":"Fortify","cost":10,"power":0.0,"kind":"guard","level":8,"cooldown":4,"description":"Raise a heavy defensive stance for several turns."},
        {"id":"executioner","name":"Executioner","cost":13,"power":2.05,"kind":"physical","level":12,"cooldown":4,"description":"A brutal finishing blow."},
    ],
    "arcanist": [
        {"id":"arcane_bolt","name":"Arcane Bolt","cost":6,"power":1.65,"kind":"magic","level":1,"cooldown":0,"description":"Launch concentrated arcane energy."},
        {"id":"mana_surge","name":"Mana Surge","cost":8,"power":0.0,"kind":"restore","level":2,"cooldown":3,"description":"Restore a portion of your mana."},
        {"id":"frost_lance","name":"Frost Lance","cost":9,"power":1.85,"kind":"magic","level":5,"cooldown":2,"description":"Drive a spear of frozen arcana through the target."},
        {"id":"arcane_barrier","name":"Arcane Barrier","cost":11,"power":0.0,"kind":"guard","level":8,"cooldown":4,"description":"Wrap yourself in a mana barrier."},
        {"id":"meteor","name":"Meteor","cost":15,"power":2.35,"kind":"magic","level":12,"cooldown":4,"description":"Call down a devastating fragment of the heavens."},
    ],
    "wraith": [
        {"id":"shadow_strike","name":"Shadow Strike","cost":6,"power":1.55,"kind":"physical","level":1,"cooldown":0,"description":"A swift attack from the veil."},
        {"id":"vanish","name":"Vanish","cost":8,"power":0.0,"kind":"evasion","level":2,"cooldown":3,"description":"Disappear into the veil and evade the next attack."},
        {"id":"poison_blade","name":"Poison Blade","cost":8,"power":1.45,"kind":"physical","level":5,"cooldown":2,"description":"A poisoned strike that keeps pressure on the target."},
        {"id":"afterimage","name":"Afterimage","cost":10,"power":0.0,"kind":"evasion","level":8,"cooldown":4,"description":"Leave a false image behind and become extremely elusive."},
        {"id":"death_mark","name":"Death Mark","cost":14,"power":2.15,"kind":"physical","level":12,"cooldown":4,"description":"Mark the target for a lethal shadow assault."},
    ],
    "paladin": [
        {"id":"radiant_smite","name":"Radiant Smite","cost":7,"power":1.45,"kind":"holy","level":1,"cooldown":0,"description":"A holy blow against an enemy."},
        {"id":"divine_guard","name":"Divine Guard","cost":8,"power":0.0,"kind":"guard","level":2,"cooldown":2,"description":"Reduce incoming damage."},
        {"id":"holy_lance","name":"Holy Lance","cost":10,"power":1.85,"kind":"holy","level":5,"cooldown":2,"description":"Pierce darkness with concentrated holy power."},
        {"id":"sanctuary","name":"Sanctuary","cost":11,"power":0.0,"kind":"guard","level":8,"cooldown":4,"description":"Create a sacred barrier that protects you for several turns."},
        {"id":"divine_spear","name":"Divine Spear","cost":15,"power":2.30,"kind":"holy","level":12,"cooldown":4,"description":"A devastating celestial thrust."},
    ],
    "bloodreaver": [
        {"id":"blood_slash","name":"Blood Slash","cost":6,"power":1.65,"kind":"physical","level":1,"cooldown":0,"description":"Deal heavy damage and recover some HP."},
        {"id":"reaver_frenzy","name":"Reaver Frenzy","cost":9,"power":0.0,"kind":"buff","level":2,"cooldown":3,"description":"Temporarily amplify offensive power."},
        {"id":"hemorrhage","name":"Hemorrhage","cost":9,"power":1.70,"kind":"physical","level":5,"cooldown":2,"description":"Open a deep wound with a savage strike."},
        {"id":"blood_fortress","name":"Blood Fortress","cost":11,"power":0.0,"kind":"guard","level":8,"cooldown":4,"description":"Convert pain into a temporary defensive shell."},
        {"id":"reaper_strike","name":"Reaper Strike","cost":15,"power":2.40,"kind":"physical","level":12,"cooldown":4,"description":"An overwhelming execution attempt."},
    ],
}


def get_skills(class_key):
    return SKILLS.get(str(class_key).lower(), [])


def get_skill(class_key, skill_id):
    return next((s for s in get_skills(class_key) if s["id"] == str(skill_id).lower()), None)
