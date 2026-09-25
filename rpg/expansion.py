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
    """)
    await db._conn.commit()

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
    new=min(int(p[field])+item["amount"],int(p[maximum]))
    await db.update_rpg_player(guild_id,user_id,**{field:new})
    await db._conn.execute("UPDATE rpg_consumables SET amount=amount-1 WHERE guild_id=? AND user_id=? AND item_id=?",(str(guild_id),str(user_id),item_id))
    await db._conn.commit()
    return {"ok":True,"item":item,"new":new}

async def enchant(db,guild_id,user_id,item_id,enchant_id):
    await _schema(db)
    allowed={"flame":{"name":"Flame","stat":"strength","amount":2,"cost":1000},"ward":{"name":"Ward","stat":"defense","amount":2,"cost":1000},"arcane":{"name":"Arcane","stat":"magic","amount":2,"cost":1200},"swift":{"name":"Swift","stat":"agility","amount":2,"cost":1000}}
    e=allowed.get(str(enchant_id).lower())
    if not e:return {"ok":False,"message":"Unknown enchant. Use flame, ward, arcane, or swift."}
    cur=await db._conn.execute("SELECT item_id FROM rpg_equipment WHERE guild_id=? AND user_id=? AND item_id=?",(str(guild_id),str(user_id),str(item_id).lower()))
    if not await cur.fetchone():return {"ok":False,"message":"That item must be equipped before enchanting."}
    p=await db.get_rpg_player(guild_id,user_id)
    if int(p["gold"])<e["cost"]:return {"ok":False,"message":"Not enough RPG gold."}
    await db.update_rpg_player(guild_id,user_id,gold=int(p["gold"])-e["cost"])
    await db._conn.execute("INSERT INTO rpg_enchants VALUES(?,?,?,?,1) ON CONFLICT(guild_id,user_id,item_id,enchant_id) DO UPDATE SET level=level+1",(str(guild_id),str(user_id),str(item_id).lower(),str(enchant_id).lower()))
    await db._conn.commit()
    return {"ok":True,"enchant":e}
