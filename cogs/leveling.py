"""
cogs/leveling.py
=================
XP-on-message leveling, !rank, !profile, and the XP leaderboard.
"""

import random
import time

import discord
from discord.ext import commands

from constants import (
    COLOR_PRIMARY, COLOR_GOLD, rank_title, footer,
    check_achievements, ACHIEVEMENTS
)

XP_MIN = 8
XP_MAX = 18
XP_COOLDOWN = 45  # seconds between XP awards per user, anti-spam


def xp_bar(current, maximum, length=14):
    if maximum <= 0:
        return "█" * length
    filled = int(length * min(current / maximum, 1))
    return "█" * filled + "░" * (length - filled)


class Leveling(commands.Cog):
    """Chat XP, levels, ranks, and profiles."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self._xp_cooldowns = {}

    # ------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        config = await self.db.get_guild_config(message.guild.id)

        user = await self.db.get_user(message.guild.id, message.author.id)
        await self.db.update_user(
            message.guild.id, message.author.id,
            messages=user["messages"] + 1
        )

        if not config["xp_enabled"]:
            return

        key = f"{message.guild.id}:{message.author.id}"
        now = time.time()

        if now - self._xp_cooldowns.get(key, 0) < XP_COOLDOWN:
            return

        self._xp_cooldowns[key] = now

        amount = random.randint(XP_MIN, XP_MAX)
        old_level, new_level, _ = await self.db.add_xp(
            message.guild.id, message.author.id, amount
        )

        if new_level > old_level and config["level_announce"]:
            channel = message.channel

            if config["level_channel_id"]:
                configured = message.guild.get_channel(
                    int(config["level_channel_id"])
                )
                if configured:
                    channel = configured

            embed = discord.Embed(
                title="🎉 Level Up!",
                description=(
                    f"{message.author.mention} reached "
                    f"**Level {new_level}** — "
                    f"*{rank_title(new_level)}*"
                ),
                color=COLOR_GOLD
            )
            await channel.send(embed=embed)

            fresh_user = await self.db.get_user(
                message.guild.id, message.author.id
            )

            class _FakeCtx:
                pass

            fake_ctx = _FakeCtx()
            fake_ctx.guild = message.guild
            fake_ctx.channel = channel
            fake_ctx.author = message.author

            await check_achievements(self.db, fake_ctx, message.author, fresh_user)

    # ------------------------------------------------------------
    @commands.command(name="rank", aliases=["level", "lvl", "xp"])
    async def rank(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        position = await self.db.rank_position(ctx.guild.id, member.id, "level")

        needed = user["level"] * 100
        bar = xp_bar(user["xp"], needed)

        embed = discord.Embed(
            title=f"⭐ {member.display_name}'s Rank",
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="⭐ Level", value=f"**{user['level']}**", inline=True)
        embed.add_field(
            name="🎖️ Title", value=f"**{rank_title(user['level'])}**", inline=True
        )
        embed.add_field(name="🏆 Server Rank", value=f"**#{position}**", inline=True)
        embed.add_field(
            name="✨ XP", value=f"**{user['xp']:,} / {needed:,}**", inline=False
        )
        embed.add_field(name="Progress", value=f"`{bar}`", inline=False)

        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    @commands.command(name="profile", aliases=["me"])
    async def profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        position = await self.db.rank_position(ctx.guild.id, member.id, "level")
        needed = user["level"] * 100

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="⭐ Level", value=user["level"], inline=True)
        embed.add_field(name="🎖️ Rank", value=rank_title(user["level"]), inline=True)
        embed.add_field(name="🏆 Server Rank", value=f"#{position}", inline=True)

        embed.add_field(
            name="✨ XP", value=f"{user['xp']:,} / {needed:,}", inline=True
        )
        embed.add_field(name="💰 Coins", value=f"{user['balance']:,}", inline=True)
        embed.add_field(
            name="🔥 Daily Streak", value=f"{user['daily_streak']} days", inline=True
        )

        embed.add_field(name="💬 Messages", value=f"{user['messages']:,}", inline=True)
        embed.add_field(name="🎮 Games Played", value=f"{user['games']:,}", inline=True)
        embed.add_field(name="🏆 Wins", value=f"{user['wins']:,}", inline=True)

        embed.add_field(
            name=f"🏅 Achievements ({len(user['achievements'])})",
            value=(
                ", ".join(user["achievements"][:8]) + ("…" if len(user["achievements"]) > 8 else "")
                if user["achievements"] else "None yet — try `!achievements`"
            ),
            inline=False
        )

        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    @commands.command(name="xpleaderboard", aliases=["xplb", "levels", "levelboard"])
    async def xp_leaderboard(self, ctx):
        top = await self.db.leaderboard(ctx.guild.id, order_by="level", limit=10)

        if not top:
            await ctx.send("📊 Nobody has earned XP yet.")
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []

        for i, data in enumerate(top, start=1):
            member = ctx.guild.get_member(int(data["user_id"]))
            name = member.display_name if member else f"User {data['user_id']}"
            prefix = medals[i - 1] if i <= 3 else f"**{i}.**"
            lines.append(
                f"{prefix} **{name}** — Level `{data['level']}` "
                f"• `{data['xp']} XP`"
            )

        embed = discord.Embed(
            title="🏆 XP Leaderboard",
            description="\n".join(lines),
            color=COLOR_GOLD
        )
        await ctx.send(embed=footer(embed, ctx))


    # ------------------------------------------------------------
    @commands.command(name="achievements", aliases=["badges"])
    async def achievements(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)

        lines = []

        for name, data in ACHIEVEMENTS.items():
            status = "✅" if name in user["achievements"] else "🔒"
            lines.append(f"{status} {data['emoji']} **{name}** — {data['description']}")

        embed = discord.Embed(
            title=f"🏅 Achievements ({len(user['achievements'])}/{len(ACHIEVEMENTS)})",
            description="\n".join(lines),
            color=COLOR_GOLD
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=footer(embed, ctx))


async def setup(bot):
    await bot.add_cog(Leveling(bot))
