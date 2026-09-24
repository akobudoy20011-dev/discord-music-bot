"""Server-wide RPG world boss system."""
import time
import discord
from discord.ext import commands
from rpg.equipment import equipment_stats
from rpg.manager import get_player

BOSSES={
    "void_colossus":{"name":"Void Colossus","icon":"🌑","hp":250000,"attack":180,"coins":75000,"xp":7500,"duration":7200},
    "astral_leviathan":{"name":"Astral Leviathan","icon":"🌌","hp":500000,"attack":260,"coins":150000,"xp":15000,"duration":10800},
    "eclipse_sovereign":{"name":"Eclipse Sovereign","icon":"👑","hp":1000000,"attack":400,"coins":300000,"xp":30000,"duration":14400},
}

class WorldBoss(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.db=bot.db
    def _embed(self,b):
        m=BOSSES.get(b["boss_id"],{})
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
        p=await get_player(self.db,ctx.guild.id,ctx.author.id); gear=await equipment_stats(self.db,ctx.guild.id,ctx.author.id); companion=await self.db.get_active_rpg_companion(ctx.guild.id,ctx.author.id)
        damage=max(100,int(p["strength"])*8+int(p["magic"])*5+int(p["level"])*25+gear["power"]*6)
        damage=min(damage,max(1,int(b["hp"])))
        ok,reason,hp=await self.db.damage_world_boss(ctx.guild.id,ctx.author.id,damage)
        if not ok: await ctx.send("❌ The world boss is no longer active."); return
        await ctx.send(f"⚔️ **{ctx.author.display_name}** dealt **{damage:,}** damage · Boss HP **{hp:,}**.")
        if reason=="defeated": await ctx.send("🏆 **WORLD BOSS DEFEATED.** Contributors can claim their rewards.")

    @worldboss.command(name="claim")
    async def claim(self,ctx):
        reward,reason=await self.db.claim_world_boss_reward(ctx.guild.id,ctx.author.id)
        if reward is None: await ctx.send("❌ No world-boss reward is available for you."); return
        coins,xp,damage=reward
        await self.db.add_balance(ctx.guild.id,ctx.author.id,coins); await self.db.add_xp(ctx.guild.id,ctx.author.id,xp); await self.db.add_rpg_xp(ctx.guild.id,ctx.author.id,max(1,xp//5))
        await ctx.send(f"🎁 World-boss reward: **{coins:,} coins + {xp:,} XP** · Damage **{damage:,}**.")

async def setup(bot):
    await bot.add_cog(WorldBoss(bot))