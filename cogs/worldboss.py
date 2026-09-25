"""Server-wide RPG world boss system."""
import random
import time
import discord
from discord.ext import commands
from rpg.equipment import equipment_stats
from rpg.manager import get_player

PHASES=(('Awakening',1.00,0.70),('Enraged',1.25,0.35),('Cataclysm',1.55,0.00))

def boss_phase(b):
    ratio=max(0.0,float(b["hp"])/max(1,int(b["max_hp"])))
    if ratio>0.70: return "Awakening",1.00
    if ratio>0.35: return "Enraged",1.25
    return "Cataclysm",1.55

def boss_effect(b, phase):
    if b["boss_id"]=="void_colossus":
        return {"Awakening":("void_pulse",0.90,0.18),"Enraged":("gravity_crush",0.80,0.28),"Cataclysm":("event_horizon",0.70,0.38)}[phase]
    if b["boss_id"]=="astral_leviathan":
        return {"Awakening":("astral_current",0.92,0.18),"Enraged":("starfall_surge",0.82,0.28),"Cataclysm":("cosmic_rupture",0.72,0.38)}[phase]
    return {"Awakening":("sovereign_aura",0.94,0.18),"Enraged":("imperial_wrath",0.80,0.30),"Cataclysm":("final_decree",0.68,0.40)}[phase]

def boss_mechanic(b, phase):
    bid=b["boss_id"]
    if bid=="void_colossus":
        return {
            "Awakening": ("🌑 Void Pulse", "The Colossus distorts reality around the battlefield."),
            "Enraged": ("🕳️ Gravity Crush", "Void pressure surges through every attacker."),
            "Cataclysm": ("☄️ Event Horizon", "The battlefield is collapsing into the Void."),
        }[phase]
    if bid=="astral_leviathan":
        return {
            "Awakening": ("🌌 Astral Current", "Celestial energy floods the battlefield."),
            "Enraged": ("🌊 Starfall Surge", "The Leviathan unleashes a violent astral wave."),
            "Cataclysm": ("💫 Cosmic Rupture", "The sky itself begins breaking apart."),
        }[phase]
    return {
        "Awakening": ("👑 Sovereign Aura", "The Sovereign tests the strength of its challengers."),
        "Enraged": ("⚡ Imperial Wrath", "The Sovereign's power erupts across the battlefield."),
        "Cataclysm": ("🔥 Final Decree", "The Sovereign begins erasing everything before it."),
    }[phase]

BOSSES={
    "void_colossus":{"name":"Void Colossus","icon":"🌑","hp":250000,"attack":180,"coins":75000,"xp":7500,"duration":7200,"loot":"worldboss_void_core"},
    "astral_leviathan":{"name":"Astral Leviathan","icon":"🌌","hp":500000,"attack":260,"coins":150000,"xp":15000,"duration":10800,"loot":"worldboss_leviathan_heart"},
    "eclipse_sovereign":{"name":"Eclipse Sovereign","icon":"👑","hp":1000000,"attack":400,"coins":300000,"xp":30000,"duration":14400,"loot":"worldboss_sovereign_heart"},
}

class WorldBoss(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.db=bot.db
    def _embed(self,b):
        m=BOSSES.get(b["boss_id"],{})
        phase,multiplier=boss_phase(b)
        mechanic,mechanic_text=boss_mechanic(b,phase)
        return discord.Embed(title=f"{m['icon']} {b['name']}",description=f"HP **{int(b['hp']):,}/{int(b['max_hp']):,}**\nTime: <t:{int(b['ends_at'])}:R>\nReward pool: **{int(b['reward_coins']):,} coins + {int(b['reward_xp']):,} XP**\n\nAttack with !worldboss attack · Claim with !worldboss claim",color=discord.Color.dark_purple())

    @commands.group(name="worldboss",aliases=["wb"],invoke_without_command=True)
    async def worldboss(self,ctx):
        b=await self.db.get_world_boss(ctx.guild.id)
        await ctx.send(embed=self._embed(b)) if b else await ctx.send("🌌 No world boss is active.")

    @worldboss.command(name="start")
    @commands.has_guild_permissions(manage_guild=True)
    async def start(self,ctx,boss_id:str="void_colossus"):
        bid=boss_id.lower(); m=BOSSES.get(bid)
        if not m: await ctx.send("❌ Unknown boss: void_colossus, astral_leviathan, eclipse_sovereign."); return
        current=await self.db.get_world_boss(ctx.guild.id)
        if current and current["status"]=="active" and float(current["ends_at"])>time.time(): await ctx.send("❌ A world boss is already active."); return
        b=await self.db.create_world_boss(ctx.guild.id,bid,m["name"],m["hp"],m["attack"],m["coins"],m["xp"],m["duration"],ctx.author.id)
        await ctx.send(embed=self._embed(b))

    @worldboss.command(name="status")
    async def status(self,ctx):
        b=await self.db.get_world_boss(ctx.guild.id)
        await ctx.send(embed=self._embed(b)) if b else await ctx.send("🌌 No world boss is active.")

    @worldboss.command(name="attack")
    @commands.cooldown(1,8,commands.BucketType.user)
    async def attack(self,ctx):
        b=await self.db.get_world_boss(ctx.guild.id)
        if not b or b["status"]!="active" or float(b["ends_at"])<=time.time(): await ctx.send("❌ No active world boss."); return
        p=await get_player(self.db,ctx.guild.id,ctx.author.id); gear=await equipment_stats(self.db,ctx.guild.id,ctx.author.id)
        phase,multiplier=boss_phase(b)
        effect_multiplier=await self.db.consume_world_boss_effects(ctx.guild.id,b["boss_id"],ctx.author.id)
        base=int(p["strength"])*8+int(p["magic"])*5+int(p["level"])*25+gear["power"]*6
        damage=max(100,int(base*random.uniform(0.90,1.10)*multiplier*effect_multiplier))
        effect_id,debuff_multiplier,proc_chance=boss_effect(b,phase)
        triggered=False
        if random.random()<proc_chance:
            await self.db.add_world_boss_effect(ctx.guild.id,b["boss_id"],ctx.author.id,effect_id,debuff_multiplier,uses=2,duration=120)
            triggered=True
        damage=min(damage,max(1,int(b["hp"])))
        ok,reason,hp=await self.db.damage_world_boss(ctx.guild.id,ctx.author.id,damage)
        if not ok: await ctx.send("❌ The world boss is no longer active."); return
        new_boss=await self.db.get_world_boss(ctx.guild.id)
        effect_name = effect_id.replace("_", " ").title()
        effect_note = f" · 💢 **{effect_name}** weakened your next attacks" if triggered else ""
        await ctx.send(f"⚔️ **{ctx.author.display_name}** dealt **{damage:,}** damage · Boss HP **{hp:,}**{effect_note}.")
        if new_boss and boss_phase(new_boss)[0] != phase:
            new_phase=boss_phase(new_boss)[0]
            mechanic,mechanic_text=boss_mechanic(new_boss,new_phase)
            await ctx.send(f"⚠️ **PHASE SHIFT — {new_phase.upper()}** ⚠️\n{mechanic}\n{mechanic_text}")
        elif random.random() < 0.12:
            mechanic,mechanic_text=boss_mechanic(b,phase)
            await ctx.send(f"💢 **{mechanic}** — {mechanic_text}")
        if reason=="defeated": await ctx.send("🏆 **WORLD BOSS DEFEATED.** Contributors can claim their rewards.")

    @worldboss.command(name="claim")
    async def claim(self,ctx):
        reward,reason=await self.db.claim_world_boss_reward(ctx.guild.id,ctx.author.id)
        if reward is None: await ctx.send("❌ No world-boss reward is available for you."); return
        coins,xp,damage=reward
        await self.db.add_balance(ctx.guild.id,ctx.author.id,coins); await self.db.add_xp(ctx.guild.id,ctx.author.id,xp); await self.db.add_rpg_xp(ctx.guild.id,ctx.author.id,max(1,xp//5))
        loot_id=BOSSES.get((await self.db.get_world_boss(ctx.guild.id) or {}).get("boss_id"),{}).get("loot")
        if loot_id and random.random()<0.20:
            await self.db.add_rpg_item(ctx.guild.id,ctx.author.id,loot_id,1)
            from rpg.expansion import assign_affixes
            await assign_affixes(self.db,ctx.guild.id,ctx.author.id,loot_id)
            loot_text=f" · 🌟 **{loot_id}**"
        else: loot_text=""
        await ctx.send(f"🎁 World-boss reward: **{coins:,} coins + {xp:,} XP** · Damage **{damage:,}**{loot_text}.")

async def setup(bot):
    await bot.add_cog(WorldBoss(bot))