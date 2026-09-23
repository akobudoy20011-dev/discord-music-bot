"""RPG equipment service."""
from .items import get_item

async def grant_starter_gear(db,guild_id,user_id,class_key):
    weapon={"knight":"iron_sword","arcanist":"moon_staff","wraith":"shadow_dagger","paladin":"iron_sword","bloodreaver":"shadow_dagger"}.get(class_key,"iron_sword")
    items=await db.get_rpg_items(guild_id,user_id)
    if not any(x["item_id"]==weapon for x in items):
        await db.add_rpg_item(guild_id,user_id,weapon,1)
        await db.set_rpg_item_equipped(guild_id,user_id,weapon,True)
    return await db.get_rpg_items(guild_id,user_id)

async def inventory(db,guild_id,user_id):
    return await db.get_rpg_items(guild_id,user_id)
