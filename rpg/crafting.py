"""ECLIPSE RPG crafting and salvage loop.

Materials are persistent and are earned through exploration/combat or by
salvaging unwanted equipment. Recipes are gated by discoveries so regions
actually unlock new equipment paths.
"""

from .items import get_item

MATERIALS = {
    "iron_shard": {"name": "Iron Shard", "icon": "⚙️", "description": "A reusable fragment of forged metal."},
    "moon_petal": {"name": "Moon Petal", "icon": "🌙", "description": "A silver petal that only opens beneath moonlight."},
    "thorn_fiber": {"name": "Thorn Fiber", "icon": "🌿", "description": "Living forest fiber harvested from the Whispering Wood."},
    "ash_core": {"name": "Ash Core", "icon": "🔥", "description": "A heat-darkened core left by creatures of the Ashen Crown."},
    "star_fragment": {"name": "Star Fragment", "icon": "🌠", "description": "A shard of fallen starlight from the Starfall Coast."},
    "guardian_essence": {"name": "Guardian Essence", "icon": "👑", "description": "Residual power left when a realm guardian falls."},
}

RECIPES = {
    "thornblade": {
        "materials": {"iron_shard": 8, "thorn_fiber": 10, "moon_petal": 4},
        "gold": 450,
        "requires_discovery": "rootbound_grove",
        "description": "A living blade grown from forest fiber and moonlit steel.",
    },
    "thornmantle": {
        "materials": {"iron_shard": 6, "thorn_fiber": 12, "moon_petal": 5},
        "gold": 500,
        "requires_discovery": "rootbound_grove",
        "description": "Branch-like armor that moves with its wearer.",
    },
    "embercleaver": {
        "materials": {"iron_shard": 12, "ash_core": 10, "guardian_essence": 1},
        "gold": 1000,
        "requires_discovery": "blackglass_keep",
        "requires_guardian": "ashen_sovereign",
        "description": "A volcanic weapon whose edge never fully cools.",
    },
    "ashplate": {
        "materials": {"iron_shard": 14, "ash_core": 12, "guardian_essence": 1},
        "gold": 1150,
        "requires_discovery": "blackglass_keep",
        "requires_guardian": "ashen_sovereign",
        "description": "Heavy plate tempered in the fires of the Crown.",
    },
    "starfall_staff": {
        "materials": {"ash_core": 8, "star_fragment": 14, "guardian_essence": 2},
        "gold": 1800,
        "requires_discovery": "starwatch_ruins",
        "requires_guardian": "astral_leviathan",
        "description": "A staff built around a fragment of fallen starlight.",
    },
    "starweave": {
        "materials": {"thorn_fiber": 8, "star_fragment": 16, "guardian_essence": 2},
        "gold": 1900,
        "requires_discovery": "starwatch_ruins",
        "requires_guardian": "astral_leviathan",
        "description": "Luminous armor woven from starfall and living fiber.",
    },
}

SALVAGE_YIELD = {
    "common": {"iron_shard": 3},
    "uncommon": {"iron_shard": 5, "moon_petal": 1},
    "rare": {"iron_shard": 6, "thorn_fiber": 2},
    "epic": {"iron_shard": 8, "ash_core": 2},
    "legendary": {"iron_shard": 10, "star_fragment": 2},
    "relic": {"iron_shard": 12, "guardian_essence": 1},
}

def material_info(material_id):
    return MATERIALS.get(str(material_id).lower())

def list_recipes():
    return list(RECIPES.items())

async def can_craft(db, guild_id, user_id, item_id):
    item_id = str(item_id).lower()
    recipe = RECIPES.get(item_id)
    item = get_item(item_id)
    if not recipe or not item:
        return {"ok": False, "message": "That item has no crafting recipe."}

    discovery = recipe.get("requires_discovery")
    if discovery and not await db.has_rpg_discovery(guild_id, user_id, discovery):
        return {"ok": False, "message": f"You must discover \`{discovery}\` before this recipe is revealed."}

    guardian = recipe.get("requires_guardian")
    if guardian:
        from .world import REGIONS
        region_id = next((rid for rid, data in REGIONS.items() if data.get("guardian") == guardian), None)
        if region_id:
            state = await db.get_rpg_guardian(guild_id, region_id)
            if not state["defeated"]:
                return {"ok": False, "message": f"The realm guardian **{guardian.replace('_', ' ').title()}** must fall before this recipe can be forged."}

    if not await db.has_rpg_materials(guild_id, user_id, recipe["materials"]):
        have = {r["material_id"]: int(r["amount"]) for r in await db.get_rpg_materials(guild_id, user_id)}
        missing = [
            f"{material_info(mid)['name']} ×{max(0, int(amount) - have.get(mid, 0))}"
            for mid, amount in recipe["materials"].items()
            if have.get(mid, 0) < int(amount)
        ]
        return {"ok": False, "message": "Missing materials: " + ", ".join(missing)}

    player = await db.get_rpg_player(guild_id, user_id)
    if int(player["gold"]) < int(recipe["gold"]):
        return {"ok": False, "message": f"You need **{recipe['gold']:,} RPG gold**."}

    return {"ok": True, "recipe": recipe, "item": item}

async def craft(db, guild_id, user_id, item_id):
    check = await can_craft(db, guild_id, user_id, item_id)
    if not check["ok"]:
        return check

    recipe = check["recipe"]
    item = check["item"]

    ok, _ = await db.spend_rpg_gold(guild_id, user_id, recipe["gold"])
    if not ok:
        return {"ok": False, "message": "Your RPG gold changed before the forge could complete the order."}

    for material_id, amount in recipe["materials"].items():
        removed = await db.remove_rpg_material(guild_id, user_id, material_id, amount)
        if not removed:
            return {"ok": False, "message": "The forge lost a material during crafting. No item was created."}

    await db.add_rpg_item(guild_id, user_id, item_id, 1)
    return {"ok": True, "item": item, "recipe": recipe}

async def salvage(db, guild_id, user_id, item_id):
    item_id = str(item_id).lower()
    item = get_item(item_id)
    if not item:
        return {"ok": False, "message": "That item does not exist."}

    owned = await db.get_rpg_items(guild_id, user_id)
    row = next((x for x in owned if x["item_id"] == item_id and int(x["amount"]) > 0), None)
    if not row:
        return {"ok": False, "message": "You do not own that item."}

    if int(row.get("equipped", 0)):
        return {"ok": False, "message": "Unequip that item before salvaging it."}

    if not await db.remove_rpg_item(guild_id, user_id, item_id, 1):
        return {"ok": False, "message": "That item is no longer available."}

    yields = SALVAGE_YIELD.get(item.get("rarity", "common"), SALVAGE_YIELD["common"])
    for material_id, amount in yields.items():
        await db.add_rpg_material(guild_id, user_id, material_id, amount)

    return {"ok": True, "item": item, "yields": yields}
