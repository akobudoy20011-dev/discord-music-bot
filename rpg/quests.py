"""Persistent RPG quests plus NPC-driven story questlines.

The original objective quests remain the same public system. Story quests are
layered on top of that table so there is no second quest/inventory engine.
NPCs gate multi-stage chains through previous quest claims.
"""

QUESTS = {
    "first_blood":{"name":"First Blood","description":"Defeat 3 enemies.","goal":3,"kind":"kills","xp":150,"gold":100,"item":"guardian_mail"},
    "veilwalker":{"name":"Veilwalker","description":"Complete 3 adventures.","goal":3,"kind":"adventures","xp":200,"gold":140,"item":"mana_charm"},
    "ashen_hunt":{"name":"Ashen Hunt","description":"Defeat an Ash Drake.","goal":1,"kind":"ash_drake","xp":300,"gold":250,"item":"shadow_dagger"},
}

NPCS = {
    "lyra":{"name":"Lyra, Keeper of the Veil","icon":"🌙","region":"moonlit_vale","description":"A quiet archivist who records disturbances in the Veil.","dialogue":"The moon keeps memories the living were never meant to carry. If you can walk the Vale without losing yourself, I may trust you with its sealed records."},
    "oren":{"name":"Oren, Rootbound Warden","icon":"🌿","region":"whispering_wood","description":"A veteran guardian who speaks for the ancient forest.","dialogue":"The roots remember every blade that has cut them. Bring me proof that you can survive the Wood, and I will show you what sleeps beneath it."},
    "vestra":{"name":"Vestra, Ashen Envoy","icon":"🔥","region":"ashen_crown","description":"An envoy searching the ruins of a fallen crown.","dialogue":"Ash preserves what fire cannot forgive. The Crown left behind a seal, and something beneath it is still listening."},
    "cael":{"name":"Cael, Starwatcher","icon":"🌠","region":"starfall_coast","description":"A star-reader who has seen something moving beyond the coast.","dialogue":"The stars have started disappearing one by one. The old observatory has a keyhole that was never meant for any earthly key."},
}

STORY_QUESTS = {
    "veil_letter":{"name":"A Letter Beneath Moonlight","npc":"lyra","chapter":1,"description":"Complete an adventure for Lyra.","goal":1,"kind":"adventures","xp":175,"gold":125,"item":"moon_seal","dialogue":"Take this sealed letter into the Vale. If the moonlight changes its ink, you have found the path I need."},
    "veil_echoes":{"name":"Echoes in the Veil","npc":"lyra","chapter":2,"requires":"veil_letter","description":"Defeat 3 enemies touched by the Veil.","goal":3,"kind":"kills","xp":250,"gold":200,"item":"echo_fragment","dialogue":"The echoes are multiplying. Break three of their vessels and bring me what remains."},
    "rootbound_oath":{"name":"The Rootbound Oath","npc":"oren","chapter":3,"requires":"veil_echoes","description":"Complete 2 adventures in the Whispering Wood.","goal":2,"kind":"adventures","region":"whispering_wood","xp":325,"gold":300,"item":"root_token","dialogue":"The forest does not need heroes. It needs someone willing to keep an oath when no one is watching."},
    "ashen_seal":{"name":"Seal of Cinders","npc":"vestra","chapter":4,"requires":"rootbound_oath","description":"Defeat an Ash Drake in the Ashen Crown.","goal":1,"kind":"ash_drake","region":"ashen_crown","xp":450,"gold":425,"item":"ashen_seal","dialogue":"The drakes guard the last seal because they remember the Crown. Take it from one of them, and the ruins will open."},
    "starfall_key":{"name":"The Starfall Key","npc":"cael","chapter":5,"requires":"ashen_seal","description":"Complete 3 adventures on the Starfall Coast.","goal":3,"kind":"adventures","region":"starfall_coast","xp":650,"gold":650,"item":"star_key","special":"celestial_tempest","dialogue":"Three journeys beneath the falling stars. Return alive and I will give you the key to the observatory."},
}

ALL_QUESTS = {**QUESTS, **STORY_QUESTS}

def list_quests(): return list(ALL_QUESTS.items())
def get_quest(quest_id): return ALL_QUESTS.get(str(quest_id).lower())
def get_npc(npc_id): return NPCS.get(str(npc_id).lower())

def _unlocked(row_map, quest):
    required = quest.get("requires")
    return not required or bool(row_map.get(required, {}).get("claimed"))

async def ensure_quests(db,guild_id,user_id):
    existing={q["quest_id"] for q in await db.get_rpg_quests(guild_id,user_id)}
    for qid in ALL_QUESTS:
        if qid not in existing: await db.set_rpg_quest(guild_id,user_id,qid)
    return await db.get_rpg_quests(guild_id,user_id)

async def progress(db,guild_id,user_id,kind,amount=1,enemy_id=None):
    quests=await ensure_quests(db,guild_id,user_id)
    row_map={r["quest_id"]:r for r in quests}
    player=await db.get_rpg_player(guild_id,user_id)
    region=player.get("region")
    for row in quests:
        q=ALL_QUESTS[row["quest_id"]]
        if row["completed"] or not _unlocked(row_map,q): continue
        if q.get("region") and q["region"] != region: continue
        if not (q["kind"]==kind or q["kind"]==enemy_id): continue
        value=min(q["goal"],row["progress"]+amount)
        await db.set_rpg_quest(guild_id,user_id,row["quest_id"],value,int(value>=q["goal"]),row["claimed"])
    return await db.get_rpg_quests(guild_id,user_id)

async def claim(db,guild_id,user_id,quest_id):
    quest_id=str(quest_id).lower()
    q=get_quest(quest_id)
    row=await db.get_rpg_quest(guild_id,user_id,quest_id)
    if not q or not row: return {"ok":False,"message":"Unknown quest."}
    quests=await ensure_quests(db,guild_id,user_id)
    if not _unlocked({r["quest_id"]:r for r in quests},q):
        return {"ok":False,"message":"That quest is still locked. Complete the previous chapter first."}
    if not row["completed"]: return {"ok":False,"message":"Quest is not complete yet."}
    if row["claimed"]: return {"ok":False,"message":"Quest reward already claimed."}
    old,new,player=await db.add_rpg_xp(guild_id,user_id,q["xp"])
    player=await db.update_rpg_player(guild_id,user_id,gold=player["gold"]+q["gold"])
    if q.get("item"): await db.add_rpg_item(guild_id,user_id,q["item"],1)
    special_unlocked = None
    if q.get("special"):
        from .specials import get_special
        special = get_special(q["special"])
        if special:
            await db.unlock_rpg_special(guild_id,user_id,q["special"],source=f"quest:{quest_id}")
            special_unlocked = q["special"]
    await db.set_rpg_quest(guild_id,user_id,quest_id,row["progress"],1,1)
    next_quest=next((qid for qid,data in STORY_QUESTS.items() if data.get("requires")==quest_id),None)
    return {"ok":True,"quest":q,"level_up":new>old,"next_quest":next_quest,"special_unlocked":special_unlocked}

async def npc_view(db,guild_id,user_id,npc_id):
    npc=get_npc(npc_id)
    if not npc: return None
    rows=await ensure_quests(db,guild_id,user_id)
    row_map={r["quest_id"]:r for r in rows}
    available=[(qid,q,row_map[qid]) for qid,q in STORY_QUESTS.items() if q.get("npc")==str(npc_id).lower() and _unlocked(row_map,q) and not row_map[qid]["claimed"]]
    return {"npc":npc,"quests":available}
