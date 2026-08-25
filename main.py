import os
import json
import random
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
import yt_dlp
import aiohttp
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

EMBED_COLOR = discord.Color.from_rgb(88, 101, 242)  # Discord blurple

# ==================== BARTENDER PERSONALITY ====================
# Shared flavor text so games, 8-ball, etc. don't all sound like a form letter.

EIGHTBALL_RESPONSES = {
    "positive": [
        "I'd put money on it.",
        "Honestly? Yeah.",
        "Looks good from where I'm standing.",
        "I'd say you've got this.",
        "The odds are weirdly in your favor.",
        "Yeah. Don't overthink it.",
    ],
    "negative": [
        "I'd leave that one alone.",
        "Yeah... I wouldn't.",
        "That's looking rough.",
        "Probably not the hill you wanna die on.",
        "My professional opinion? Absolutely not.",
        "You already know the answer to that.",
    ],
    "uncertain": [
        "Could go either way.",
        "That's a dangerous coin toss.",
        "Ask me after another drink.",
        "The universe is being suspiciously quiet on this one.",
        "I genuinely don't know on that one.",
        "You're asking me to gamble with information I don't have.",
    ],
    "sarcastic": [
        "Bold question for someone who already made up their mind.",
        "You came here for validation, didn't you?",
        "Interesting. Very interesting. I'm choosing not to elaborate.",
        "You want the honest answer or the one that'll make you feel better?",
        "You already know better than to ask me that.",
        "That's between you and whatever decision led you here.",
    ],
}

COINFLIP_WIN_LINES = [
    "Beginner's luck. Don't get used to it.",
    "Look at that. The house lost one.",
    "I'll allow it.",
    "Someone's feeling lucky tonight.",
]
COINFLIP_LOSE_LINES = [
    "Tough luck. Try not to take it personally.",
    "The coin has spoken. It's not on your side.",
    "That's rough. Want a napkin for that L?",
    "Statistically expected, honestly.",
]
SLOTS_JACKPOT_LINES = [
    "Okay, NOW I'm paying attention.",
    "Alright, big winner over here. Everyone look.",
    "I don't know how you did that, but I'm impressed.",
]
SLOTS_WIN_LINES = [
    "Not bad. Not bad at all.",
    "Two out of three ain't nothing.",
    "The machine likes you tonight. Suspicious, but I'll allow it.",
]
SLOTS_LOSE_LINES = [
    "That spin was rough. I'm not even charging you emotionally.",
    "The house always wins eventually. Today was 'eventually.'",
    "Painful. Truly painful to watch.",
    "That's one for the memory book. Not a good one.",
]

# ==================== MUSIC ====================

YTDL_OPTIONS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    # Pretending to be the YouTube Android app avoids the "Sign in to confirm
    # you're not a bot" block that cloud/datacenter IPs (like Render's) often hit.
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    },
}
if YTDLP_COOKIES_FILE and os.path.exists(YTDLP_COOKIES_FILE):
    YTDL_OPTIONS["cookiefile"] = YTDLP_COOKIES_FILE
    logger.info(f"Using YouTube cookies from {YTDLP_COOKIES_FILE}")

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.webpage_url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")
        self.uploader = data.get("uploader")
        self.duration = data.get("duration")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        # "ytsearch1:" makes plain text (song name) resolve to the first search result
        query = url if url.startswith("http") else f"ytsearch1:{url}"
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(query, download=not stream)
        )
        if "entries" in data:
            data = data["entries"][0]
        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)


def format_duration(seconds):
    if not seconds:
        return "Live/Unknown"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name="!help")
        )
    except Exception:
        pass


@bot.command(name="join")
async def join(ctx: commands.Context):
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send(embed=error_embed("Join a voice channel first."))
        return
    channel = ctx.author.voice.channel
    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
    embed = discord.Embed(
        description=f"🎤 Joined **{channel.name}**",
        color=EMBED_COLOR,
    )
    await ctx.send(embed=embed)


async def play_song(ctx: commands.Context, query: str):
    """Shared logic: joins voice if needed, searches/streams, and posts a now-playing embed."""
    if ctx.voice_client is None:
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send(embed=error_embed("Join a voice channel first, or use `!join`."))
            return
        await ctx.author.voice.channel.connect()

    voice_client = ctx.voice_client
    if voice_client.is_playing():
        voice_client.stop()

    async with ctx.typing():
        try:
            player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        except Exception as e:
            logger.exception("Failed to extract/stream audio")
            await ctx.send(embed=error_embed(f"Couldn't find or play that.\n`{e}`"))
            return

        def after_playing(error):
            if error:
                logger.error(f"Player error: {error}")

        voice_client.play(player, after=after_playing)

    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"**[{player.title}]({player.webpage_url or ''})**",
        color=EMBED_COLOR,
    )
    if player.uploader:
        embed.add_field(name="Uploader", value=player.uploader, inline=True)
    embed.add_field(name="Duration", value=format_duration(player.duration), inline=True)
    if player.thumbnail:
        embed.set_thumbnail(url=player.thumbnail)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="play")
async def play(ctx: commands.Context, *, query: str):
    await play_song(ctx, query)


@bot.command(name="leave")
async def leave(ctx: commands.Context):
    if ctx.voice_client is None:
        await ctx.send(embed=error_embed("I'm not connected to a voice channel."))
        return
    await ctx.voice_client.disconnect()
    embed = discord.Embed(description="👋 Disconnected.", color=EMBED_COLOR)
    await ctx.send(embed=embed)


@bot.command(name="download", aliases=["dl", "send"])
async def download_song(ctx: commands.Context, *, query: str):
    """Downloads the song as an MP3 and posts it directly in chat."""
    status_embed = discord.Embed(description=f"⏳ Fetching **{query}**...", color=EMBED_COLOR)
    status = await ctx.send(embed=status_embed)

    query_url = query if query.startswith("http") else f"ytsearch1:{query}"
    os.makedirs("downloads", exist_ok=True)
    dl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if YTDLP_COOKIES_FILE and os.path.exists(YTDLP_COOKIES_FILE):
        dl_opts["cookiefile"] = YTDLP_COOKIES_FILE

    loop = asyncio.get_event_loop()
    mp3_path = None
    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(query_url, download=True)
            )
            if "entries" in info:
                info = info["entries"][0]
            base, _ = os.path.splitext(ydl.prepare_filename(info))
            mp3_path = base + ".mp3"
    except Exception as e:
        logger.exception("Download failed")
        await status.edit(embed=error_embed(f"Couldn't download that.\n`{e}`"))
        return

    limit = ctx.guild.filesize_limit if ctx.guild else 25 * 1024 * 1024
    size = os.path.getsize(mp3_path)
    title = info.get("title", "audio")

    if size > limit:
        await status.edit(
            embed=error_embed(
                f"**{title}** is too large to upload here "
                f"({size // (1024*1024)}MB). Try `!play {query}` to stream it instead."
            )
        )
        os.remove(mp3_path)
        return

    await status.delete()
    embed = discord.Embed(
        title="🎵 Download Ready",
        description=f"**{title}**",
        color=EMBED_COLOR,
    )
    thumb = info.get("thumbnail")
    if thumb:
        embed.set_thumbnail(url=thumb)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(
        embed=embed,
        file=discord.File(mp3_path, filename=f"{title[:80]}.mp3"),
    )
    os.remove(mp3_path)


# ==================== ECONOMY ====================

ECONOMY_FILE = "economy.json"
STARTING_BALANCE = 100
DAILY_AMOUNT = 200
WORK_MIN, WORK_MAX = 50, 150
WORK_COOLDOWN = timedelta(hours=1)
DAILY_COOLDOWN = timedelta(hours=24)


def load_economy():
    if os.path.exists(ECONOMY_FILE):
        try:
            with open(ECONOMY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_economy():
    with open(ECONOMY_FILE, "w") as f:
        json.dump(economy, f, indent=2)


economy = load_economy()


def get_user(uid):
    uid = str(uid)
    if uid not in economy:
        economy[uid] = {"balance": STARTING_BALANCE, "last_daily": None, "last_work": None}
    return economy[uid]


def error_embed(message):
    return discord.Embed(description=f"❌ {message}", color=discord.Color.red())


# ==================== LEVELING & RANKS ====================

LEVEL_FILE = "levels.json"
XP_MIN, XP_MAX = 8, 18
XP_COOLDOWN_SECONDS = 45

levels = {}
if os.path.exists(LEVEL_FILE):
    try:
        with open(LEVEL_FILE, "r") as f:
            levels = json.load(f)
    except (json.JSONDecodeError, OSError):
        levels = {}

xp_cooldowns = {}

RANK_TITLES = [
    (1, "Newcomer"), (5, "Regular"), (10, "Regular+"), (20, "Veteran"),
    (35, "Elite"), (50, "Legend"), (100, "Mythic"),
]


def save_levels():
    with open(LEVEL_FILE, "w") as f:
        json.dump(levels, f, indent=2)


def get_level_data(guild_id, user_id):
    guild_id, user_id = str(guild_id), str(user_id)
    levels.setdefault(guild_id, {})
    levels[guild_id].setdefault(user_id, {"xp": 0, "level": 1})
    return levels[guild_id][user_id]


def xp_required(level):
    return level * 100


def rank_title(level):
    title = RANK_TITLES[0][1]
    for threshold, name in RANK_TITLES:
        if level >= threshold:
            title = name
    return title


def add_xp(guild_id, user_id, amount=None):
    data = get_level_data(guild_id, user_id)
    old_level = data["level"]
    if amount is None:
        amount = random.randint(XP_MIN, XP_MAX)
    data["xp"] += amount
    while data["xp"] >= xp_required(data["level"]):
        data["xp"] -= xp_required(data["level"])
        data["level"] += 1
    save_levels()
    return amount, old_level, data["level"]


def make_xp_bar(current, maximum, length=12):
    if maximum <= 0:
        return "█" * length
    filled = int(length * min(current / maximum, 1))
    return "█" * filled + "░" * (length - filled)


@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    if message.guild:
        key = f"{message.guild.id}:{message.author.id}"
        now = asyncio.get_event_loop().time()
        if now - xp_cooldowns.get(key, 0) >= XP_COOLDOWN_SECONDS:
            xp_cooldowns[key] = now
            amount, old_level, new_level = add_xp(message.guild.id, message.author.id)
            if new_level > old_level:
                embed = discord.Embed(
                    description=(
                        f"🎉 {message.author.mention} just hit **Level {new_level}** "
                        f"— **{rank_title(new_level)}** now.\nKeep it up."
                    ),
                    color=discord.Color.gold(),
                )
                try:
                    await message.channel.send(embed=embed)
                except discord.Forbidden:
                    pass

    await bot.process_commands(message)


@bot.command(name="rank", aliases=["level", "lvl"])
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_level_data(ctx.guild.id, member.id)
    guild_data = levels.get(str(ctx.guild.id), {})
    ranking = sorted(guild_data.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
    position = next((i for i, (uid, _) in enumerate(ranking, 1) if uid == str(member.id)), len(ranking))

    needed = xp_required(data["level"])
    bar = make_xp_bar(data["xp"], needed)

    embed = discord.Embed(title=f"⭐ {member.display_name}'s Rank", color=EMBED_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Level", value=f"**{data['level']}** — {rank_title(data['level'])}", inline=True)
    embed.add_field(name="XP", value=f"**{data['xp']:,} / {needed:,}**", inline=True)
    embed.add_field(name="Server Rank", value=f"**#{position}**", inline=True)
    embed.add_field(name="Progress", value=f"`{bar}`", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="xpleaderboard", aliases=["xplb", "levels"])
async def xp_leaderboard(ctx):
    guild_data = levels.get(str(ctx.guild.id), {})
    if not guild_data:
        await ctx.send(embed=error_embed("Nobody's earned XP yet."))
        return
    ranking = sorted(guild_data.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, data) in enumerate(ranking, 1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        prefix = medals[i - 1] if i <= 3 else f"**{i}.**"
        lines.append(f"{prefix} **{name}** — Level `{data['level']}` • `{data['xp']} XP`")
    embed = discord.Embed(title="🏆 XP Leaderboard", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


@bot.command(name="profile", aliases=["me"])
async def profile(ctx, member: discord.Member = None):
    member = member or ctx.author
    user = get_user(member.id)
    level_data = get_level_data(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"👤 {member.display_name}", color=EMBED_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="⭐ Level", value=f"{level_data['level']} — {rank_title(level_data['level'])}", inline=True)
    embed.add_field(name="✨ XP", value=f"{level_data['xp']:,}", inline=True)
    embed.add_field(name="💰 Coins", value=f"{user['balance']:,}", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="balance", aliases=["bal"])
async def balance(ctx):
    user = get_user(ctx.author.id)
    embed = discord.Embed(
        title="💰 Balance",
        description=f"**{user['balance']:,}** coins",
        color=discord.Color.gold(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="daily")
async def daily(ctx):
    user = get_user(ctx.author.id)
    now = datetime.now(timezone.utc)
    if user["last_daily"]:
        last = datetime.fromisoformat(user["last_daily"])
        if now - last < DAILY_COOLDOWN:
            remaining = DAILY_COOLDOWN - (now - last)
            hrs, rem = divmod(int(remaining.total_seconds()), 3600)
            mins = rem // 60
            await ctx.send(embed=error_embed(f"Already claimed. Try again in **{hrs}h {mins}m**."))
            return
    user["balance"] += DAILY_AMOUNT
    user["last_daily"] = now.isoformat()
    save_economy()
    embed = discord.Embed(
        title="🎁 Daily Reward",
        description=f"Claimed **{DAILY_AMOUNT} coins**!\nBalance: **{user['balance']:,}**",
        color=discord.Color.gold(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="work")
async def work(ctx):
    user = get_user(ctx.author.id)
    now = datetime.now(timezone.utc)
    if user["last_work"]:
        last = datetime.fromisoformat(user["last_work"])
        if now - last < WORK_COOLDOWN:
            remaining = WORK_COOLDOWN - (now - last)
            mins = int(remaining.total_seconds() // 60)
            await ctx.send(embed=error_embed(f"You're tired. Rest **{mins}m** before working again."))
            return
    earned = random.randint(WORK_MIN, WORK_MAX)
    user["balance"] += earned
    user["last_work"] = now.isoformat()
    save_economy()
    embed = discord.Embed(
        title="🛠️ Work Complete",
        description=f"Earned **{earned} coins**!\nBalance: **{user['balance']:,}**",
        color=discord.Color.gold(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="coinflip", aliases=["cf"])
async def coinflip(ctx, amount: int, choice: str):
    choice = choice.lower()
    if choice not in ("heads", "tails"):
        await ctx.send(embed=error_embed("Choose `heads` or `tails`. Usage: `!coinflip <amount> <heads/tails>`"))
        return
    user = get_user(ctx.author.id)
    if amount <= 0 or amount > user["balance"]:
        await ctx.send(embed=error_embed("Invalid bet amount."))
        return
    result = random.choice(["heads", "tails"])
    won = result == choice
    if won:
        user["balance"] += amount
        flavor = random.choice(COINFLIP_WIN_LINES)
    else:
        user["balance"] -= amount
        flavor = random.choice(COINFLIP_LOSE_LINES)
    save_economy()
    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=(
            f"Landed on **{result}**!\n"
            f"{'🎉 You won' if won else '💀 You lost'} **{amount:,} coins**\n"
            f"Balance: **{user['balance']:,}**\n\n"
            f"*\"{flavor}\"*"
        ),
        color=discord.Color.green() if won else discord.Color.red(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="slots")
async def slots(ctx, amount: int):
    user = get_user(ctx.author.id)
    if amount <= 0 or amount > user["balance"]:
        await ctx.send(embed=error_embed("Invalid bet amount. Usage: `!slots <amount>`"))
        return
    symbols = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
    spin = [random.choice(symbols) for _ in range(3)]
    display = " | ".join(spin)
    if spin[0] == spin[1] == spin[2]:
        winnings = amount * 5
        user["balance"] += winnings
        result_text = f"🎉 **JACKPOT!** You won **{winnings:,} coins**"
        color = discord.Color.gold()
        flavor = random.choice(SLOTS_JACKPOT_LINES)
    elif spin[0] == spin[1] or spin[1] == spin[2]:
        winnings = amount * 2
        user["balance"] += winnings
        result_text = f"✨ **Nice!** You won **{winnings:,} coins**"
        color = discord.Color.green()
        flavor = random.choice(SLOTS_WIN_LINES)
    else:
        user["balance"] -= amount
        result_text = f"💀 No match. You lost **{amount:,} coins**"
        color = discord.Color.red()
        flavor = random.choice(SLOTS_LOSE_LINES)
    save_economy()
    embed = discord.Embed(
        title="🎰 Slots",
        description=f"**{display}**\n\n{result_text}\nBalance: **{user['balance']:,}**\n\n*\"{flavor}\"*",
        color=color,
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="8ball", aliases=["8b"])
async def eightball(ctx, *, question: str):
    category = random.choice(list(EIGHTBALL_RESPONSES.keys()))
    reply = random.choice(EIGHTBALL_RESPONSES[category])
    embed = discord.Embed(
        title="🎱",
        description=f"**{question}**\n\n{reply}",
        color=EMBED_COLOR,
    )
    await ctx.send(embed=embed)


RPS_CHOICES = ["rock", "paper", "scissors"]
RPS_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}


def rps_outcome(player, opp):
    if player == opp:
        return "tie"
    wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    return "win" if wins[player] == opp else "lose"


@bot.command(name="rps")
async def rps(ctx, choice: str):
    choice = choice.lower()
    if choice not in RPS_CHOICES:
        await ctx.send(embed=error_embed("Use `rock`, `paper`, or `scissors`."))
        return
    bot_choice = random.choice(RPS_CHOICES)
    outcome = rps_outcome(choice, bot_choice)
    user = get_user(ctx.author.id)
    if outcome == "win":
        reward = 50
        user["balance"] += reward
        save_economy()
        text = f"🎉 **You win!** +{reward} coins"
        color = discord.Color.green()
    elif outcome == "tie":
        text = "🤝 Tie. Nobody's buying a round for that."
        color = EMBED_COLOR
    else:
        text = "💀 You lose. Try again."
        color = discord.Color.red()
    embed = discord.Embed(
        title="✊ Rock Paper Scissors",
        description=f"You: {RPS_EMOJI[choice]}  vs  Bot: {RPS_EMOJI[bot_choice]}\n\n{text}",
        color=color,
    )
    await ctx.send(embed=embed)


@bot.command(name="roll", aliases=["dice"])
async def roll(ctx, sides: int = 6):
    if sides < 2 or sides > 1000:
        await ctx.send(embed=error_embed("Choose between 2 and 1000 sides."))
        return
    result = random.randint(1, sides)
    embed = discord.Embed(
        description=f"🎲 {ctx.author.mention} rolled **{result}** (1-{sides})",
        color=EMBED_COLOR,
    )
    await ctx.send(embed=embed)


class GameMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="🎲 Roll", style=discord.ButtonStyle.primary)
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"🎲 Rolled **{random.randint(1, 6)}**!")

    @discord.ui.button(label="✊ RPS", style=discord.ButtonStyle.success)
    async def rps_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        choice = random.choice(RPS_CHOICES)
        await interaction.response.send_message(f"✊ Random opponent throws {RPS_EMOJI[choice]}!")

    @discord.ui.button(label="🎱 8-Ball", style=discord.ButtonStyle.secondary)
    async def ball_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        category = random.choice(list(EIGHTBALL_RESPONSES.keys()))
        await interaction.response.send_message(f"🎱 {random.choice(EIGHTBALL_RESPONSES[category])}")


@bot.command(name="games")
async def games_menu(ctx):
    embed = discord.Embed(
        title="🎮 Game Center",
        description=(
            "**Commands**\n"
            "`!coinflip <amount> heads/tails`\n"
            "`!slots <amount>`\n"
            "`!rps rock/paper/scissors`\n"
            "`!roll [sides]`\n"
            "`!8ball <question>`\n\n"
            "Or just tap a button below 👇"
        ),
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed, view=GameMenuView())


@bot.command(name="leaderboard", aliases=["lb"])
async def leaderboard(ctx):
    top = sorted(economy.items(), key=lambda x: x[1]["balance"], reverse=True)[:10]
    if not top:
        await ctx.send(embed=error_embed("No data yet."))
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, data) in enumerate(top, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        prefix = medals[i - 1] if i <= 3 else f"**{i}.**"
        lines.append(f"{prefix} {name} — `{data['balance']:,}` coins")
    embed = discord.Embed(
        title="🏆 Coin Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed)


# ==================== AI CHAT ====================

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap; swap to "claude-sonnet-5" for smarter replies

chat_history = {}
MAX_HISTORY = 6

BASE_PERSONALITY = (
    "You are not an assistant that exists only to answer questions — you're a recurring "
    "character who hangs around this Discord server. Talk naturally. You don't need to "
    "give a complete explanation every time — sometimes a short sentence is better. Don't "
    "constantly use emojis or slang, don't call everyone 'bro', don't start every reply the "
    "same way, and don't sound like customer support. If someone is joking, joke back. If "
    "someone is venting, listen. If someone asks something serious, become more sincere. "
    "Keep replies short — a sentence or two, like a real chat message, not an essay."
)

CHAT_MODES = {
    "bartender": (
        "You're the bartender of this server. Relaxed, witty, slightly sarcastic, observant, "
        "and occasionally unexpectedly thoughtful. You can occasionally use bartender-style "
        "language naturally, but don't force the metaphor into every message. "
        + BASE_PERSONALITY
    ),
    "casino": (
        "You run the casino floor of this server. Cocky, playful, always ready with a gambling "
        "line or a bet, but not obnoxious about it. " + BASE_PERSONALITY
    ),
    "dj": (
        "You're the DJ of this server. Laid-back, music-obsessed, drops the occasional music "
        "reference or opinion, chill energy. " + BASE_PERSONALITY
    ),
    "menace": (
        "You're the resident troublemaker of this server. Teasing, playfully chaotic, quick "
        "with a roast, but never actually mean or crossing into real insults. " + BASE_PERSONALITY
    ),
    "normal": (
        "You're a straightforward, friendly regular in this server. Clear and direct, still "
        "warm and conversational, no persona gimmick. " + BASE_PERSONALITY
    ),
}
DEFAULT_MODE = "bartender"
channel_modes = {}


@bot.command(name="mode")
async def mode(ctx: commands.Context, choice: str = None):
    channel_id = str(ctx.channel.id)
    if choice is None:
        current = channel_modes.get(channel_id, DEFAULT_MODE)
        embed = discord.Embed(
            title="🎭 Current Mode",
            description=(
                f"This channel's bot personality is set to **{current}**.\n\n"
                f"Options: {', '.join(f'`{m}`' for m in CHAT_MODES)}\n"
                f"Usage: `!mode <name>`"
            ),
            color=EMBED_COLOR,
        )
        await ctx.send(embed=embed)
        return
    choice = choice.lower()
    if choice not in CHAT_MODES:
        await ctx.send(embed=error_embed(f"Unknown mode. Options: {', '.join(CHAT_MODES)}"))
        return
    channel_modes[channel_id] = choice
    embed = discord.Embed(description=f"🎭 Mode switched to **{choice}** for this channel.", color=EMBED_COLOR)
    await ctx.send(embed=embed)


@bot.command(name="chat")
async def chat(ctx: commands.Context, *, message: str):
    if not ANTHROPIC_API_KEY:
        await ctx.send(embed=error_embed("AI chat isn't set up yet — missing `ANTHROPIC_API_KEY`."))
        return

    channel_id = str(ctx.channel.id)
    history = chat_history.setdefault(channel_id, [])
    history.append({"role": "user", "content": message})
    history[:] = history[-MAX_HISTORY:]
    system_prompt = CHAT_MODES.get(channel_modes.get(channel_id, DEFAULT_MODE), CHAT_MODES[DEFAULT_MODE])

    async with ctx.typing():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    CLAUDE_API_URL,
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 500,
                        "system": system_prompt,
                        "messages": history,
                    },
                ) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        logger.error(f"Claude API error: {data}")
                        await ctx.send(embed=error_embed("Sorry, I couldn't get a response right now."))
                        return
                    reply = data["content"][0]["text"]
        except Exception:
            logger.exception("Claude API call failed")
            await ctx.send(embed=error_embed("Something went wrong reaching the AI."))
            return

    history.append({"role": "assistant", "content": reply})
    history[:] = history[-MAX_HISTORY:]

    embed = discord.Embed(description=reply[:4000], color=EMBED_COLOR)
    embed.set_author(name="🤖 Music Delivery", icon_url=bot.user.display_avatar.url if bot.user else None)
    await ctx.send(embed=embed)


# ==================== HELP ====================

@bot.command(name="help", aliases=["commands"])
async def help_command(ctx: commands.Context):
    embed = discord.Embed(
        title="🎵 Music Delivery — Commands",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="🎶 Music",
        value="`!play <song>`\n`!download <song>`\n`!join` • `!leave`\n"
              "_Tip: just type `!<song name>` to play instantly_",
        inline=False,
    )
    embed.add_field(
        name="⭐ Leveling",
        value="`!rank` `!profile`\n`!xpleaderboard`",
        inline=False,
    )
    embed.add_field(
        name="💰 Economy",
        value="`!balance` `!daily` `!work`\n`!leaderboard`",
        inline=False,
    )
    embed.add_field(
        name="🎮 Games",
        value="`!games` (interactive menu)\n`!coinflip <amount> heads/tails`\n"
              "`!slots <amount>`\n`!rps rock/paper/scissors`\n`!roll [sides]`\n`!8ball <question>`",
        inline=False,
    )
    embed.add_field(
        name="🎭 Bot Personality",
        value="`!mode` — see/set the bot's vibe (bartender, casino, dj, menace, normal)",
        inline=False,
    )
    embed.add_field(
        name="🤖 Chat with the bot",
        value="`!chat <message>`",
        inline=False,
    )
    embed.set_footer(text="Music Delivery Bot")
    await ctx.send(embed=embed)


# Lets people just type "!<song name>" instead of "!play <song name>"
KNOWN_COMMANDS = {"join", "play", "leave", "download", "dl", "send", "balance",
                   "bal", "daily", "work", "coinflip", "cf", "slots", "8ball",
                   "8b", "leaderboard", "lb", "chat", "help", "commands",
                   "rank", "level", "lvl", "xpleaderboard", "xplb", "levels",
                   "profile", "me", "mode", "rps", "roll", "dice", "games"}


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        query = ctx.message.content[len(ctx.prefix):].strip()
        if query and query.split()[0].lower() not in KNOWN_COMMANDS:
            await play_song(ctx, query)
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=error_embed(f"Missing something. Try `!help` for usage."))
        return
    logger.error(f"Command error: {error}")


# ==================== KEEP-ALIVE WEB SERVER ====================
# Render's free Web Service tier requires an open port to detect the app as
# "running." The bot itself doesn't need one (it only talks to Discord), so
# this starts a tiny server alongside it just to satisfy that health check.

async def health(request):
    return web.Response(text="Bot is running.")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server listening on port {port}")


async def main():
    await start_web_server()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
