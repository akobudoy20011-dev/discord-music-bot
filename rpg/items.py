"""ECLIPSE RPG item definitions."""

ITEMS = {
    "iron_sword": {"name":"Iron Sword","slot":"weapon","icon":"⚔️","power":3,"description":"A dependable starter blade."},
    "moon_staff": {"name":"Moon Staff","slot":"weapon","icon":"🔮","power":3,"description":"A staff humming with lunar magic."},
    "shadow_dagger": {"name":"Shadow Dagger","slot":"weapon","icon":"🗡️","power":3,"description":"A light blade favored by wraiths."},
    "guardian_mail": {"name":"Guardian Mail","slot":"armor","icon":"🛡️","power":3,"description":"Reinforced armor built to endure."},
    "mana_charm": {"name":"Mana Charm","slot":"charm","icon":"💠","power":8,"description":"Raises maximum mana."},
}

def get_item(item_id):
    return ITEMS.get(str(item_id).lower())
