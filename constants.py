"""
constants.py
============
Shared data used by more than one cog: achievement definitions, level
rank titles, and the color palette so every embed looks consistent.
"""

import discord

# ------------------------------------------------------------------
# BRAND / EMBED COLORS
# ------------------------------------------------------------------

COLOR_PRIMARY = discord.Color.from_rgb(88, 101, 242)     # blurple
COLOR_SUCCESS = discord.Color.from_rgb(87, 242, 135)      # green
COLOR_WARNING = discord.Color.from_rgb(254, 231, 92)      # yellow
COLOR_DANGER = discord.Color.from_rgb(237, 66, 69)        # red
COLOR_GOLD = discord.Color.from_rgb(255, 200, 87)
COLOR_MUSIC = discord.Color.from_rgb(235, 69, 158)


def footer(embed, ctx):
    embed.set_footer(
        text=f"Requested by {ctx.author.display_name}",
        icon_url=ctx.author.display_avatar.url
    )
    return embed


# ------------------------------------------------------------------
# ACHIEVEMENTS
# Each requirement receives the user dict from database.get_user().
# ------------------------------------------------------------------

ACHIEVEMENTS = {
    # Social
    "First Message": {
        "emoji": "💬",
        "description": "Send your first message.",
        "requirement": lambda u: u["messages"] >= 1
    },
    "Chatty": {
        "emoji": "💬",
        "description": "Send 100 messages.",
        "requirement": lambda u: u["messages"] >= 100
    },
    "Veteran": {
        "emoji": "💬",
        "description": "Send 1,000 messages.",
        "requirement": lambda u: u["messages"] >= 1000
    },
    "Legend of the Server": {
        "emoji": "💬",
        "description": "Send 10,000 messages.",
        "requirement": lambda u: u["messages"] >= 10000
    },

    # Leveling
    "Getting Started": {
        "emoji": "⭐",
        "description": "Reach Level 5.",
        "requirement": lambda u: u["level"] >= 5
    },
    "Regular": {
        "emoji": "⭐",
        "description": "Reach Level 10.",
        "requirement": lambda u: u["level"] >= 10
    },
    "Veteran Member": {
        "emoji": "⭐",
        "description": "Reach Level 25.",
        "requirement": lambda u: u["level"] >= 25
    },
    "Legend": {
        "emoji": "⭐",
        "description": "Reach Level 50.",
        "requirement": lambda u: u["level"] >= 50
    },

    # Economy
    "First Grand": {
        "emoji": "💰",
        "description": "Have 1,000 coins.",
        "requirement": lambda u: u["balance"] >= 1000
    },
    "Rich": {
        "emoji": "💰",
        "description": "Have 10,000 coins.",
        "requirement": lambda u: u["balance"] >= 10000
    },
    "Wealthy": {
        "emoji": "💰",
        "description": "Have 100,000 coins.",
        "requirement": lambda u: u["balance"] >= 100000
    },

    # Games
    "Gambler": {
        "emoji": "🎮",
        "description": "Play 25 games.",
        "requirement": lambda u: u["games"] >= 25
    },
    "Winner": {
        "emoji": "🏆",
        "description": "Win 10 games.",
        "requirement": lambda u: u["wins"] >= 10
    },
    "Champion": {
        "emoji": "🏆",
        "description": "Win 100 games.",
        "requirement": lambda u: u["wins"] >= 100
    },

    # Streaks
    "Dedicated": {
        "emoji": "🔥",
        "description": "Reach a 7-day daily streak.",
        "requirement": lambda u: u["daily_streak"] >= 7
    },
    "Unstoppable": {
        "emoji": "🔥",
        "description": "Reach a 30-day daily streak.",
        "requirement": lambda u: u["daily_streak"] >= 30
    }
}


async def check_achievements(db, ctx, member, user=None):
    """
    Checks `member`'s stats against ACHIEVEMENTS, unlocks any newly
    earned ones, announces them in ctx.channel, and returns the
    (possibly refreshed) user dict.
    """

    if user is None:
        user = await db.get_user(ctx.guild.id, member.id)

    newly_unlocked = []

    for name, achievement in ACHIEVEMENTS.items():

        if name in user["achievements"]:
            continue

        if achievement["requirement"](user):
            unlocked = await db.add_achievement(
                ctx.guild.id, member.id, name
            )

            if unlocked:
                newly_unlocked.append(name)

    if newly_unlocked:
        user = await db.get_user(ctx.guild.id, member.id)

        for name in newly_unlocked:
            emoji = ACHIEVEMENTS[name]["emoji"]

            embed = discord.Embed(
                title=f"{emoji} Achievement Unlocked!",
                description=f"**{name}**\n{ACHIEVEMENTS[name]['description']}",
                color=COLOR_GOLD
            )
            embed.set_author(
                name=member.display_name,
                icon_url=member.display_avatar.url
            )

            await ctx.channel.send(
                content=member.mention,
                embed=embed
            )

    return user


# ------------------------------------------------------------------
# LEVEL RANK TITLES
# ------------------------------------------------------------------

RANK_TITLES = [
    (100, "Mythic"),
    (50, "Legend"),
    (30, "Elite"),
    (20, "Veteran"),
    (10, "Regular"),
    (5, "Member"),
    (1, "Newcomer")
]


def rank_title(level):
    for threshold, title in RANK_TITLES:
        if level >= threshold:
            return title
    return "Newcomer"
