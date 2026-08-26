"""
cogs/help.py
============
A categorized !help embed instead of discord.py's plain default.
"""

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY


class Help(commands.Cog):
    """The !help command."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["commands"])
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="🤖 MUSIC DELIVERY",
            description="Your all-in-one Discord bot.",
            color=COLOR_PRIMARY
        )

        embed.add_field(
            name="🎵 Music",
            value=(
                "`!play <song>` • `!download <song>`\n"
                "`!join` • `!leave`\n"
                "`!pause` • `!resume` • `!skip` • `!stop`\n"
                "`!queue` • `!nowplaying` • `!volume <0-200>`\n"
                "`!loop <off/single/queue>` • `!shuffle`"
            ),
            inline=False
        )

        embed.add_field(
            name="⭐ Leveling",
            value=(
                "`!rank` • `!profile` • `!stats`\n"
                "`!xpleaderboard` • `!achievements`"
            ),
            inline=False
        )

        embed.add_field(
            name="💰 Economy",
            value=(
                "`!balance` • `!daily` • `!work`\n"
                "`!pay @user <amount>` • `!leaderboard`\n"
                "`!shop` • `!buy <item>` • `!inventory`"
            ),
            inline=False
        )

        embed.add_field(
            name="🎮 Games",
            value=(
                "`!games` • `!trivia` • `!rps <choice>`\n"
                "`!roll [sides]` • `!guess <1-10>`\n"
                "`!coinflip <heads/tails> <bet>` • `!slots <bet>`\n"
                "`!blackjack <bet>` • `!8ball <question>`"
            ),
            inline=False
        )

        embed.add_field(
            name="🎉 Fun",
            value=(
                "`!avatar` • `!userinfo` • `!serverinfo`\n"
                "`!choose a, b, c` • `!rate <thing>`\n"
                "`!ship @user1 @user2` • `!compliment` • `!roast`"
            ),
            inline=False
        )

        embed.add_field(
            name="🤖 AI",
            value="`!chat <message>` (aliases: `!ask`, `!ai`)",
            inline=False
        )

        embed.add_field(
            name="🛡️ Moderation (staff only)",
            value=(
                "`!kick` • `!ban` • `!unban` • `!mute <member> <minutes>`\n"
                "`!warn` • `!warnings` • `!clearwarnings` • `!clear <amount>`\n"
                "`!config` — server settings"
            ),
            inline=False
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
