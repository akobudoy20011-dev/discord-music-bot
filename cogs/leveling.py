"""
cogs/leveling.py
=================
XP-on-message leveling, !rank, !profile, XP leaderboard,
and owner-only level management.
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

# ============================================================
# BOT OWNER
# ============================================================

OWNER_ID = 1416702999421784104


def xp_bar(current, maximum, length=14):
    if maximum <= 0:
        return "█" * length

    filled = int(length * min(current / maximum, 1))

    return "█" * filled + "░" * (length - filled)


class Leveling(commands.Cog):
    """Chat XP, levels, ranks, profiles, and level management."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self._xp_cooldowns = {}

    # ------------------------------------------------------------
    # XP ON MESSAGE
    # ------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        config = await self.db.get_guild_config(message.guild.id)

        user = await self.db.get_user(
            message.guild.id,
            message.author.id
        )

        await self.db.update_user(
            message.guild.id,
            message.author.id,
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
            message.guild.id,
            message.author.id,
            amount
        )

        if new_level > old_level:
            for reached_level in range(old_level + 1, new_level + 1):
                await self.db.grant_level_milestone(
                    message.guild.id,
                    message.author.id,
                    reached_level
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
                message.guild.id,
                message.author.id
            )

            class _FakeCtx:
                pass

            fake_ctx = _FakeCtx()
            fake_ctx.guild = message.guild
            fake_ctx.channel = channel
            fake_ctx.author = message.author

            await check_achievements(
                self.db,
                fake_ctx,
                message.author,
                fresh_user
            )

    # ------------------------------------------------------------
    # RANK
    # ------------------------------------------------------------

    @commands.command(name="rank", aliases=["level", "lvl", "xp"])
    async def rank(
        self,
        ctx,
        member: discord.Member = None
    ):
        member = member or ctx.author

        user = await self.db.get_user(
            ctx.guild.id,
            member.id
        )

        position = await self.db.rank_position(
            ctx.guild.id,
            member.id,
            "level"
        )

        needed = user["level"] * 100

        bar = xp_bar(
            user["xp"],
            needed
        )

        embed = discord.Embed(
            title=f"⭐ {member.display_name}'s Rank",
            color=COLOR_PRIMARY
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="⭐ Level",
            value=f"**{user['level']}**",
            inline=True
        )

        embed.add_field(
            name="🎖️ Title",
            value=f"**{rank_title(user['level'])}**",
            inline=True
        )

        embed.add_field(
            name="🏆 Server Rank",
            value=f"**#{position}**",
            inline=True
        )

        embed.add_field(
            name="✨ XP",
            value=f"**{user['xp']:,} / {needed:,}**",
            inline=False
        )

        embed.add_field(
            name="Progress",
            value=f"`{bar}`",
            inline=False
        )

        progression = await self.db.get_level_progression(ctx.guild.id, member.id)
        embed.add_field(
            name="♛ Prestige",
            value=f"{int(progression['prestige'])} • {float(progression['xp_boost']):.0%} XP",
            inline=True
        )
        embed.add_field(
            name="📈 Lifetime XP",
            value=f"{int(progression['total_xp']):,}",
            inline=True
        )

        await ctx.send(
            embed=footer(embed, ctx)
        )

    # ------------------------------------------------------------
    # PROFILE
    # ------------------------------------------------------------

    @commands.command(name="profile", aliases=["me"])
    async def profile(
        self,
        ctx,
        member: discord.Member = None
    ):
        member = member or ctx.author

        user = await self.db.get_user(
            ctx.guild.id,
            member.id
        )

        position = await self.db.rank_position(
            ctx.guild.id,
            member.id,
            "level"
        )

        needed = user["level"] * 100

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=COLOR_PRIMARY
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="⭐ Level",
            value=user["level"],
            inline=True
        )

        embed.add_field(
            name="🎖️ Rank",
            value=rank_title(user["level"]),
            inline=True
        )

        embed.add_field(
            name="🏆 Server Rank",
            value=f"#{position}",
            inline=True
        )

        embed.add_field(
            name="✨ XP",
            value=f"{user['xp']:,} / {needed:,}",
            inline=True
        )

        embed.add_field(
            name="💰 Coins",
            value=f"{user['balance']:,}",
            inline=True
        )

        embed.add_field(
            name="🔥 Daily Streak",
            value=f"{user['daily_streak']} days",
            inline=True
        )

        progression = await self.db.get_level_progression(ctx.guild.id, member.id)

        embed.add_field(
            name="♛ Prestige",
            value=f"{int(progression['prestige'])} • {float(progression['xp_boost']):.0%} XP",
            inline=True
        )
        embed.add_field(
            name="📈 Lifetime XP",
            value=f"{int(progression['total_xp']):,}",
            inline=True
        )

        embed.add_field(
            name="💬 Messages",
            value=f"{user['messages']:,}",
            inline=True
        )

        embed.add_field(
            name="🎮 Games Played",
            value=f"{user['games']:,}",
            inline=True
        )

        embed.add_field(
            name="🏆 Wins",
            value=f"{user['wins']:,}",
            inline=True
        )

        embed.add_field(
            name=f"🏅 Achievements ({len(user['achievements'])})",
            value=(
                ", ".join(user["achievements"][:8])
                + ("…" if len(user["achievements"]) > 8 else "")
                if user["achievements"]
                else "None yet — try `!achievements`"
            ),
            inline=False
        )

        await ctx.send(
            embed=footer(embed, ctx)
        )

    # ------------------------------------------------------------
    # ADVANCED PROGRESSION
    # ------------------------------------------------------------

    @commands.command(name="progression", aliases=["progress", "progressioninfo"])
    async def progression(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        state = await self.db.get_level_progression(ctx.guild.id, member.id)
        level = int(user["level"])
        current_xp = int(user["xp"])
        needed = level * 100
        prestige = int(state["prestige"])
        boost = float(state["xp_boost"])
        lifetime = int(state["total_xp"])
        claimed = int(state["milestone_claimed"])
        next_milestone = ((max(level, 9) // 10) + 1) * 10
        if level >= 100:
            next_milestone = 100

        embed = discord.Embed(
            title=f"📈 {member.display_name}'s Progression",
            description=(
                f"Level {level} • {rank_title(level)}\n"
                f"XP {current_xp:,}/{needed:,}"
            ),
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="♛ Prestige", value=f"{prestige}", inline=True)
        embed.add_field(name="✨ XP Multiplier", value=f"{boost:.0%}", inline=True)
        embed.add_field(name="📚 Lifetime XP", value=f"{lifetime:,}", inline=True)
        embed.add_field(name="🎁 Milestones", value=f"Claimed through Level {claimed}", inline=True)
        embed.add_field(
            name="🏁 Next Milestone",
            value="Prestige available" if level >= 100 else f"Level {next_milestone} • {next_milestone * 100:,} coins",
            inline=True
        )
        embed.add_field(
            name="♛ Prestige Requirement",
            value="Ready — Level 100 reached. Use !prestige." if level >= 100 else f"Reach Level 100 ({100 - level} levels remaining).",
            inline=True
        )
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="prestige", aliases=["prestigeup", "rebirth"])
    async def prestige(self, ctx):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if int(user["level"]) < 100:
            await ctx.send(
                f"You need Level 100 to prestige. You are currently Level {int(user['level'])}."
            )
            return
        new_prestige = await self.db.prestige_user(ctx.guild.id, ctx.author.id)
        if new_prestige is None:
            await ctx.send("Prestige could not be completed.")
            return
        reward = 10_000
        await self.db.add_balance(ctx.guild.id, ctx.author.id, reward)
        state = await self.db.get_level_progression(ctx.guild.id, ctx.author.id)
        embed = discord.Embed(
            title="♛ PRESTIGE ASCENDED",
            description=(
                f"{ctx.author.mention} has entered Prestige {new_prestige}.\n\n"
                "Your level has returned to 1, while lifetime XP is preserved.\n"
                f"Your XP gain is now {float(state['xp_boost']):.0%}."
            ),
            color=COLOR_GOLD
        )
        embed.add_field(name="💰 Ascension Reward", value=f"+{reward:,} coins", inline=True)
        embed.add_field(name="📈 Lifetime XP", value=f"{int(state['total_xp']):,}", inline=True)
        embed.add_field(name="🎁 Next Milestone", value="Level 10", inline=True)
        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    # OWNER-ONLY SET LEVEL
    # ------------------------------------------------------------

    @commands.command(name="setlevel")
    async def set_level(
        self,
        ctx,
        member: discord.Member,
        level: int
    ):
        """
        Owner-only command.

        Usage:
        !setlevel @user 10
        """

        # Only the bot owner ID can use this command.
        if ctx.author.id != OWNER_ID:
            await ctx.send(
                "❌ You don't have permission to use this command."
            )
            return

        # Prevent invalid levels.
        if level < 1:
            await ctx.send(
                "❌ Level must be 1 or higher."
            )
            return

        # Make sure the user's database entry exists.
        await self.db.get_user(
            ctx.guild.id,
            member.id
        )

        # Set the level directly.
        await self.db.update_user(
            ctx.guild.id,
            member.id,
            level=level,
            xp=0
        )

        await ctx.send(
            f"✅ Set {member.mention}'s level to **{level}** "
            f"— *{rank_title(level)}*"
        )

    # ------------------------------------------------------------
    # XP LEADERBOARD
    # ------------------------------------------------------------

    @commands.command(
        name="xpleaderboard",
        aliases=["xplb", "levels", "levelboard"]
    )
    async def xp_leaderboard(self, ctx):

        top = await self.db.leaderboard(
            ctx.guild.id,
            order_by="level",
            limit=10
        )

        if not top:
            await ctx.send(
                "📊 Nobody has earned XP yet."
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []

        for i, data in enumerate(top, start=1):

            member = ctx.guild.get_member(
                int(data["user_id"])
            )

            name = (
                member.display_name
                if member
                else f"User {data['user_id']}"
            )

            prefix = (
                medals[i - 1]
                if i <= 3
                else f"**{i}.**"
            )

            lines.append(
                f"{prefix} **{name}** — "
                f"Level `{data['level']}` "
                f"• `{data['xp']} XP`"
            )

        embed = discord.Embed(
            title="🏆 XP Leaderboard",
            description="\n".join(lines),
            color=COLOR_GOLD
        )

        await ctx.send(
            embed=footer(embed, ctx)
        )

    # ------------------------------------------------------------
    # ACHIEVEMENTS
    # ------------------------------------------------------------

    @commands.command(
        name="achievements",
        aliases=["badges"]
    )
    async def achievements(
        self,
        ctx,
        member: discord.Member = None
    ):
        member = member or ctx.author

        user = await self.db.get_user(
            ctx.guild.id,
            member.id
        )

        lines = []

        for name, data in ACHIEVEMENTS.items():

            status = (
                "✅"
                if name in user["achievements"]
                else "🔒"
            )

            lines.append(
                f"{status} {data['emoji']} "
                f"**{name}** — {data['description']}"
            )

        embed = discord.Embed(
            title=(
                f"🏅 Achievements "
                f"({len(user['achievements'])}/"
                f"{len(ACHIEVEMENTS)})"
            ),
            description="\n".join(lines),
            color=COLOR_GOLD
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        await ctx.send(
            embed=footer(embed, ctx)
        )


async def setup(bot):
    await bot.add_cog(Leveling(bot))
