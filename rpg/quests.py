"""Persistent RPG quest definitions and progression."""
QUESTS = {
    "first_blood":{"name":"First Blood","description":"Defeat 3 enemies.","goal":3,"kind":"kills","xp":150,"gold":100,"item":"guardian_mail"},
    "veilwalker":{"name":"Veilwalker","description":"Complete 3 adventures.","goal":3,"kind":"adventures","xp":200,"gold":140,"item":"mana_charm"},
    "ashen_hunt":{"name":"Ashen Hunt","description":"Defeat an Ash Drake.","goal":1,"kind":"ash_drake","xp":300,"gold":250,"item":"shadow_dagger"},
}

def list_quests(): return list(QUESTS.items())
def get_quest(quest_id): return QUESTS.get(str(quest_id).lower())

async def ensure_quests(db,guild_id,user_id):
    existing={q["quest_id"] for q in await db.get_rpg_quests(guild_id,user_id)}
    for qid in QUESTS:
        if qid not in existing: await db.set_rpg_quest(guild_id,user_id,qid)
    return await db.get_rpg_quests(guild_id,user_id)

async def progress(db,guild_id,user_id,kind,amount=1,enemy_id=None):
    quests=await ensure_quests(db,guild_id,user_id)
    for row in quests:
        q=QUESTS[row["quest_id"]]
        if row["completed"]: continue
        matches=q["kind"]==kind or (q["kind"]==enemy_id)
        if not matches: continue
        value=min(q["goal"],row["progress"]+amount)
        await db.set_rpg_quest(guild_id,user_id,row["quest_id"],value,int(value>=q["goal"]),row["claimed"])
    return await db.get_rpg_quests(guild_id,user_id)

async def claim(db,guild_id,user_id,quest_id):
    q=get_quest(quest_id); row=await db.get_rpg_quest(guild_id,user_id,quest_id)
    if not q or not row: return {"ok":False,"message":"Unknown quest."}
    if not row["completed"]: return {"ok":False,"message":"Quest is not complete yet."}
    if row["claimed"]: return {"ok":False,"message":"Quest reward already claimed."}
    old,new,player=await db.add_rpg_xp(guild_id,user_id,q["xp"])
    player=await db.update_rpg_player(guild_id,user_id,gold=player["gold"]+q["gold"])
    if q.get("item"): await db.add_rpg_item(guild_id,user_id,q["item"],1)
    await db.set_rpg_quest(guild_id,user_id,quest_id,row["progress"],1,1)
    return {"ok":True,"quest":q,"level_up":new>old}
