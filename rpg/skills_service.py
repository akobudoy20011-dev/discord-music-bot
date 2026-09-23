"""RPG skill progression service."""
from .skills import get_skills

async def ensure_class_skills(db,guild_id,user_id,class_key):
    skills=get_skills(class_key)
    owned=await db.get_rpg_skills(guild_id,user_id)
    if not owned and skills:
        await db.unlock_rpg_skill(guild_id,user_id,skills[0]["id"])
    return await db.get_rpg_skills(guild_id,user_id)

async def unlock_skill(db,guild_id,user_id,class_key,skill_id):
    skills=get_skills(class_key)
    skill=next((s for s in skills if s["id"]==str(skill_id).lower()),None)
    if not skill: return None, await db.get_rpg_skills(guild_id,user_id)
    await db.unlock_rpg_skill(guild_id,user_id,skill["id"])
    return skill, await db.get_rpg_skills(guild_id,user_id)
