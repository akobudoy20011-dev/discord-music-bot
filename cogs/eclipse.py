"""
cogs/eclipse.py
===============
ECLIPSE meta systems: richer identity/titles, communal world events,
banking, and a native game-room hub.
"""

import random
import time

import discord
from discord.ext import commands

from constants import COLOR_GOLD, COLOR_PRIMARY, footer, ACHIEVEMENTS, rank_title
from ui.panels import game_room_embed


TITLE_RULES = {
    "Newcomer": lambda u: int(u["level"]) >= 1,
    "Member": lambda u: int(u["level"]) >= 5,
    "Regular": lambda u: int(u["level"]) >= 10,
    "Veteran": lambda u: int(u["level"]) >= 20,
    "Elite": lambda u: int(u["level"]) >= 30,
    "Legend": lambda u: int(u["level"]) >= 50,
    "Mythic": lambda u: int(u["level"]) >= 100,
    "Dedicated": lambda u: "Dedicated" in u["achievements"],
    "Unstoppable": lambda u: "Unstoppable" in u["achievements"],
    "Gambler": lambda u: "Gambler" in u["achievements"],
    "Champion": lambda u: "Champion" in u["achievements"],
    "First Blood": lambda u: "First Blood" in u["achievements"],
    "Arcade Veteran": lambda u: "Arcade Veteran" in u["achievements"],
    "High Roller": lambda u: "High Roller" in u["achievements"],
    "Tenfold": lambda u: "Tenfold" in u["achievements"],
    "Arcade Tycoon": lambda u: "Arcade Tycoon" in u["achievements"],
    "Legend of the Server": lambda u: "Legend of the Server" in u["achievements"],
}


WORLD_EVENTS = [
    {
        "id": "moonfall",
        "title": "🌙 MOONFALL",
        "description": "The night sky is thinning. The server must feed the lunar seal before it breaks.",
        "target": 5000,
        "reward_coins": 1000,
        "reward_xp": 100,
    },
    {
        "id": "starforge",
        "title": "✦ STARFORGE",
        "description": "A dormant star has fallen into ECLIPSE territory. Collective wealth can awaken it.",
        "target": 7500,
        "reward_coins": 1500,
        "reward_xp": 150,
    },
    {
        "id": "veilbreak",
        "title": "🪽 VEILBREAK",
        "description": "The Veil is collapsing. Every contribution strengthens the boundary between worlds.",
        "target": 10000,
        "reward_coins": 2000,
        "reward_xp": 200,
    },
]


class GameRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Luck", emoji="🎲", style=discord.ButtonStyle.primary)
    async def luck(self, interaction, button):
        await interaction.response.send_message(
            "🎲 Luck chamber: !roll, !coinflip, !slots, !guess",
            ephemeral=True,
        )

    @discord.ui.button(label="Cards", emoji="🃏", style=discord.ButtonStyle.secondary)
    async def cards(self, interaction, button):
        await interaction.response.send_message(
            "🃏 Card table: !blackjack",
            ephemeral=True,
        )

    @discord.ui.button(label="Mind", emoji="🧠", style=discord.ButtonStyle.secondary)
    async def mind(self, interaction, button):
        await interaction.response.send_message(
            "🧠 Mind games: !trivia, !riddle, !math, !8ball",
            ephemeral=True,
        )

    @discord.ui.button(label="RPG", emoji="⚔️", style=discord.ButtonStyle.success)
    async def rpg(self, interaction, button):
        await interaction.response.send_message(
            "⚔️ RPG: !rpg profile, !rpg adventure, !rpg battle, !rpg world",
            ephemeral=True,
        )

    @discord.ui.button(label="Profile", emoji="♡", style=discord.ButtonStyle.secondary)
    async def profile(self, interaction, button):
        await interaction.response.send_message(
            "♡ Use !profile, !identity, !titles, or !rank to inspect your ECLIPSE identity.",
            ephemeral=True,
        )


class Eclipse(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def _ensure_event(self, guild_id):
        event = await self.db.get_world_event(guild_id)
        now = time.time()
        if event and not event["completed"] and float(event["ends_at"]) > now:
            return event
        spec = random.choice(WORLD_EVENTS)
        return await self.db.create_world_event(
            guild_id,
            spec["id"],
            spec["title"],
            spec["description"],
            spec["target"],
            spec["reward_coins"],
            spec["reward_xp"],
            now + 7 * 24 * 3600,
        )

    def _available_titles(self, user):
        return [name for name, rule in TITLE_RULES.items() if rule(user)]

    @commands.command(name="identity", aliases=["idcard", "eclipseprofile"])
    async def identity(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        position = await self.db.rank_position(ctx.guild.id, member.id, "level")
        titles = self._available_titles(user)
        equipped = user.get("equipped_title") or rank_title(user["level"])
        embed = discord.Embed(
            title=f"♡ {member.display_name} · ECLIPSE IDENTITY ♡",
            description=f"**{equipped}**\n\nLevel **{user['level']}** · Server rank **#{position}**",
            color=COLOR_PRIMARY,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="✨ XP", value=f"{user['xp']:,} / {user['level']*100:,}", inline=True)
        embed.add_field(name="💰 Coins", value=f"{user['balance']:,}", inline=True)
        embed.add_field(name="🏦 Bank", value=f"{user['bank_balance']:,}", inline=True)
        embed.add_field(name="🔥 Streak", value=f"{user['daily_streak']} day(s)", inline=True)
        embed.add_field(name="💬 Messages", value=f"{user['messages']:,}", inline=True)
        embed.add_field(name="🏆 Wins", value=f"{user['wins']:,}", inline=True)
        embed.add_field(name="🏅 Achievements", value=f"{len(user['achievements'])}/{len(ACHIEVEMENTS)}", inline=False)
        embed.add_field(name="🎖️ Titles", value=", ".join(titles[:8]) + ("…" if len(titles) > 8 else ""), inline=False)
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="titles")
    async def titles(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        titles = self._available_titles(user)
        equipped = user.get("equipped_title") or rank_title(user["level"])
        lines = [f"{'👑' if t == equipped else '◇'} {t}" for t in titles]
        embed = discord.Embed(
            title=f"🎖️ {member.display_name}'s Titles",
            description="\n".join(lines) if lines else "No titles unlocked yet.",
            color=COLOR_GOLD,
        )
        embed.set_footer(text="Use !title <title name> to equip an unlocked title.")
        await ctx.send(embed=embed)

    @commands.command(name="title")
    async def title(self, ctx, *, requested: str = None):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        titles = self._available_titles(user)
        if not requested:
            equipped = user.get("equipped_title") or rank_title(user["level"])
            await ctx.send(f"🎖️ Equipped title: **{equipped}**")
            return
        match = next((t for t in titles if t.lower() == requested.strip().lower()), None)
        if not match:
            await ctx.send("🔒 That title is not unlocked yet. Use !titles to see what you have.")
            return
        await self.db.set_equipped_title(ctx.guild.id, ctx.author.id, match)
        await ctx.send(f"👑 Equipped **{match}**.")

    @commands.command(name="worldevent", aliases=["world", "event"])
    async def worldevent(self, ctx, action: str = None, amount: int = None):
        event = await self._ensure_event(ctx.guild.id)
        if action and action.lower() in {"contribute", "offer", "feed"}:
            if amount is None:
                await ctx.send("Use !worldevent contribute <amount>.")
                return
            ok, result = await self.db.contribute_world_event(ctx.guild.id, ctx.author.id, amount)
            if not ok:
                await ctx.send("❌ Contribution failed: the amount is invalid, your balance is too low, or the event expired.")
                return
            event = result
            if event["completed"]:
                rewarded = await self.db.reward_world_event_contributors(ctx.guild.id)
                await ctx.send(f"🌌 **{event['title']}** is complete. {rewarded} contributor(s) received the completion reward.")
            else:
                await ctx.send(f"✦ Contribution accepted: **{amount:,}**. Progress: **{event['progress']:,}/{event['target']:,}**.")
            return

        remaining = max(0, int(float(event["ends_at"]) - time.time()))
        embed = discord.Embed(
            title=f"🌌 {event['title']}",
            description=event["description"],
            color=COLOR_PRIMARY,
        )
        embed.add_field(name="Collective Progress", value=f"{event['progress']:,} / {event['target']:,}", inline=True)
        embed.add_field(name="Time Remaining", value=f"{remaining // 86400}d {(remaining % 86400)//3600}h", inline=True)
        embed.add_field(name="Completion Reward", value=f"{event['reward_coins']:,} coins + {event['reward_xp']} XP", inline=False)
        embed.set_footer(text="Contribute with !worldevent contribute <amount>")
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="gameroom", aliases=["gamehub", "gamesroom"])
    async def gameroom(self, ctx):
        await ctx.send(embed=game_room_embed(), view=GameRoomView())


async def setup(bot):
    await bot.add_cog(Eclipse(bot))
