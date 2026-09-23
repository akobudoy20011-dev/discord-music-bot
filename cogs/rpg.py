"""ECLIPSE RPG command surface."""
import discord
from discord.ext import commands
from constants import COLOR_GOLD, COLOR_PRIMARY
from rpg.classes import CLASSES, get_class
from rpg.manager import ADVENTURE_COOLDOWN, adventure, choose_class, get_player, rest


def xp_bar(current, maximum, length=14):
    if maximum <= 0: return "█"*length
    filled=int(length*min(current/maximum,1))
    return "█"*filled+"░"*(length-filled)

class RPG(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.db=bot.db

    @commands.group(name="rpg",invoke_without_command=True)
    async def rpg(self,ctx): await self.profile(ctx)

    @rpg.command(name="profile",aliases=["p","status"])
    async def profile(self,ctx):
        player=await get_player(self.db,ctx.guild.id,ctx.author.id); cls=get_class(player["class_key"]); need=max(1,player['level']*100)
        embed=discord.Embed(title=f"♡ ECLIPSE · {cls['icon']} {cls['name']} ♡",description=f"**{ctx.author.display_name}**\nLevel **{player['level']}** · {cls['description']}\n\n{xp_bar(player['xp'],need)} **{player['xp']}/{need} XP**",color=COLOR_PRIMARY)
        embed.add_field(name="♡ VITALS",value=f"❤️ {player['hp']}/{player['max_hp']} HP\n💠 {player['mp']}/{player['max_mp']} MP\n💰 {player['gold']:,} RPG gold",inline=True)
        embed.add_field(name="♡ STATS",value=f"⚔️ {player['strength']} STR\n🛡️ {player['defense']} DEF\n🔮 {player['magic']} MAG\n🪽 {player['agility']} AGI",inline=True)
        embed.set_thumbnail(url=ctx.author.display_avatar.url); embed.set_footer(text="୨୧ !rpg class · !rpg adventure · !rpg rest"); await ctx.send(embed=embed)

    @rpg.command(name="class",aliases=["choose"])
    async def class_command(self,ctx,key:str=None):
        if not key:
            lines=[f"{d['icon']} **{d['name']}** — {d['description']}" for d in CLASSES.values()]
            await ctx.send(embed=discord.Embed(title="♡ ECLIPSE · CLASSES ♡",description="\n\n".join(lines)+"\n\nUse !rpg class <name> to choose.",color=COLOR_PRIMARY)); return
        chosen,_=await choose_class(self.db,ctx.guild.id,ctx.author.id,key)
        if chosen is None: await ctx.send("❌ Unknown class. Use !rpg class to see the available paths."); return
        await ctx.send(f"{chosen['icon']} **{ctx.author.display_name}** is now a **{chosen['name']}**.\n{chosen['description']}")

    @rpg.command(name="adventure",aliases=["explore","hunt"])
    @commands.cooldown(1,ADVENTURE_COOLDOWN,commands.BucketType.user)
    async def adventure_command(self,ctx):
        result=await adventure(self.db,ctx.guild.id,ctx.author.id)
        if not result["ok"]: await ctx.send(f"⏳ The world is still settling. Try again in **{result['remaining']:.0f}s**."); return
        reward=f"+{result['gold']:,} gold" if result['gold']>=0 else f"{result['gold']:,} gold"
        level_text="\n✦ **LEVEL UP**" if result["new_level"]>result["old_level"] else ""
        await ctx.send(embed=discord.Embed(title=f"🌙 {result['event']}",description=f"{result['narrative']}\n\n**Rewards:** {reward} · +{result['xp']} XP{level_text}",color=COLOR_GOLD))

    @rpg.command(name="rest",aliases=["heal"])
    async def rest_command(self,ctx):
        player=await rest(self.db,ctx.guild.id,ctx.author.id); await ctx.send(f"🪽 **{ctx.author.display_name}** rests beneath the ECLIPSE.\n❤️ HP restored to **{player['hp']}/{player['max_hp']}** · 💠 MP restored to **{player['mp']}/{player['max_mp']}**")

async def setup(bot): await bot.add_cog(RPG(bot))
