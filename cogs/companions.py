"""RPG companion system for ECLIPSE."""

import discord
from discord.ext import commands

COMPANIONS = {
    "moonfox": {"name":"Moonfox","icon":"🦊","cost":5000,"description":"A lunar fox that sharpens agility and awareness.","bonus":{"agility":4,"magic":2}},
    "emberwolf": {"name":"Emberwolf","icon":"🐺","cost":7500,"description":"A fire-born wolf that strengthens physical attacks.","bonus":{"strength":5,"max_hp":10}},
    "starowl": {"name":"Starowl","icon":"🦉","cost":10000,"description":"A celestial owl that expands the mana pool.","bonus":{"magic":5,"max_mp":18}},
    "voidcat": {"name":"Voidcat","icon":"🐈‍⬛","cost":15000,"description":"A creature of the Veil that balances every attribute.","bonus":{"strength":3,"defense":3,"magic":3,"agility":3}},
}

class Companions(commands.Cog):
    def __init__(self, bot): self.bot=bot; self.db=bot.db

    @commands.group(name="companion", aliases=["companions"], invoke_without_command=True)
    async def companion(self, ctx):
        owned={r["companion_id"]:r for r in await self.db.get_rpg_companions(ctx.guild.id,ctx.author.id)}
        lines=[]
        for cid,c in COMPANIONS.items():
            row=owned.get(cid); bonus=", ".join(f"+{v} {k.upper()}" for k,v in c["bonus"].items())
            state=f" · Lv.{row["level"]}" if row else ""
            active=" ✦ ACTIVE" if row and int(row["active"]) else ""
            lines.append(f"{c["icon"]} **{c["name"]}**{state}{active} — {c["description"]} · {bonus}")
        embed=discord.Embed(title="🌙 ECLIPSE · COMPANIONS",description="\n\n".join(lines),color=discord.Color.blurple())
        embed.set_footer(text="!companion recruit <id> · equip <id> · train <id> <xp>")
        await ctx.send(embed=embed)

    @companion.command(name="recruit")
    async def recruit(self, ctx, companion_id: str):
        cid=companion_id.lower(); c=COMPANIONS.get(cid)
        if not c: await ctx.send("❌ Unknown companion. Use !companion."); return
        ok,reason,data=await self.db.recruit_rpg_companion(ctx.guild.id,ctx.author.id,cid,c["cost"])
        if not ok:
            await ctx.send({"owned":"❌ You already own that companion.","gold":"❌ Not enough RPG gold."}.get(reason,"❌ Recruitment failed.")); return
        await self.db.set_active_rpg_companion(ctx.guild.id,ctx.author.id,cid)
        await ctx.send(f"{c["icon"]} **{c["name"]}** bonded with you. It is now active.")

    @companion.command(name="equip", aliases=["active"])
    async def equip(self, ctx, companion_id: str):
        cid=companion_id.lower()
        if cid not in COMPANIONS: await ctx.send("❌ Unknown companion."); return
        ok,reason=await self.db.set_active_rpg_companion(ctx.guild.id,ctx.author.id,cid)
        if not ok: await ctx.send("❌ You do not own that companion."); return
        await ctx.send(f"{COMPANIONS[cid]["icon"]} **{COMPANIONS[cid]["name"]}** is now your active companion.")

    @companion.command(name="train")
    @commands.cooldown(1,5,commands.BucketType.user)
    async def train(self, ctx, companion_id: str, xp: int=250):
        cid=companion_id.lower()
        if cid not in COMPANIONS: await ctx.send("❌ Unknown companion."); return
        xp=max(1,min(2500,int(xp)))
        ok,reason,data=await self.db.train_rpg_companion(ctx.guild.id,ctx.author.id,cid,xp)
        if not ok: await ctx.send("❌ You either do not own it or lack the RPG gold to train it."); return
        await ctx.send(f"✨ **{COMPANIONS[cid]["name"]}** trained to **Lv.{data["level"]}** · {data["xp"]} XP.")

    @companion.command(name="status")
    async def status(self, ctx):
        active=await self.db.get_active_rpg_companion(ctx.guild.id,ctx.author.id)
        if not active: await ctx.send("🌙 No active companion. Use !companion equip <id>."); return
        c=COMPANIONS[active["companion_id"]]
        await ctx.send(f"{c["icon"]} **{c["name"]}** · Level **{active["level"]}** · XP **{active["xp"]}**\n{c["description"]}")

async def setup(bot):
    await bot.add_cog(Companions(bot))