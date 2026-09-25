"""ECLIPSE RPG expansion systems.

This module deliberately excludes systems that already exist elsewhere:
guilds, guild raids/bosses, world bosses, companions, marketplace/auctions,
dungeons, gathering, crafting, achievements, and the core quest engine.

It adds the missing player-facing progression layers around those systems:
factions/reputation, subclasses, PvP arena, housing, dynamic daily quests,
consumables, and gear enchantments.
"""
import random
import time

from .items import ITEMS

FACTIONS = {
    "veilkeepers": {"name":"Veilkeepers","icon":"🌙","description":"Keepers of the Veil and its forbidden memories.","regions":["moonlit_vale"],"rewards":[("Moonlit Reputation","Access to Veilkeeper contracts")]},
    "rootbound": {"name":"Rootbound","icon":"🌿","description":"Ancient wardens who protect the living forest.","regions":["whispering_wood"],"rewards":[("Rootbound Reputation","Access to forest contracts")]},
    "ashen_court": {"name":"Ashen Court","icon":"🔥","description":"Survivors and claimants of the fallen Ashen Crown.","regions":["ashen_crown"],"rewards":[("Ashen Reputation","Access to cinder contracts")]},
    "starwatch": {"name":"Starwatch","icon":"🌠","description":"Astronomers guarding the Starfall Coast.","regions":["starfall_coast"],"rewards":[("Starwatch Reputation","Access to celestial contracts")]},
}

SUBCLASSES = {
    "knight": {
        "warlord":{"name":"Warlord","icon":"⚔️","description":"Aggressive frontline commander.","bonus":{"strength":5,"defense":2}},
        "dread_knight":{"name":"Dread Knight","icon":"☠️","description":"A brutal knight who converts pressure into damage.","bonus":{"strength":3,"max_hp":30,"magic":2}},
        "bastion":{"name":"Bastion","icon":"🛡️","description":"A fortress built around survival.","bonus":{"defense":7,"max_hp":45}},
    },
    "arcanist": {
        "archmage":{"name":"Archmage","icon":"🔮","description":"Pure arcane destruction.","bonus":{"magic":7,"max_mp":20}},
        "chronomancer":{"name":"Chronomancer","icon":"⏳","description":"Manipulates tempo and mana.","bonus":{"magic":4,"agility":5,"max_mp":15}},
        "voidcaller":{"name":"Voidcaller","icon":"🕳️","description":"Channels unstable void power.","bonus":{"magic":5,"strength":2,"max_hp":15}},
    },
    "wraith": {
        "assassin":{"name":"Assassin","icon":"🗡️","description":"Extreme single-target burst.","bonus":{"agility":8,"strength":4}},
        "reaper":{"name":"Reaper","icon":"☠️","description":"A death-focused executioner.","bonus":{"strength":6,"agility":4,"max_hp":15}},
        "phantom":{"name":"Phantom","icon":"👻","description":"A spectral evasive specialist.","bonus":{"agility":7,"magic":4,"max_mp":12}},
    },
    "paladin": {
        "templar":{"name":"Templar","icon":"🛡️","description":"A defensive holy guardian.","bonus":{"defense":6,"max_hp":35,"magic":2}},
        "seraph":{"name":"Seraph","icon":"🪽","description":"A radiant hybrid caster.","bonus":{"magic":6,"defense":3,"max_mp":15}},
        "crusader":{"name":"Crusader","icon":"⚜️","description":"A holy warrior built for decisive strikes.","bonus":{"strength":5,"defense":4}},
    },
    "bloodreaver": {
        "hemomancer":{"name":"Hemomancer","icon":"🩸","description":"Weaponizes blood and magic.","bonus":{"magic":5,"strength":4,"max_mp":10}},
        "berserker":{"name":"Berserker","icon":"🔥","description":"Trades defense for overwhelming force.","bonus":{"strength":9,"max_hp":20}},
        "blood_knight":{"name":"Blood Knight","icon":"🩸","description":"A durable lifesteal bruiser.","bonus":{"strength":5,"defense":5,"max_hp":25}},
    },
}

RELATIONSHIPS = {
    "lyra":{"name":"Lyra","icon":"🌙","gift":["moon_seal","moonstone"]},
    "oren":{"name":"Oren","icon":"🌿","gift":["root_token","thorn_fiber"]},
    "vestra":{"name":"Vestra","icon":"🔥","gift":["ashen_seal","ash_core"]},
    "cael":{"name":"Cael","icon":"🌠","gift":["star_key","star_fragment"]},
}

HOUSING = {
    "camp":{"name":"Traveler's Camp","icon":"⛺","cost":0,"level":1,"bonus":{"max_hp":5,"max_mp":2},"description":"A humble camp beneath the stars."},
    "cottage":{"name":"Moonlit Cottage","icon":"🏡","cost":5000,"level":5,"bonus":{"max_hp":20,"max_mp":10,"defense":2},"description":"A quiet home with a small training yard."},
    "estate":{"name":"Veil Estate","icon":"🏰","cost":25000,"level":10,"bonus":{"max_hp":45,"max_mp":25,"defense":4,"magic":3},"description":"A fortified estate with an arcane study."},
    "castle":{"name":"Eclipse Castle","icon":"🏯","cost":100000,"level":20,"bonus":{"max_hp":90,"max_mp":50,"defense":8,"strength":5,"magic":5},"description":"A personal stronghold worthy of an endgame adventurer."},
}

CONSUMABLES = {
    "minor_potion":{"name":"Minor HP Potion","icon":"🧪","cost":150,"kind":"hp","amount":35,"description":"Restore 35 HP."},
    "mana_potion":{"name":"Mana Potion","icon":"💠","cost":180,"kind":"mp","amount":20,"description":"Restore 20 MP."},
    "greater_potion":{"name":"Greater HP Potion","icon":"❤️","cost":500,"kind":"hp","amount":100,"description":"Restore 100 HP."},
    "elixir":{"name":"Arcane Elixir","icon":"🔮","cost":650,"kind":"mp","amount":55,"description":"Restore 55 MP."},
}

DAILY_POOL = [
    ("ashen_hunt","Defeat 3 enemies","kills",3,250,180,"ashen_court"),
    ("vale_walk","Complete 2 adventures","adventures",2,200,150,"veilkeepers"),
    ("root_forager","Gather 5 resources","gather",5,225,175,"rootbound"),
    ("starwatcher","Explore 3 times","explore",3,275,220,"starwatch"),
]

async def _schema(db):
    await db._conn.executescript("""
    CREATE TABLE IF NOT EXISTS rpg_factions (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, faction_id TEXT NOT NULL,
        reputation INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,user_id,faction_id)
    );
    CREATE TABLE IF NOT EXISTS rpg_subclasses (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, subclass_id TEXT NOT NULL,
        chosen_at REAL NOT NULL, PRIMARY KEY(guild_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS rpg_housing (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, house_id TEXT NOT NULL,
        purchased_at REAL NOT NULL, PRIMARY KEY(guild_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS rpg_pvp_ratings (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, rating INTEGER NOT NULL DEFAULT 1000,
        wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(guild_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS rpg_pvp_matches (
        guild_id TEXT NOT NULL, match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id TEXT NOT NULL, opponent_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        winner_id TEXT, created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rpg_daily_quests (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, day_key TEXT NOT NULL,
        quest_id TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
        goal INTEGER NOT NULL, claimed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(guild_id,user_id,day_key)
    );
    CREATE TABLE IF NOT EXISTS rpg_consumables (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, item_id TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,user_id,item_id)
    );
    CREATE TABLE IF NOT EXISTS rpg_enchants (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, item_id TEXT NOT NULL,
        enchant_id TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(guild_id,user_id,item_id,enchant_id)
    );
    CREATE TABLE IF NOT EXISTS rpg_relationships (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, npc_id TEXT NOT NULL,
        affinity INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,user_id,npc_id)
    );
    """)
    await db._conn.commit()

async def relationship_rows(db,guild_id,user_id):
    await _schema(db)
    for npc_id in RELATIONSHIPS:
        await db._conn.execute(
            "INSERT OR IGNORE INTO rpg_relationships(guild_id,user_id,npc_id) VALUES(?,?,?)",
            (str(guild_id),str(user_id),npc_id),
        )
    await db._conn.commit()
    cur=await db._conn.execute(
        "SELECT * FROM rpg_relationships WHERE guild_id=? AND user_id=? ORDER BY affinity DESC",
        (str(guild_id),str(user_id)),
    )
    return [dict(r) for r in await cur.fetchall()]

def affinity_rank(value):
    value=int(value)
    if value>=1000:return "Soulbound"
    if value>=600:return "Trusted"
    if value>=300:return "Friend"
    if value>=100:return "Acquainted"
    return "Stranger"

async def gift_npc(db,guild_id,user_id,npc_id,item_id):
    await relationship_rows(db,guild_id,user_id)
    npc_id=str(npc_id).lower()
    item_id=str(item_id).lower()
    npc=RELATIONSHIPS.get(npc_id)
    if not npc:return {"ok":False,"message":"Unknown NPC."}
    if item_id not in npc["gift"]:return {"ok":False,"message":f"{npc['name']} does not value that item."}
    rows=await db.get_rpg_items(guild_id,user_id)
    owned=next((r for r in rows if r["item_id"]==item_id and int(r["amount"])>0),None)
    source="item"
    if not owned:
        materials=await db.get_rpg_materials(guild_id,user_id)
        owned=next((r for r in materials if r["material_id"]==item_id and int(r["amount"])>0),None)
        source="material"
    if not owned:return {"ok":False,"message":"You do not own that gift."}
    if source=="item":
        consumed=await db.remove_rpg_item(guild_id,user_id,item_id,1)
    else:
        consumed=await db.remove_rpg_material(guild_id,user_id,item_id,1)
    if not consumed:return {"ok":False,"message":"The gift was no longer available."}
    await db._conn.execute("UPDATE rpg_relationships SET affinity=MIN(1000,affinity+75) WHERE guild_id=? AND user_id=? AND npc_id=?",(str(guild_id),str(user_id),npc_id))
    await db._conn.commit()
    cur=await db._conn.execute("SELECT affinity FROM rpg_relationships WHERE guild_id=? AND user_id=? AND npc_id=?",(str(guild_id),str(user_id),npc_id))
    row=await cur.fetchone()
    return {"ok":True,"npc":npc,"affinity":int(row["affinity"])}

async def faction_rows(db,guild_id,user_id):
    await _schema(db)
    cur=await db._conn.execute("SELECT * FROM rpg_factions WHERE guild_id=? AND user_id=?",(str(guild_id),str(user_id)))
    rows=await cur.fetchall()
    known={r["faction_id"]:dict(r) for r in rows}
    for fid in FACTIONS:
        if fid not in known:
            await db._conn.execute("INSERT INTO rpg_factions(guild_id,user_id,faction_id) VALUES(?,?,?)",(str(guild_id),str(user_id),fid))
    await db._conn.commit()
    cur=await db._conn.execute("SELECT * FROM rpg_factions WHERE guild_id=? AND user_id=? ORDER BY reputation DESC",(str(guild_id),str(user_id)))
    return [dict(r) for r in await cur.fetchall()]

async def add_reputation(db,guild_id,user_id,faction_id,amount):
    if faction_id not in FACTIONS: return False
    await faction_rows(db,guild_id,user_id)
    await db._conn.execute("UPDATE rpg_factions SET reputation=MAX(0,reputation+?) WHERE guild_id=? AND user_id=? AND faction_id=?",(int(amount),str(guild_id),str(user_id),faction_id))
    await db._conn.commit()
    return True

def rep_rank(value):
    value=int(value)
    if value>=3000:return "Exalted"
    if value>=1500:return "Honored"
    if value>=750:return "Trusted"
    if value>=250:return "Friendly"
    if value>0:return "Neutral+"
    return "Neutral"

async def choose_subclass(db,guild_id,user_id,subclass_id):
    await _schema(db)
    p=await db.get_rpg_player(guild_id,user_id)
    if not p:return {"ok":False,"message":"Create your RPG character first."}
    if int(p["level"])<20:return {"ok":False,"message":"Subclass selection requires RPG level 20."}
    sid=str(subclass_id).lower()
    options=SUBCLASSES.get(p["class_key"],{})
    data=options.get(sid)
    if not data:return {"ok":False,"message":"That subclass does not belong to your class."}
    cur=await db._conn.execute("SELECT * FROM rpg_subclasses WHERE guild_id=? AND user_id=?",(str(guild_id),str(user_id)))
    if await cur.fetchone():return {"ok":False,"message":"You already chose a subclass. Subclasses are permanent."}
    await db._conn.execute("INSERT INTO rpg_subclasses VALUES(?,?,?,?)",(str(guild_id),str(user_id),sid,time.time()))
    bonuses=data["bonus"]
    sets=", ".join(f"{k}={k}+?" for k in bonuses)
    vals=[bonuses[k] for k in bonuses]
    vals += [str(guild_id),str(user_id)]
    await db._conn.execute(f"UPDATE rpg_players SET {sets} WHERE guild_id=? AND user_id=?",tuple(vals))
    await db._conn.commit()
    return {"ok":True,"subclass":data}

async def get_subclass(db,guild_id,user_id):
    await _schema(db)
    cur=await db._conn.execute("SELECT s.*,p.class_key FROM rpg_subclasses s JOIN rpg_players p ON p.guild_id=s.guild_id AND p.user_id=s.user_id WHERE s.guild_id=? AND s.user_id=?",(str(guild_id),str(user_id)))
    row=await cur.fetchone()
    return dict(row) if row else None

async def buy_house(db,guild_id,user_id,house_id):
    await _schema(db)
    hid=str(house_id).lower(); h=HOUSING.get(hid)
    p=await db.get_rpg_player(guild_id,user_id)
    if not h:return {"ok":False,"message":"Unknown house."}
    if not p:return {"ok":False,"message":"Create your RPG character first."}
    if int(p["level"])<h["level"]:return {"ok":False,"message":f"Level {h['level']} required."}
    cur=await db._conn.execute("SELECT house_id FROM rpg_housing WHERE guild_id=? AND user_id=?",(str(guild_id),str(user_id)))
    old=await cur.fetchone()
    if old:
        current=HOUSING.get(str(old["house_id"]).lower())
        if current and int(h["level"])<=int(current["level"]):
            return {"ok":False,"message":"That home is not an upgrade."}
        price=max(0,int(h["cost"])-(int(current["cost"]) if current else 0))
        if price>int(p["gold"]): return {"ok":False,"message":f"You need {price:,} more RPG gold for that upgrade."}
        await db.update_rpg_player(guild_id,user_id,gold=int(p["gold"])-price)
        await db._conn.execute("UPDATE rpg_housing SET house_id=?,purchased_at=? WHERE guild_id=? AND user_id=?",(hid,time.time(),str(guild_id),str(user_id)))
        await db._conn.commit()
        return {"ok":True,"house":h,"upgrade":True,"cost":price}
    if int(h["cost"])>int(p["gold"]):return {"ok":False,"message":"Not enough RPG gold."}
    await db.update_rpg_player(guild_id,user_id,gold=int(p["gold"])-int(h["cost"]))
    await db._conn.execute("INSERT INTO rpg_housing VALUES(?,?,?,?)",(str(guild_id),str(user_id),hid,time.time()))
    await db._conn.commit()
    return {"ok":True,"house":h}

async def get_house(db,guild_id,user_id):
    await _schema(db)
    cur=await db._conn.execute("SELECT h.* FROM rpg_housing h WHERE guild_id=? AND user_id=?",(str(guild_id),str(user_id)))
    row=await cur.fetchone()
    if row:return HOUSING.get(row["house_id"])
    return HOUSING["camp"]

async def pvp_rating(db,guild_id,user_id):
    await _schema(db)
    cur=await db._conn.execute("SELECT * FROM rpg_pvp_ratings WHERE guild_id=? AND user_id=?",(str(guild_id),str(user_id)))
    row=await cur.fetchone()
    if row:return dict(row)
    await db._conn.execute("INSERT INTO rpg_pvp_ratings(guild_id,user_id) VALUES(?,?)",(str(guild_id),str(user_id)))
    await db._conn.commit()
    return {"guild_id":str(guild_id),"user_id":str(user_id),"rating":1000,"wins":0,"losses":0}

async def create_pvp(db,guild_id,challenger_id,opponent_id):
    await _schema(db)
    if str(challenger_id)==str(opponent_id):return {"ok":False,"message":"You cannot challenge yourself."}
    cur=await db._conn.execute(
        "SELECT 1 FROM rpg_pvp_matches WHERE guild_id=? AND challenger_id=? AND opponent_id=? AND status='pending'",
        (str(guild_id),str(challenger_id),str(opponent_id)),
    )
    if await cur.fetchone(): return {"ok":False,"message":"That challenge is already pending."}
    await pvp_rating(db,guild_id,challenger_id); await pvp_rating(db,guild_id,opponent_id)
    await db._conn.execute("INSERT INTO rpg_pvp_matches(guild_id,challenger_id,opponent_id,created_at) VALUES(?,?,?,?)",(str(guild_id),str(challenger_id),str(opponent_id),time.time()))
    await db._conn.commit()
    return {"ok":True}

async def resolve_pvp(db,guild_id,challenger_id,opponent_id):
    await _schema(db)
    cur=await db._conn.execute(
        "SELECT match_id,created_at FROM rpg_pvp_matches WHERE guild_id=? AND challenger_id=? AND opponent_id=? AND status='pending' ORDER BY match_id DESC LIMIT 1",
        (str(guild_id),str(challenger_id),str(opponent_id)),
    )
    match=await cur.fetchone()
    if not match: return {"ok":False,"message":"No pending challenge from that player."}
    if time.time()-float(match["created_at"])>900:
        await db._conn.execute("UPDATE rpg_pvp_matches SET status='expired' WHERE match_id=?",(int(match["match_id"]),))
        await db._conn.commit()
        return {"ok":False,"message":"That challenge expired."}
    a=await db.get_rpg_player(guild_id,challenger_id); b=await db.get_rpg_player(guild_id,opponent_id)
    if not a or not b:return {"ok":False,"message":"Both players need RPG characters."}
    ra=await pvp_rating(db,guild_id,challenger_id); rb=await pvp_rating(db,guild_id,opponent_id)
    def power(p):
        return int(p["level"])*25+int(p["strength"])*6+int(p["defense"])*3+int(p["magic"])*5+int(p["agility"])*4
    pa=power(a); pb=power(b)
    chance=max(.15,min(.85,.5+(pa-pb)/max(1,(pa+pb))*0.35))
    winner=challenger_id if random.random()<chance else opponent_id
    loser=opponent_id if winner==challenger_id else challenger_id
    rw=ra if winner==challenger_id else rb; rl=rb if winner==challenger_id else ra
    expected=1/(1+10**((int(rl["rating"])-int(rw["rating"]))/400))
    gain=max(8,round(24*(1-expected))); loss=max(5,round(18*expected))
    await db._conn.execute("UPDATE rpg_pvp_ratings SET rating=rating+?,wins=wins+1 WHERE guild_id=? AND user_id=?",(gain,str(guild_id),str(winner)))
    await db._conn.execute("UPDATE rpg_pvp_ratings SET rating=MAX(0,rating-?),losses=losses+1 WHERE guild_id=? AND user_id=?",(loss,str(guild_id),str(loser)))
    await db._conn.execute("UPDATE rpg_pvp_matches SET status='finished',winner_id=? WHERE guild_id=? AND challenger_id=? AND opponent_id=? AND status='pending'",(str(winner),str(guild_id),str(challenger_id),str(opponent_id)))
    await db._conn.commit()
    return {"ok":True,"winner":winner,"loser":loser,"gain":gain,"loss":loss}

async def daily_quest(db,guild_id,user_id):
    await _schema(db)
    day=time.strftime("%Y-%m-%d",time.gmtime())
    cur=await db._conn.execute("SELECT * FROM rpg_daily_quests WHERE guild_id=? AND user_id=? AND day_key=?",(str(guild_id),str(user_id),day))
    row=await cur.fetchone()
    if row:return dict(row)
    qid,desc,kind,goal,xp,gold,faction=random.choice(DAILY_POOL)
    await db._conn.execute("INSERT INTO rpg_daily_quests VALUES(?,?,?,?,?,?,0)",(str(guild_id),str(user_id),day,qid,0,goal))
    await db._conn.commit()
    return {"guild_id":str(guild_id),"user_id":str(user_id),"day_key":day,"quest_id":qid,"progress":0,"goal":goal,"claimed":0,"description":desc,"kind":kind,"xp":xp,"gold":gold,"faction":faction}

async def daily_progress(db,guild_id,user_id,kind,amount=1):
    row=await daily_quest(db,guild_id,user_id)
    q=next((x for x in DAILY_POOL if x[0]==row["quest_id"]),None)
    if not q or row["claimed"] or q[2]!=kind:return row
    progress=min(int(row["goal"]),int(row["progress"])+int(amount))
    await db._conn.execute("UPDATE rpg_daily_quests SET progress=? WHERE guild_id=? AND user_id=? AND day_key=?",(progress,str(guild_id),str(user_id),row["day_key"]))
    await db._conn.commit()
    row["progress"]=progress
    return row

async def claim_daily(db,guild_id,user_id):
    row=await daily_quest(db,guild_id,user_id)
    if row["claimed"]:return {"ok":False,"message":"Today's reward has already been claimed."}
    if int(row["progress"])<int(row["goal"]):return {"ok":False,"message":"Today's objective is not complete yet."}
    q=next(x for x in DAILY_POOL if x[0]==row["quest_id"])
    await db.add_rpg_xp(guild_id,user_id,q[4])
    p=await db.get_rpg_player(guild_id,user_id)
    await db.update_rpg_player(guild_id,user_id,gold=int(p["gold"])+q[5])
    await add_reputation(db,guild_id,user_id,q[6],50)
    await db._conn.execute("UPDATE rpg_daily_quests SET claimed=1 WHERE guild_id=? AND user_id=? AND day_key=?",(str(guild_id),str(user_id),row["day_key"]))
    await db._conn.commit()
    return {"ok":True,"quest":q}

async def buy_consumable(db,guild_id,user_id,item_id):
    await _schema(db)
    item=CONSUMABLES.get(str(item_id).lower())
    p=await db.get_rpg_player(guild_id,user_id)
    if not item:return {"ok":False,"message":"Unknown consumable."}
    if int(p["gold"])<item["cost"]:return {"ok":False,"message":"Not enough RPG gold."}
    await db.update_rpg_player(guild_id,user_id,gold=int(p["gold"])-item["cost"])
    await db._conn.execute("INSERT INTO rpg_consumables(guild_id,user_id,item_id,amount) VALUES(?,?,?,1) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET amount=amount+1",(str(guild_id),str(user_id),item_id))
    await db._conn.commit()
    return {"ok":True,"item":item}

async def use_consumable(db,guild_id,user_id,item_id):
    await _schema(db)
    item=CONSUMABLES.get(str(item_id).lower())
    if not item:return {"ok":False,"message":"Unknown consumable."}
    cur=await db._conn.execute("SELECT amount FROM rpg_consumables WHERE guild_id=? AND user_id=? AND item_id=?",(str(guild_id),str(user_id),item_id))
    row=await cur.fetchone()
    if not row or int(row["amount"])<=0:return {"ok":False,"message":"You do not own that consumable."}
    p=await db.get_rpg_player(guild_id,user_id)
    field="hp" if item["kind"]=="hp" else "mp"
    maximum="max_hp" if field=="hp" else "max_mp"
    from .equipment import equipment_stats
    gear=await equipment_stats(db,guild_id,user_id)
    effective_max=int(p[maximum])+int(gear.get(maximum,0))
    new=min(int(p[field])+item["amount"],effective_max)
    await db.update_rpg_player(guild_id,user_id,**{field:new})
    await db._conn.execute("UPDATE rpg_consumables SET amount=amount-1 WHERE guild_id=? AND user_id=? AND item_id=?",(str(guild_id),str(user_id),item_id))
    await db._conn.commit()
    return {"ok":True,"item":item,"new":new}

async def enchant(db,guild_id,user_id,item_id,enchant_id):
    await _schema(db)
    allowed={"flame":{"name":"Flame","stat":"strength","amount":2,"cost":1000},"ward":{"name":"Ward","stat":"defense","amount":2,"cost":1000},"arcane":{"name":"Arcane","stat":"magic","amount":2,"cost":1200},"swift":{"name":"Swift","stat":"agility","amount":2,"cost":1000}}
    e=allowed.get(str(enchant_id).lower())
    if not e:return {"ok":False,"message":"Unknown enchant. Use flame, ward, arcane, or swift."}
    cur=await db._conn.execute("SELECT item_id FROM rpg_items WHERE guild_id=? AND user_id=? AND equipped=1 AND item_id=?",(str(guild_id),str(user_id),str(item_id).lower()))
    if not await cur.fetchone():return {"ok":False,"message":"That item must be equipped before enchanting."}
    p=await db.get_rpg_player(guild_id,user_id)
    if int(p["gold"])<e["cost"]:return {"ok":False,"message":"Not enough RPG gold."}
    await db.update_rpg_player(guild_id,user_id,gold=int(p["gold"])-e["cost"])
    await db._conn.execute("INSERT INTO rpg_enchants VALUES(?,?,?,?,1) ON CONFLICT(guild_id,user_id,item_id,enchant_id) DO UPDATE SET level=level+1",(str(guild_id),str(user_id),str(item_id).lower(),str(enchant_id).lower()))
    await db._conn.commit()
    return {"ok":True,"enchant":e}


# ------------------------- ENDGAME LAYER -------------------------
RARITY_ORDER={"common":0,"uncommon":1,"rare":2,"epic":3,"legendary":4,"relic":5,"mythic":6,"celestial":7}
AFFIXES={
    "might":("strength",2,5),"bulwark":("defense",2,5),"arcane":("magic",2,5),"swiftness":("agility",2,5),
    "vitality":("max_hp",8,20),"manaflow":("max_mp",5,15),
}
SET_BONUSES={
    "eclipse":{"pieces":2,"bonus":{"strength":5,"magic":5},"name":"Eclipse Oath"},
    "starfall":{"pieces":3,"bonus":{"magic":10,"max_mp":20},"name":"Starfall Constellation"},
    "sovereign":{"pieces":4,"bonus":{"strength":10,"defense":10,"magic":10,"agility":10},"name":"Sovereign's Dominion"},
}
RAID_TIERS={
    "mythic":{"min_level":20,"hp":2500,"attack":90,"phases":3,"reward_xp":2500,"reward_gold":15000},
    "celestial":{"min_level":30,"hp":6000,"attack":150,"phases":4,"reward_xp":7500,"reward_gold":50000},
}
SEASON_LENGTH=28
ASCENSION_MAX=10

async def _endgame_schema(db):
    await db._conn.executescript("""
    CREATE TABLE IF NOT EXISTS rpg_affixes(guild_id TEXT NOT NULL,user_id TEXT NOT NULL,item_id TEXT NOT NULL,affix_id TEXT NOT NULL,value INTEGER NOT NULL,PRIMARY KEY(guild_id,user_id,item_id,affix_id));
    CREATE TABLE IF NOT EXISTS rpg_raid_runs(guild_id TEXT NOT NULL,user_id TEXT NOT NULL,raid_id TEXT NOT NULL,phase INTEGER NOT NULL DEFAULT 1,hp INTEGER NOT NULL,started_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(guild_id,user_id,raid_id));
    CREATE TABLE IF NOT EXISTS rpg_ascensions(guild_id TEXT NOT NULL,user_id TEXT NOT NULL,ascension INTEGER NOT NULL DEFAULT 0,points INTEGER NOT NULL DEFAULT 0,claimed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id));
    CREATE TABLE IF NOT EXISTS rpg_seasons(guild_id TEXT PRIMARY KEY,season INTEGER NOT NULL DEFAULT 1,started_at REAL NOT NULL,ends_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS rpg_season_stats(guild_id TEXT NOT NULL,season INTEGER NOT NULL,user_id TEXT NOT NULL,points INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,season,user_id));
    """)
    await db._conn.commit()

def roll_affixes(item_id, count=1):
    item=ITEMS.get(str(item_id).lower(),{})
    rarity=RARITY_ORDER.get(item.get("rarity","common"),0)
    count=max(0,min(int(count),1+rarity//2))
    pool=list(AFFIXES)
    random.shuffle(pool)
    return [(a,random.randint(AFFIXES[a][1],AFFIXES[a][2])) for a in pool[:count]]

async def assign_affixes(db,guild_id,user_id,item_id):
    await _endgame_schema(db)
    item=ITEMS.get(str(item_id).lower())
    if not item:return []
    affixes=roll_affixes(item_id)
    for aid,value in affixes:
        await db._conn.execute("INSERT OR IGNORE INTO rpg_affixes VALUES(?,?,?,?,?)",(str(guild_id),str(user_id),str(item_id),aid,value))
    await db._conn.commit()
    return affixes

SET_ITEMS={
    "eclipse":{"legendary_eclipse_blade","legendary_void_crown"},
    "starfall":{"starfall_staff","starweave","leviathan_eye"},
    "sovereign":{"legendary_celestial_aegis","legendary_sovereign_relic","worldboss_sovereign_heart","worldboss_void_core"},
}

async def affix_stats(db,guild_id,user_id):
    await _endgame_schema(db)
    cur=await db._conn.execute(
        """SELECT a.affix_id,a.value
           FROM rpg_affixes a
           JOIN rpg_items e
             ON e.guild_id=a.guild_id AND e.user_id=a.user_id AND e.item_id=a.item_id
            AND e.equipped=1
           WHERE a.guild_id=? AND a.user_id=?""",
        (str(guild_id),str(user_id)),
    )
    totals={k:0 for k in ("strength","defense","magic","agility","max_hp","max_mp")}
    for row in await cur.fetchall():
        a=AFFIXES.get(row["affix_id"])
        if a:totals[a[0]]+=int(row["value"])
    return totals

async def set_bonus_stats(db,guild_id,user_id):
    await _endgame_schema(db)
    cur=await db._conn.execute(
        "SELECT item_id FROM rpg_equipment WHERE guild_id=? AND user_id=?",
        (str(guild_id),str(user_id)),
    )
    equipped={str(r["item_id"]) for r in await cur.fetchall()}
    totals={k:0 for k in ("strength","defense","magic","agility","max_hp","max_mp")}
    for set_id,data in SET_BONUSES.items():
        pieces=len(equipped & SET_ITEMS.get(set_id,set()))
        if pieces>=int(data["pieces"]):
            for key,value in data["bonus"].items():
                totals[key]+=int(value)
    return totals

async def ascension_bonuses(db,guild_id,user_id):
    state=await ascension(db,guild_id,user_id)
    n=int(state.get("ascension",0))
    return {
        "strength":n,
        "defense":n,
        "magic":n,
        "agility":n,
        "max_hp":n*10,
        "max_mp":n*5,
    }

async def raid_status(db,guild_id,user_id,raid_id):
    await _endgame_schema(db)
    raid=RAID_TIERS.get(str(raid_id).lower())
    if not raid:return {"ok":False,"message":"Unknown raid."}
    player=await db.get_rpg_player(guild_id,user_id)
    if int(player["level"])<raid["min_level"]:return {"ok":False,"message":f"You need level {raid['min_level']}."}
    cur=await db._conn.execute("SELECT * FROM rpg_raid_runs WHERE guild_id=? AND user_id=? AND raid_id=?",(str(guild_id),str(user_id),str(raid_id).lower()))
    row=await cur.fetchone()
    return {"ok":True,"raid":raid,"run":dict(row) if row else None}

async def raid_start(db,guild_id,user_id,raid_id):
    info=await raid_status(db,guild_id,user_id,raid_id)
    if not info["ok"]:return info
    if info["run"] and info["run"]["status"]=="active":return {"ok":False,"message":"You already have an active raid run."}
    raid_id=str(raid_id).lower(); raid=RAID_TIERS[raid_id]
    await db._conn.execute("INSERT OR REPLACE INTO rpg_raid_runs VALUES(?,?,?,?,?,?,?)",(str(guild_id),str(user_id),raid_id,1,raid["hp"],time.time(),"active")); await db._conn.commit()
    return {"ok":True,"raid":raid}

async def raid_advance(db,guild_id,user_id,raid_id):
    info=await raid_status(db,guild_id,user_id,raid_id)
    if not info["ok"]:return info
    run=info["run"]
    if not run:return {"ok":False,"message":"Start the raid first."}
    raid=info["raid"]; damage=random.randint(max(10,int(raid["attack"]*0.8)),max(20,int(raid["attack"]*1.4)))+int((await db.get_rpg_player(guild_id,user_id))["level"])*8
    hp=max(0,int(run["hp"])-damage)
    phase=int(run["phase"])
    if hp==0 and phase<int(raid["phases"]): phase+=1; hp=raid["hp"]*(raid["phases"]-phase+1)//raid["phases"]
    status="cleared" if hp==0 else "active"
    await db._conn.execute("UPDATE rpg_raid_runs SET phase=?,hp=?,status=? WHERE guild_id=? AND user_id=? AND raid_id=?",(phase,hp,status,str(guild_id),str(user_id),str(raid_id).lower())); await db._conn.commit()
    if status=="cleared":
        await db.add_rpg_xp(guild_id,user_id,int(raid["reward_xp"]))
        current=await db.get_rpg_player(guild_id,user_id)
        await db.update_rpg_player(guild_id,user_id,gold=int(current["gold"])+int(raid["reward_gold"]))
        await season_points(db,guild_id,user_id,100 if raid_id=="mythic" else 250)
    return {"ok":True,"damage":damage,"hp":hp,"phase":phase,"status":status,"reward":raid if status=="cleared" else None}

async def ascension(db,guild_id,user_id):
    await _endgame_schema(db)
    cur=await db._conn.execute("SELECT * FROM rpg_ascensions WHERE guild_id=? AND user_id=?",(str(guild_id),str(user_id))); row=await cur.fetchone()
    if not row:
        await db._conn.execute("INSERT INTO rpg_ascensions(guild_id,user_id) VALUES(?,?)",(str(guild_id),str(user_id))); await db._conn.commit(); return {"ascension":0,"points":0}
    return dict(row)

async def ascend(db,guild_id,user_id):
    state=await ascension(db,guild_id,user_id); player=await db.get_rpg_player(guild_id,user_id)
    if state["ascension"]>=ASCENSION_MAX:return {"ok":False,"message":"Maximum ascension reached."}
    if int(player["level"])<50:return {"ok":False,"message":"Ascension requires RPG level 50."}
    new=int(state["ascension"])+1
    await db._conn.execute("UPDATE rpg_ascensions SET ascension=?,points=points+5 WHERE guild_id=? AND user_id=?",(new,str(guild_id),str(user_id))); await db._conn.commit()
    return {"ok":True,"ascension":new,"points":5}

async def season_status(db,guild_id,user_id):
    await _endgame_schema(db); now=time.time()
    cur=await db._conn.execute("SELECT * FROM rpg_seasons WHERE guild_id=?",(str(guild_id),)); row=await cur.fetchone()
    if not row:
        await db._conn.execute("INSERT INTO rpg_seasons VALUES(?,?,?,?)",(str(guild_id),1,now,now+SEASON_LENGTH*86400))
        await db._conn.commit()
        row={"season":1,"started_at":now,"ends_at":now+SEASON_LENGTH*86400}
    elif float(row["ends_at"])<=now:
        old_season=int(row["season"])
        cur=await db._conn.execute(
            "SELECT user_id,points FROM rpg_season_stats WHERE guild_id=? AND season=? ORDER BY points DESC",
            (str(guild_id),old_season),
        )
        winners=[dict(x) for x in await cur.fetchall()]
        for rank,entry in enumerate(winners[:3],1):
            reward={1:(10000,1000),2:(6000,600),3:(3000,300)}[rank]
            player=await db.get_rpg_player(guild_id,int(entry["user_id"]))
            if player:
                await db.update_rpg_player(
                    guild_id,int(entry["user_id"]),
                    gold=int(player["gold"])+reward[0],
                )
                await db.add_rpg_xp(guild_id,int(entry["user_id"]),reward[1])
        new_season=old_season+1
        await db._conn.execute(
            "DELETE FROM rpg_season_stats WHERE guild_id=? AND season=?",
            (str(guild_id),old_season),
        )
        await db._conn.execute(
            "UPDATE rpg_seasons SET season=?,started_at=?,ends_at=? WHERE guild_id=?",
            (new_season,now,now+SEASON_LENGTH*86400,str(guild_id)),
        )
        await db._conn.commit()
        row={"season":new_season,"started_at":now,"ends_at":now+SEASON_LENGTH*86400}
    cur=await db._conn.execute("SELECT user_id,points FROM rpg_season_stats WHERE guild_id=? AND season=? ORDER BY points DESC LIMIT 10",(str(guild_id),int(row["season"])))
    leaderboard=[dict(x) for x in await cur.fetchall()]
    return {"season":int(row["season"]),"ends_at":float(row["ends_at"]),"leaderboard":leaderboard}

async def season_points(db,guild_id,user_id,points):
    s=await season_status(db,guild_id,user_id)
    await db._conn.execute("INSERT INTO rpg_season_stats VALUES(?,?,?,?) ON CONFLICT(guild_id,season,user_id) DO UPDATE SET points=points+excluded.points",(str(guild_id),s["season"],str(user_id),int(points))); await db._conn.commit()
    return s["season"]
