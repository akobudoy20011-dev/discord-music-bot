"""RPG skill progression service."""
from .skills import get_skills


async def ensure_class_skills(db, guild_id, user_id, class_key):
    skills = get_skills(class_key)
    owned = await db.get_rpg_skills(guild_id, user_id)
    if not owned and skills:
        await db.unlock_rpg_skill(guild_id, user_id, skills[0]["id"])
    return await db.get_rpg_skills(guild_id, user_id)


async def unlock_skill(db, guild_id, user_id, class_key, skill_id):
    skills = get_skills(class_key)
    skill = next((s for s in skills if s["id"] == str(skill_id).lower()), None)
    if not skill:
        return {"ok": False, "message": "Unknown skill for your class."}
    player = await db.get_rpg_player(guild_id, user_id)
    if int(player["level"]) < int(skill.get("level", 1)):
        return {"ok": False, "message": f"{skill['name']} unlocks at RPG level {skill.get('level', 1)}."}
    owned = await db.get_rpg_skills(guild_id, user_id)
    if skill["id"] in owned:
        return {"ok": False, "message": "That skill is already unlocked.", "skill": skill}
    await db.unlock_rpg_skill(guild_id, user_id, skill["id"])
    return {"ok": True, "skill": skill, "skills": await db.get_rpg_skills(guild_id, user_id)}
