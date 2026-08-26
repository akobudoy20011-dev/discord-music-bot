"""
cogs/fun.py
===========
Lightweight interactive commands that don't touch the economy —
avatar/userinfo/serverinfo, choose/rate/ship/compliment, and !stats.
"""

import random

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, footer

COMPLIMENTS = [
    "is genuinely one of the good ones.",
    "always knows how to make a chat better.",
    "has impeccable taste.",
    "is criminally underrated.",
    "brings great energy to this server.",
]

ROASTS = [
    "types like they're being charged per correct word.",
    "has the aim of a stormtrooper in every game.",
    "still hasn't recovered from that one L.",
    "is proof that confidence and skill aren't the same thing.",
]


class Fun(commands.Cog):
    """Avatar/user/server info, and a handful of playful commands."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------
    @commands.command(name="avatar", aliases=["av"])
    async def avatar(self, ctx, member: discord.Member = None):
        member = member or ctx.author

        embed = discord.Embed(
            title=f"{member.display_name}'s Avatar", color=COLOR_PRIMARY
        )
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="userinfo", aliases=["ui", "whois"])
    async def userinfo(self, ctx, member: discord.Member = None):
        member = member or ctx.author

        embed = discord.Embed(title=f"👤 {member}", color=COLOR_PRIMARY)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(
            name="Joined Server",
            value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown",
            inline=True
        )
        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(member.created_at, "R"),
            inline=True
        )
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=" ".join(roles[:10]) if roles else "None",
            inline=False
        )
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="serverinfo", aliases=["si"])
    async def serverinfo(self, ctx):
        guild = ctx.guild

        embed = discord.Embed(title=f"🏠 {guild.name}", color=COLOR_PRIMARY)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Owner", value=str(guild.owner), inline=True)
        embed.add_field(
            name="Created",
            value=discord.utils.format_dt(guild.created_at, "R"),
            inline=True
        )
        embed.add_field(name="Text Channels", value=len(guild.text_channels), inline=True)
        embed.add_field(name="Voice Channels", value=len(guild.voice_channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)

        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    @commands.command(name="choose", aliases=["pick"])
    async def choose(self, ctx, *, options: str):
        choices = [c.strip() for c in options.split(",") if c.strip()]

        if len(choices) < 2:
            await ctx.send("Give me at least two options, separated by commas.")
            return

        await ctx.send(f"🎯 I choose: **{random.choice(choices)}**")

    @commands.command(name="rate")
    async def rate(self, ctx, *, thing: str):
        score = random.randint(1, 100)
        await ctx.send(f"⭐ I'd rate **{thing}** a **{score}/100**.")

    @commands.command(name="ship")
    async def ship(self, ctx, member1: discord.Member, member2: discord.Member = None):
        member2 = member2 or ctx.author
        compatibility = random.randint(0, 100)

        bar_len = 10
        filled = int(bar_len * compatibility / 100)
        bar = "❤️" * filled + "🖤" * (bar_len - filled)

        embed = discord.Embed(
            title="💘 Ship Calculator",
            description=(
                f"{member1.mention} + {member2.mention}\n\n"
                f"{bar}\n**{compatibility}%** compatible"
            ),
            color=discord.Color.from_rgb(255, 105, 180)
        )
        await ctx.send(embed=embed)

    @commands.command(name="compliment")
    async def compliment(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        await ctx.send(f"✨ {member.mention} {random.choice(COMPLIMENTS)}")

    @commands.command(name="roast")
    async def roast(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        await ctx.send(f"😂 {member.mention} {random.choice(ROASTS)}")

    # ------------------------------------------------------------
    @commands.command(name="stats")
    async def stats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)

        embed = discord.Embed(
            title=f"📊 {member.display_name}'s Stats", color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💬 Messages", value=f"{user['messages']:,}", inline=True)
        embed.add_field(name="⭐ Level", value=user["level"], inline=True)
        embed.add_field(name="✨ Total XP", value=f"{user['xp']:,}", inline=True)
        embed.add_field(name="🎮 Games Played", value=f"{user['games']:,}", inline=True)
        embed.add_field(name="🏆 Wins", value=f"{user['wins']:,}", inline=True)
        embed.add_field(name="💰 Coins", value=f"{user['balance']:,}", inline=True)
        embed.add_field(
            name="🏅 Achievements", value=f"{len(user['achievements'])}", inline=True
        )
        embed.add_field(
            name="🔥 Daily Streak", value=f"{user['daily_streak']} days", inline=True
        )

        await ctx.send(embed=footer(embed, ctx))


async def setup(bot):
    await bot.add_cog(Fun(bot))
