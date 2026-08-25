import os
import json
import random
import asyncio
import logging
import time

from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
import yt_dlp
import aiohttp
from aiohttp import web
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")


# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# ============================================================
# FILE STORAGE
# ============================================================

ECONOMY_FILE = "economy.json"
LEVEL_FILE = "levels.json"
SHOP_FILE = "shop.json"


def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


economy = load_json(ECONOMY_FILE, {})
levels = load_json(LEVEL_FILE, {})
inventories = load_json(SHOP_FILE, {})


# ============================================================
# USER DATA
# ============================================================

STARTING_BALANCE = 100

DAILY_AMOUNT = 200
DAILY_COOLDOWN = timedelta(hours=24)

WORK_MIN = 50
WORK_MAX = 150
WORK_COOLDOWN = timedelta(hours=1)


def get_user(user_id):
    user_id = str(user_id)

    if user_id not in economy:
        economy[user_id] = {
            "balance": STARTING_BALANCE,
            "last_daily": None,
            "last_work": None,
            "messages": 0,
            "wins": 0,
            "games": 0,
            "achievements": []
        }

    user = economy[user_id]

    user.setdefault("balance", STARTING_BALANCE)
    user.setdefault("last_daily", None)
    user.setdefault("last_work", None)
    user.setdefault("messages", 0)
    user.setdefault("wins", 0)
    user.setdefault("games", 0)
    user.setdefault("achievements", [])

    return user


def save_economy():
    save_json(ECONOMY_FILE, economy)


# ============================================================
# LEVELING
# ============================================================

XP_MIN = 8
XP_MAX = 18
XP_COOLDOWN = 45

xp_cooldowns = {}


def get_level_data(guild_id, user_id):
    guild_id = str(guild_id)
    user_id = str(user_id)

    if guild_id not in levels:
        levels[guild_id] = {}

    if user_id not in levels[guild_id]:
        levels[guild_id][user_id] = {
            "xp": 0,
            "level": 1
        }

    return levels[guild_id][user_id]


def xp_required(level):
    return level * 100


def add_xp(member, amount=None):
    guild_id = str(member.guild.id)
    user_id = str(member.id)

    data = get_level_data(guild_id, user_id)

    old_level = data["level"]

    if amount is None:
        amount = random.randint(XP_MIN, XP_MAX)

    data["xp"] += amount

    while data["xp"] >= xp_required(data["level"]):
        data["xp"] -= xp_required(data["level"])
        data["level"] += 1

    save_json(LEVEL_FILE, levels)

    return amount, old_level, data["level"]


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild:

        user = get_user(message.author.id)
        user["messages"] += 1

        now = time.time()
        key = f"{message.guild.id}:{message.author.id}"

        if now - xp_cooldowns.get(key, 0) >= XP_COOLDOWN:

            xp_cooldowns[key] = now

            amount, old_level, new_level = add_xp(
                message.author
            )

            if new_level > old_level:
                await message.channel.send(
                    f"🎉 {message.author.mention} "
                    f"**LEVEL UP!**\n"
                    f"⭐ You reached **Level {new_level}**!"
                )

        save_economy()

    await bot.process_commands(message)


# ============================================================
# RANK
# ============================================================

def make_xp_bar(current, maximum, length=12):

    if maximum <= 0:
        return "█" * length

    percentage = min(current / maximum, 1)

    filled = int(length * percentage)

    return "█" * filled + "░" * (length - filled)


@bot.command(name="rank", aliases=["level", "lvl"])
async def rank(ctx, member: discord.Member = None):

    member = member or ctx.author

    data = get_level_data(
        ctx.guild.id,
        member.id
    )

    guild_data = levels.get(
        str(ctx.guild.id),
        {}
    )

    ranking = sorted(
        guild_data.items(),
        key=lambda x: (
            x[1].get("level", 1),
            x[1].get("xp", 0)
        ),
        reverse=True
    )

    position = 1

    for i, (uid, _) in enumerate(ranking, 1):
        if uid == str(member.id):
            position = i
            break

    needed = xp_required(data["level"])
    xp = data["xp"]

    bar = make_xp_bar(xp, needed)

    embed = discord.Embed(
        title=f"⭐ {member.display_name}'s Rank",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="⭐ Level",
        value=f"**{data['level']}**",
        inline=True
    )

    embed.add_field(
        name="✨ XP",
        value=f"**{xp:,} / {needed:,}**",
        inline=True
    )

    embed.add_field(
        name="🏆 Server Rank",
        value=f"**#{position}**",
        inline=True
    )

    embed.add_field(
        name="Progress",
        value=f"`{bar}`",
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command(name="profile", aliases=["me"])
async def profile(ctx, member: discord.Member = None):

    member = member or ctx.author

    user = get_user(member.id)

    level_data = get_level_data(
        ctx.guild.id,
        member.id
    )

    achievements = user["achievements"]

    embed = discord.Embed(
        title=f"👤 {member.display_name}",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="⭐ Level",
        value=level_data["level"],
        inline=True
    )

    embed.add_field(
        name="✨ XP",
        value=level_data["xp"],
        inline=True
    )

    embed.add_field(
        name="💰 Coins",
        value=f"{user['balance']:,}",
        inline=True
    )

    embed.add_field(
        name="💬 Messages",
        value=f"{user['messages']:,}",
        inline=True
    )

    embed.add_field(
        name="🎮 Games",
        value=f"{user['games']:,}",
        inline=True
    )

    embed.add_field(
        name="🏆 Wins",
        value=f"{user['wins']:,}",
        inline=True
    )

    embed.add_field(
        name="🏅 Achievements",
        value=(
            ", ".join(achievements)
            if achievements
            else "None yet"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command(
    name="xpleaderboard",
    aliases=["xplb", "levels"]
)
async def xp_leaderboard(ctx):

    guild_data = levels.get(
        str(ctx.guild.id),
        {}
    )

    if not guild_data:
        await ctx.send(
            "📊 Nobody has earned XP yet."
        )
        return

    ranking = sorted(
        guild_data.items(),
        key=lambda x: (
            x[1].get("level", 1),
            x[1].get("xp", 0)
        ),
        reverse=True
    )[:10]

    lines = []

    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, data) in enumerate(ranking, 1):

        member = ctx.guild.get_member(
            int(uid)
        )

        name = (
            member.display_name
            if member
            else f"User {uid}"
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
        color=discord.Color.gold()
    )

    await ctx.send(embed=embed)


# ============================================================
# ACHIEVEMENTS
# ============================================================

ACHIEVEMENTS = {
    "First Message": {
        "requirement": lambda u: u["messages"] >= 1,
        "description": "Send your first message."
    },

    "Chatty": {
        "requirement": lambda u: u["messages"] >= 100,
        "description": "Send 100 messages."
    },

    "Veteran": {
        "requirement": lambda u: u["messages"] >= 500,
        "description": "Send 500 messages."
    },

    "Gambler": {
        "requirement": lambda u: u["games"] >= 25,
        "description": "Play 25 games."
    },

    "Winner": {
        "requirement": lambda u: u["wins"] >= 10,
        "description": "Win 10 games."
    },

    "Rich": {
        "requirement": lambda u: u["balance"] >= 5000,
        "description": "Have 5,000 coins."
    }
}


async def check_achievements(ctx, user):

    unlocked = []

    for name, achievement in ACHIEVEMENTS.items():

        if name in user["achievements"]:
            continue

        if achievement["requirement"](user):

            user["achievements"].append(name)

            unlocked.append(name)

    if unlocked:

        save_economy()

        for achievement in unlocked:

            await ctx.send(
                f"🏅 {ctx.author.mention} "
                f"unlocked **{achievement}**!"
            )


@bot.command(name="achievements", aliases=["badges"])
async def achievements(ctx):

    user = get_user(ctx.author.id)

    lines = []

    for name, data in ACHIEVEMENTS.items():

        if name in user["achievements"]:
            status = "✅"
        else:
            status = "🔒"

        lines.append(
            f"{status} **{name}** — "
            f"{data['description']}"
        )

    embed = discord.Embed(
        title="🏅 Achievements",
        description="\n".join(lines),
        color=discord.Color.gold()
    )

    await ctx.send(embed=embed)


# ============================================================
# ECONOMY
# ============================================================

@bot.command(name="balance", aliases=["bal"])
async def balance(ctx):

    user = get_user(ctx.author.id)

    await ctx.send(
        f"💰 {ctx.author.mention}, "
        f"you have **{user['balance']:,} coins**."
    )


@bot.command(name="daily")
async def daily(ctx):

    user = get_user(ctx.author.id)

    now = datetime.now(timezone.utc)

    if user["last_daily"]:

        last = datetime.fromisoformat(
            user["last_daily"]
        )

        if now - last < DAILY_COOLDOWN:

            remaining = (
                DAILY_COOLDOWN -
                (now - last)
            )

            hours, remainder = divmod(
                int(remaining.total_seconds()),
                3600
            )

            minutes = remainder // 60

            await ctx.send(
                f"⏳ You already claimed your daily.\n"
                f"Try again in **{hours}h {minutes}m**."
            )

            return

    user["balance"] += DAILY_AMOUNT
    user["last_daily"] = now.isoformat()

    save_economy()

    await ctx.send(
        f"🎁 {ctx.author.mention} claimed "
        f"**{DAILY_AMOUNT} coins**!\n"
        f"💰 Balance: **{user['balance']:,}**"
    )

    await check_achievements(ctx, user)


@bot.command(name="work")
async def work(ctx):

    user = get_user(ctx.author.id)

    now = datetime.now(timezone.utc)

    if user["last_work"]:

        last = datetime.fromisoformat(
            user["last_work"]
        )

        if now - last < WORK_COOLDOWN:

            remaining = (
                WORK_COOLDOWN -
                (now - last)
            )

            minutes = int(
                remaining.total_seconds() / 60
            )

            await ctx.send(
                f"😴 You're tired.\n"
                f"Try again in **{minutes} minutes**."
            )

            return

    earned = random.randint(
        WORK_MIN,
        WORK_MAX
    )

    user["balance"] += earned
    user["last_work"] = now.isoformat()

    save_economy()

    await ctx.send(
        f"🛠️ {ctx.author.mention} worked and earned "
        f"**{earned} coins**!\n"
        f"💰 Balance: **{user['balance']:,}**"
    )

    await check_achievements(ctx, user)


@bot.command(
    name="leaderboard",
    aliases=["lb"]
)
async def leaderboard(ctx):

    top = sorted(
        economy.items(),
        key=lambda x: x[1].get(
            "balance",
            0
        ),
        reverse=True
    )[:10]

    if not top:
        await ctx.send(
            "No economy data yet."
        )
        return

    lines = []

    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, data) in enumerate(
        top,
        start=1
    ):

        member = ctx.guild.get_member(
            int(uid)
        )

        name = (
            member.display_name
            if member
            else f"User {uid}"
        )

        prefix = (
            medals[i - 1]
            if i <= 3
            else f"**{i}.**"
        )

        lines.append(
            f"{prefix} {name} — "
            f"💰 `{data['balance']:,}`"
        )

    await ctx.send(
        "🏆 **COIN LEADERBOARD**\n\n" +
        "\n".join(lines)
    )


# ============================================================
# GAMES
# ============================================================

@bot.command(name="games")
async def games(ctx):

    embed = discord.Embed(
        title="🎮 Game Center",
        description=(
            "**Mini Games**\n\n"
            "🧠 `!trivia`\n"
            "✊ `!rps rock`\n"
            "🎲 `!roll`\n"
            "🔢 `!guess 5`\n"
            "🎱 `!8ball <question>`\n\n"
            "Games give XP and some give coins!"
        ),
        color=discord.Color.green()
    )

    view = GameMenuView()

    await ctx.send(
        embed=embed,
        view=view
    )


# ============================================================
# RPS
# ============================================================

@bot.command(name="rps")
async def rps(ctx, choice: str):

    choice = choice.lower()

    choices = [
        "rock",
        "paper",
        "scissors"
    ]

    if choice not in choices:

        await ctx.send(
            "Use `rock`, `paper`, or `scissors`."
        )

        return

    bot_choice = random.choice(
        choices
    )

    user = get_user(
        ctx.author.id
    )

    user["games"] += 1

    if choice == bot_choice:

        result = "🤝 Tie!"

    elif (
        (choice == "rock" and bot_choice == "scissors")
        or
        (choice == "paper" and bot_choice == "rock")
        or
        (choice == "scissors" and bot_choice == "paper")
    ):

        reward = 50

        user["balance"] += reward
        user["wins"] += 1

        result = (
            f"🎉 **You win!**\n"
            f"💰 +{reward} coins"
        )

    else:

        result = "💀 **You lose!**"

    save_economy()

    await ctx.send(
        f"✊ **Rock Paper Scissors**\n\n"
        f"You: `{choice}`\n"
        f"Bot: `{bot_choice}`\n\n"
        f"{result}"
    )

    await check_achievements(
        ctx,
        user
    )


# ============================================================
# DICE
# ============================================================

@bot.command(
    name="roll",
    aliases=["dice"]
)
async def roll(ctx, sides: int = 6):

    if sides < 2 or sides > 1000:

        await ctx.send(
            "🎲 Choose between 2 and 1000 sides."
        )

        return

    result = random.randint(
        1,
        sides
    )

    await ctx.send(
        f"🎲 {ctx.author.mention} rolled "
        f"**{result}** (1-{sides})"
    )


# ============================================================
# GUESSING GAME
# ============================================================

@bot.command(name="guess")
async def guess(ctx, number: int):

    if number < 1 or number > 10:

        await ctx.send(
            "🔢 Choose a number from **1 to 10**."
        )

        return

    answer = random.randint(
        1,
        10
    )

    user = get_user(
        ctx.author.id
    )

    user["games"] += 1

    if number == answer:

        reward = 100

        user["balance"] += reward
        user["wins"] += 1

        result = (
            f"🎉 **Correct!**\n"
            f"💰 +{reward} coins"
        )

    else:

        result = (
            f"❌ Wrong!\n"
            f"I picked **{answer}**."
        )

    save_economy()

    await ctx.send(result)

    await check_achievements(
        ctx,
        user
    )


# ============================================================
# 8 BALL
# ============================================================

@bot.command(
    name="8ball",
    aliases=["8b"]
)
async def eightball(
    ctx,
    *,
    question: str
):

    answers = [
        "Absolutely.",
        "Definitely.",
        "Most likely.",
        "Yes.",
        "Probably.",
        "Ask me again later.",
        "Maybe.",
        "Probably not.",
        "No.",
        "Absolutely not."
    ]

    embed = discord.Embed(
        title="🎱 Magic 8-Ball",
        color=discord.Color.purple()
    )

    embed.add_field(
        name="Question",
        value=question,
        inline=False
    )

    embed.add_field(
        name="Answer",
        value=random.choice(answers),
        inline=False
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# TRIVIA
# ============================================================

TRIVIA = [
    (
        "What planet is known as the Red Planet?",
        ["mars"]
    ),

    (
        "How many bones are in an adult human body?",
        ["206"]
    ),

    (
        "What is the largest ocean on Earth?",
        ["pacific", "pacific ocean"]
    ),

    (
        "What gas do humans need to breathe?",
        ["oxygen"]
    ),

    (
        "What is 12 × 12?",
        ["144"]
    ),

    (
        "How many continents are there?",
        ["7", "seven"]
    ),

    (
        "What is the capital of Japan?",
        ["tokyo"]
    )
]


@bot.command(name="trivia")
async def trivia(ctx):

    question, answers = random.choice(
        TRIVIA
    )

    embed = discord.Embed(
        title="🧠 TRIVIA",
        description=question,
        color=discord.Color.orange()
    )

    embed.set_footer(
        text="You have 20 seconds!"
    )

    await ctx.send(
        embed=embed
    )

    def check(message):

        return (
            message.channel == ctx.channel
            and not message.author.bot
        )

    try:

        answer = await bot.wait_for(
            "message",
            timeout=20,
            check=check
        )

        if answer.content.lower().strip() in answers:

            user = get_user(
                answer.author.id
            )

            user["games"] += 1
            user["wins"] += 1
            user["balance"] += 100

            add_xp(
                answer.author,
                50
            )

            save_economy()

            await ctx.send(
                f"🎉 {answer.author.mention} "
                f"**CORRECT!**\n"
                f"💰 +100 coins\n"
                f"⭐ +50 XP"
            )

            await check_achievements(
                ctx,
                user
            )

        else:

            await ctx.send(
                f"❌ Wrong! The answer was "
                f"**{answers[0].title()}**."
            )

    except asyncio.TimeoutError:

        await ctx.send(
            f"⏰ Time's up!\n"
            f"The answer was **{answers[0].title()}**."
        )


# ============================================================
# INTERACTIVE GAME MENU
# ============================================================

class GameMenuView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=120
        )

    @discord.ui.button(
        label="🎲 Dice",
        style=discord.ButtonStyle.primary
    )
    async def dice_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        result = random.randint(
            1,
            6
        )

        await interaction.response.send_message(
            f"🎲 {interaction.user.mention} "
            f"rolled **{result}**!"
        )

    @discord.ui.button(
        label="✊ RPS",
        style=discord.ButtonStyle.success
    )
    async def rps_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        choice = random.choice(
            [
                "rock",
                "paper",
                "scissors"
            ]
        )

        await interaction.response.send_message(
            f"✊ Your random opponent chose "
            f"**{choice}**!"
        )

    @discord.ui.button(
        label="🎱 8-Ball",
        style=discord.ButtonStyle.secondary
    )
    async def ball_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        answer = random.choice(
            [
                "Yes.",
                "No.",
                "Definitely.",
                "Maybe.",
                "Ask again later."
            ]
        )

        await interaction.response.send_message(
            f"🎱 **{answer}**"
        )


# ============================================================
# SHOP
# ============================================================

SHOP_ITEMS = {
    "cookie": {
        "name": "🍪 Cookie",
        "price": 100
    },

    "crown": {
        "name": "👑 Crown",
        "price": 1000
    },

    "diamond": {
        "name": "💎 Diamond",
        "price": 2500
    },

    "trophy": {
        "name": "🏆 Trophy",
        "price": 5000
    }
}


@bot.command(name="shop")
async def shop(ctx):

    lines = []

    for item_id, item in SHOP_ITEMS.items():

        lines.append(
            f"**{item['name']}**\n"
            f"`!buy {item_id}` — "
            f"💰 {item['price']:,}"
        )

    embed = discord.Embed(
        title="🛒 Shop",
        description="\n\n".join(lines),
        color=discord.Color.green()
    )

    await ctx.send(
        embed=embed
    )


@bot.command(name="buy")
async def buy(ctx, item_id: str):

    item_id = item_id.lower()

    if item_id not in SHOP_ITEMS:

        await ctx.send(
            "❌ That item doesn't exist.\n"
            "Use `!shop`."
        )

        return

    item = SHOP_ITEMS[item_id]

    user = get_user(
        ctx.author.id
    )

    if user["balance"] < item["price"]:

        await ctx.send(
            f"💸 You need "
            f"**{item['price']:,} coins**."
        )

        return

    user["balance"] -= item["price"]

    user_key = str(
        ctx.author.id
    )

    if user_key not in inventories:
        inventories[user_key] = {}

    inventories[user_key][item_id] = (
        inventories[user_key].get(
            item_id,
            0
        ) + 1
    )

    save_economy()
    save_json(
        SHOP_FILE,
        inventories
    )

    await ctx.send(
        f"🛒 You bought "
        f"**{item['name']}**!\n"
        f"💰 Balance: "
        f"**{user['balance']:,}**"
    )


@bot.command(
    name="inventory",
    aliases=["inv"]
)
async def inventory(ctx):

    user_id = str(
        ctx.author.id
    )

    items = inventories.get(
        user_id,
        {}
    )

    if not items:

        await ctx.send(
            "🎒 Your inventory is empty."
        )

        return

    lines = []

    for item_id, amount in items.items():

        item = SHOP_ITEMS.get(
            item_id
        )

        if item:

            lines.append(
                f"{item['name']} × **{amount}**"
            )

    embed = discord.Embed(
        title=f"🎒 {ctx.author.display_name}'s Inventory",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# MUSIC
# ============================================================

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",

    "extractor_args": {
        "youtube": {
            "player_client": [
                "android",
                "web"
            ]
        }
    }
}


FFMPEG_OPTIONS = {
    "before_options":
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5",

    "options": "-vn"
}


ytdl = yt_dlp.YoutubeDL(
    YTDL_OPTIONS
)


class YTDLSource(
    discord.PCMVolumeTransformer
):

    def __init__(
        self,
        source,
        *,
        data,
        volume=0.5
    ):

        super().__init__(
            source,
            volume
        )

        self.data = data
        self.title = data.get(
            "title"
        )

        self.url = data.get(
            "url"
        )

        self.webpage_url = data.get(
            "webpage_url"
        )

    @classmethod
    async def from_url(
        cls,
        url,
        *,
        loop=None,
        stream=True
    ):

        loop = (
            loop or
            asyncio.get_event_loop()
        )

        query = (
            url
            if url.startswith("http")
            else f"ytsearch1:{url}"
        )

        data = await loop.run_in_executor(
            None,
            lambda: ytdl.extract_info(
                query,
                download=not stream
            )
        )

        if "entries" in data:

            data = data["entries"][0]

        filename = (
            data["url"]
            if stream
            else ytdl.prepare_filename(data)
        )

        return cls(
            discord.FFmpegPCMAudio(
                filename,
                **FFMPEG_OPTIONS
            ),
            data=data
        )


@bot.command(name="join")
async def join(ctx):

    if (
        ctx.author.voice is None
        or ctx.author.voice.channel is None
    ):

        await ctx.send(
            "🎤 Join a voice channel first."
        )

        return

    channel = ctx.author.voice.channel

    if ctx.voice_client:

        await ctx.voice_client.move_to(
            channel
        )

    else:

        await channel.connect()

    await ctx.send(
        f"🎵 Joined **{channel.name}**."
    )


async def play_song(
    ctx,
    query
):

    if ctx.voice_client is None:

        if (
            ctx.author.voice is None
            or ctx.author.voice.channel is None
        ):

            await ctx.send(
                "🎤 Join a voice channel first."
            )

            return

        await ctx.author.voice.channel.connect()

    voice_client = ctx.voice_client

    if voice_client.is_playing():

        voice_client.stop()

    async with ctx.typing():

        try:

            player = await YTDLSource.from_url(
                query,
                loop=bot.loop,
                stream=True
            )

        except Exception as e:

            logger.exception(
                "Music extraction failed"
            )

            await ctx.send(
                f"❌ Couldn't play that:\n"
                f"`{e}`"
            )

            return

        def after_playing(error):

            if error:

                logger.error(
                    f"Player error: {error}"
                )

        voice_client.play(
            player,
            after=after_playing
        )

    await ctx.send(
        f"🎵 **Now Playing**\n"
        f"**{player.title}**\n"
        f"{player.webpage_url or ''}"
    )


@bot.command(name="play")
async def play(
    ctx,
    *,
    query
):

    await play_song(
        ctx,
        query
    )


@bot.command(name="leave")
async def leave(ctx):

    if ctx.voice_client is None:

        await ctx.send(
            "I'm not in a voice channel."
        )

        return

    await ctx.voice_client.disconnect()

    await ctx.send(
        "👋 Disconnected."
    )


# ============================================================
# DOWNLOAD SONG
# ============================================================

@bot.command(
    name="download",
    aliases=["dl", "send"]
)
async def download_song(
    ctx,
    *,
    query
):

    status = await ctx.send(
        f"⏳ Fetching **{query}**..."
    )

    query_url = (
        query
        if query.startswith("http")
        else f"ytsearch1:{query}"
    )

    os.makedirs(
        "downloads",
        exist_ok=True
    )

    dl_opts = {

        "format":
            "bestaudio/best",

        "outtmpl":
            "downloads/%(id)s.%(ext)s",

        "postprocessors": [
            {
                "key":
                    "FFmpegExtractAudio",

                "preferredcodec":
                    "mp3",

                "preferredquality":
                    "192"
            }
        ],

        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,

        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web"
                ]
            }
        }
    }

    loop = asyncio.get_event_loop()

    try:

        with yt_dlp.YoutubeDL(
            dl_opts
        ) as ydl:

            info = await loop.run_in_executor(
                None,
                lambda: ydl.extract_info(
                    query_url,
                    download=True
                )
            )

            if "entries" in info:

                info = info["entries"][0]

            base, _ = os.path.splitext(
                ydl.prepare_filename(info)
            )

            mp3_path = base + ".mp3"

    except Exception as e:

        logger.exception(
            "Download failed"
        )

        await status.edit(
            content=f"❌ Couldn't download:\n`{e}`"
        )

        return

    if not os.path.exists(mp3_path):

        await status.edit(
            content="❌ MP3 conversion failed."
        )

        return

    limit = (
        ctx.guild.filesize_limit
        if ctx.guild
        else 25 * 1024 * 1024
    )

    size = os.path.getsize(
        mp3_path
    )

    title = info.get(
        "title",
        "audio"
    )

    if size > limit:

        await status.edit(
            content=(
                f"⚠️ **{title}** is too large "
                f"to upload here."
            )
        )

        os.remove(mp3_path)

        return

    await status.delete()

    try:

        await ctx.send(
            content=f"🎵 **{title}**",
            file=discord.File(
                mp3_path,
                filename=f"{title[:80]}.mp3"
            )
        )

    finally:

        if os.path.exists(mp3_path):

            os.remove(mp3_path)


# ============================================================
# AI CHAT
# ============================================================

CLAUDE_API_URL = (
    "https://api.anthropic.com/v1/messages"
)

CLAUDE_MODEL = (
    "claude-haiku-4-5-20251001"
)

chat_history = {}

MAX_HISTORY = 6


@bot.command(name="chat")
async def chat(
    ctx,
    *,
    message
):

    if not ANTHROPIC_API_KEY:

        await ctx.send(
            "🤖 AI isn't configured."
        )

        return

    channel_id = str(
        ctx.channel.id
    )

    history = chat_history.setdefault(
        channel_id,
        []
    )

    history.append(
        {
            "role": "user",
            "content": message
        }
    )

    history[:] = history[
        -MAX_HISTORY:
    ]

    async with ctx.typing():

        try:

            async with aiohttp.ClientSession() as session:

                async with session.post(
                    CLAUDE_API_URL,

                    headers={
                        "x-api-key":
                            ANTHROPIC_API_KEY,

                        "anthropic-version":
                            "2023-06-01",

                        "content-type":
                            "application/json"
                    },

                    json={
                        "model":
                            CLAUDE_MODEL,

                        "max_tokens":
                            500,

                        "system":
                            (
                                "You are a friendly, "
                                "concise Discord bot "
                                "assistant. Keep replies "
                                "short and casual."
                            ),

                        "messages":
                            history
                    }

                ) as resp:

                    data = await resp.json()

                    if resp.status != 200:

                        logger.error(
                            f"Claude error: {data}"
                        )

                        await ctx.send(
                            "❌ AI couldn't respond."
                        )

                        return

                    reply = data[
                        "content"
                    ][0]["text"]

        except Exception:

            logger.exception(
                "Claude API failed"
            )

            await ctx.send(
                "❌ Something went wrong."
            )

            return

    history.append(
        {
            "role":
                "assistant",

            "content":
                reply
        }
    )

    history[:] = history[
        -MAX_HISTORY:
    ]

    for i in range(
        0,
        len(reply),
        2000
    ):

        await ctx.send(
            reply[i:i + 2000]
        )


# ============================================================
# HELP
# ============================================================

@bot.command(
    name="help",
    aliases=["commands"]
)
async def help_command(ctx):

    embed = discord.Embed(
        title="🤖 MUSIC DELIVERY",
        description=(
            "Your all-in-one Discord bot.\n\n"
            "🎵 **Music**\n"
            "`!play <song>`\n"
            "`!download <song>`\n"
            "`!join` • `!leave`\n\n"

            "⭐ **Leveling**\n"
            "`!rank` • `!profile`\n"
            "`!xpleaderboard`\n"
            "`!achievements`\n\n"

            "💰 **Economy**\n"
            "`!balance`\n"
            "`!daily` • `!work`\n"
            "`!leaderboard`\n\n"

            "🎮 **Games**\n"
            "`!games`\n"
            "`!trivia`\n"
            "`!rps rock`\n"
            "`!roll`\n"
            "`!guess 5`\n"
            "`!8ball <question>`\n\n"

            "🛒 **Shop**\n"
            "`!shop`\n"
            "`!buy <item>`\n"
            "`!inventory`\n\n"

            "🤖 **AI**\n"
            "`!chat <message>`"
        ),
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# UNKNOWN COMMAND = MUSIC SEARCH
# ============================================================

KNOWN_COMMANDS = {
    "join",
    "play",
    "leave",
    "download",
    "dl",
    "send",

    "balance",
    "bal",
    "daily",
    "work",
    "coinflip",
    "cf",
    "slots",
    "leaderboard",
    "lb",

    "rank",
    "level",
    "lvl",
    "profile",
    "me",
    "xpleaderboard",
    "xplb",
    "levels",
    "achievements",
    "badges",

    "games",
    "rps",
    "roll",
    "dice",
    "guess",
    "trivia",
    "8ball",
    "8b",

    "shop",
    "buy",
    "inventory",
    "inv",

    "chat",
    "help",
    "commands"
}


@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):

        query = (
            ctx.message.content[
                len(ctx.prefix):
            ].strip()
        )

        if (
            query
            and query.split()[0].lower()
            not in KNOWN_COMMANDS
        ):

            await play_song(
                ctx,
                query
            )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ You're missing something.\n"
            "Use `!help` to see how to use the command."
        )

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ I couldn't find that member."
        )

        return

    logger.error(
        f"Command error: {error}"
    )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    logger.info(
        f"Logged in as {bot.user} "
        f"(ID: {bot.user.id})"
    )

    logger.info(
        f"Connected to {len(bot.guilds)} server(s)"
    )

    try:

        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="!help"
            )
        )

    except Exception:

        pass


# ============================================================
# RENDER / HEALTH SERVER
# ============================================================

async def health(request):

    return web.Response(
        text="Music Delivery is running 🎵"
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    runner = web.AppRunner(
        app
    )

    await runner.setup()

    port = int(
        os.getenv(
            "PORT",
            10000
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    logger.info(
        f"Health server running on {port}"
    )


# ============================================================
# START BOT
# ============================================================

async def main():

    await start_web_server()

    async with bot:

        await bot.start(
            DISCORD_TOKEN
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )
