import os
import json
import random
import asyncio
import logging
import shutil
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

# ============================================================
# YOUTUBE COOKIES
# ============================================================

YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")
YTDLP_RUNTIME_COOKIES = "/tmp/youtube_cookies.txt"

# Render's /etc/secrets directory is READ-ONLY.
# We copy the secret cookie file into /tmp, which is writable.
if YTDLP_COOKIES_FILE:
    try:
        if os.path.exists(YTDLP_COOKIES_FILE):
            shutil.copyfile(
                YTDLP_COOKIES_FILE,
                YTDLP_RUNTIME_COOKIES
            )
            logger.info(
                "YouTube cookies copied to writable runtime storage."
            )
        else:
            logger.warning(
                f"YouTube cookie file was not found at: "
                f"{YTDLP_COOKIES_FILE}"
            )
    except Exception:
        logger.exception("Could not copy YouTube cookies.")

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is not set."
    )

# ============================================================
# DISCORD SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

EMBED_COLOR = discord.Color.from_rgb(88, 101, 242)

# ============================================================
# BARTENDER PERSONALITY
# ============================================================

EIGHTBALL_RESPONSES = {
    "positive": [
        "I'd put money on it.",
        "Honestly? Yeah.",
        "Looks good from where I'm standing.",
        "I'd say you've got this.",
        "The odds are weirdly in your favor.",
        "Yeah. Don't overthink it.",
        "I'd take that bet.",
        "Feels like a yes to me.",
        "The glass is looking pretty full on this one.",
        "I wouldn't bet against you.",
    ],

    "negative": [
        "I'd leave that one alone.",
        "Yeah... I wouldn't.",
        "That's looking rough.",
        "Probably not the hill you wanna die on.",
        "My professional opinion? Absolutely not.",
        "You already know the answer to that.",
        "I'd order something else if I were you.",
        "That one's got bad handwriting all over it.",
        "I'd keep your money in your pocket.",
        "No. And I'm saying that before you make it worse.",
    ],

    "uncertain": [
        "Could go either way.",
        "That's a dangerous coin toss.",
        "Ask me after another drink.",
        "The universe is being suspiciously quiet on this one.",
        "I genuinely don't know on that one.",
        "You're asking me to gamble with information I don't have.",
        "Give it time.",
        "That's above my pay grade tonight.",
        "The answer's hiding at the bottom of the glass.",
        "I'm not touching that one without more information.",
    ],

    "sarcastic": [
        "Bold question for someone who already made up their mind.",
        "You came here for validation, didn't you?",
        "Interesting. Very interesting. I'm choosing not to elaborate.",
        "You want the honest answer or the one that'll make you feel better?",
        "You already know better than to ask me that.",
        "That's between you and whatever decision led you here.",
        "I could answer, but where's the fun in that?",
        "You really walked into the bar and asked me THAT.",
        "That's a question for tomorrow-you.",
        "I'll pretend I didn't hear that.",
    ],
}

COINFLIP_WIN_LINES = [
    "Beginner's luck. Don't get used to it.",
    "Look at that. The house lost one.",
    "I'll allow it.",
    "Someone's feeling lucky tonight.",
    "Well, would you look at that.",
    "The coin actually likes you.",
    "Not bad. Keep your ego in check though.",
]

COINFLIP_LOSE_LINES = [
    "Tough luck. Try not to take it personally.",
    "The coin has spoken. It's not on your side.",
    "That's rough. Want a napkin for that L?",
    "Statistically expected, honestly.",
    "Ouch. That one landed directly on your wallet.",
    "The coin chose violence.",
    "Maybe don't let the coin manage your finances.",
]

SLOTS_JACKPOT_LINES = [
    "Okay, NOW I'm paying attention.",
    "Alright, big winner over here. Everyone look.",
    "I don't know how you did that, but I'm impressed.",
    "Someone's buying the next round.",
    "That's disgustingly lucky.",
    "The machine finally coughed something up.",
]

SLOTS_WIN_LINES = [
    "Not bad. Not bad at all.",
    "Two out of three ain't nothing.",
    "The machine likes you tonight. Suspicious, but I'll allow it.",
    "A little profit never hurt.",
    "At least somebody's leaving happier than they arrived.",
]

SLOTS_LOSE_LINES = [
    "That spin was rough. I'm not even charging you emotionally.",
    "The house always wins eventually. Today was 'eventually.'",
    "Painful. Truly painful to watch.",
    "That's one for the memory book. Not a good one.",
    "Your coins have officially gone on vacation.",
    "The machine saw you coming.",
]

# ============================================================
# MUSIC / YT-DLP
# ============================================================

YTDL_OPTIONS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
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
            ],
        }
    },
}

# IMPORTANT:
# Never give yt-dlp the /etc/secrets path directly.
# Use the writable /tmp copy instead.
if os.path.exists(YTDLP_RUNTIME_COOKIES):
    YTDL_OPTIONS["cookiefile"] = YTDLP_RUNTIME_COOKIES
    logger.info(
        f"Using YouTube cookies from "
        f"{YTDLP_RUNTIME_COOKIES}"
    )
else:
    logger.warning(
        "No YouTube cookie file available."
    )

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5"
    ),
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(
        self,
        source,
        *,
        data,
        volume=0.5
    ):
        super().__init__(source, volume)

        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.webpage_url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")
        self.uploader = data.get("uploader")
        self.duration = data.get("duration")

    @classmethod
    async def from_url(
        cls,
        url,
        *,
        loop=None,
        stream=True
    ):

        loop = loop or asyncio.get_event_loop()

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


def format_duration(seconds):

    if not seconds:
        return "Live/Unknown"

    minutes, secs = divmod(
        int(seconds),
        60
    )

    hours, minutes = divmod(
        minutes,
        60
    )

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


# ============================================================
# ERROR EMBED
# ============================================================

def error_embed(message):

    return discord.Embed(
        description=f"❌ {message}",
        color=discord.Color.red()
    )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    logger.info(
        f"Logged in as {bot.user} "
        f"(ID: {bot.user.id})"
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
# MUSIC COMMANDS
# ============================================================

@bot.command(name="join")
async def join(ctx):

    if (
        ctx.author.voice is None
        or ctx.author.voice.channel is None
    ):
        await ctx.send(
            embed=error_embed(
                "Join a voice channel first."
            )
        )
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None:

        await ctx.voice_client.move_to(
            channel
        )

    else:

        await channel.connect()

    embed = discord.Embed(
        description=f"🎤 Joined **{channel.name}**",
        color=EMBED_COLOR
    )

    await ctx.send(embed=embed)


async def play_song(
    ctx: commands.Context,
    query: str
):

    if ctx.voice_client is None:

        if (
            ctx.author.voice is None
            or ctx.author.voice.channel is None
        ):
            await ctx.send(
                embed=error_embed(
                    "Join a voice channel first, "
                    "or use `!join`."
                )
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
                "Failed to extract/stream audio"
            )

            error_text = str(e)

            if (
                "Sign in to confirm" in error_text
                or "cookies" in error_text.lower()
                or "bot" in error_text.lower()
            ):
                message = (
                    "YouTube blocked the request. "
                    "The cookie file may be expired or "
                    "invalid. Try exporting fresh YouTube "
                    "cookies."
                )
            else:
                message = (
                    "Couldn't find or play that."
                )

            await ctx.send(
                embed=error_embed(
                    f"{message}\n\n"
                    f"`{error_text[:800]}`"
                )
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

    embed = discord.Embed(
        title="🎵 Now Playing",
        description=(
            f"**[{player.title}]"
            f"({player.webpage_url or ''})**"
        ),
        color=EMBED_COLOR
    )

    if player.uploader:

        embed.add_field(
            name="Uploader",
            value=player.uploader,
            inline=True
        )

    embed.add_field(
        name="Duration",
        value=format_duration(
            player.duration
        ),
        inline=True
    )

    if player.thumbnail:
        embed.set_thumbnail(
            url=player.thumbnail
        )

    embed.set_footer(
        text=f"Requested by "
             f"{ctx.author.display_name}",
        icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)


@bot.command(name="play")
async def play(
    ctx: commands.Context,
    *,
    query: str
):

    await play_song(
        ctx,
        query
    )


@bot.command(name="leave")
async def leave(ctx):

    if ctx.voice_client is None:

        await ctx.send(
            embed=error_embed(
                "I'm not connected to a voice channel."
            )
        )

        return

    await ctx.voice_client.disconnect()

    await ctx.send(
        embed=discord.Embed(
            description="👋 Disconnected.",
            color=EMBED_COLOR
        )
    )


# ============================================================
# DOWNLOAD
# ============================================================

@bot.command(
    name="download",
    aliases=["dl", "send"]
)
async def download_song(
    ctx: commands.Context,
    *,
    query: str
):

    status = await ctx.send(
        embed=discord.Embed(
            description=(
                f"⏳ Fetching **{query}**..."
            ),
            color=EMBED_COLOR
        )
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
            "bestaudio[ext=m4a]/bestaudio/best",

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

        "quiet":
            True,

        "no_warnings":
            True,

        "noplaylist":
            True,

        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web"
                ]
            }
        }
    }

    # IMPORTANT:
    # Use /tmp copy, NOT /etc/secrets.
    if os.path.exists(
        YTDLP_RUNTIME_COOKIES
    ):

        dl_opts[
            "cookiefile"
        ] = YTDLP_RUNTIME_COOKIES

    loop = asyncio.get_event_loop()

    mp3_path = None

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

        error_text = str(e)

        await status.edit(
            embed=error_embed(
                f"Couldn't download that.\n"
                f"`{error_text[:1000]}`"
            )
        )

        return

    if not mp3_path or not os.path.exists(
        mp3_path
    ):

        await status.edit(
            embed=error_embed(
                "The MP3 file wasn't created."
            )
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
            embed=error_embed(
                f"**{title}** is too large "
                f"to upload here "
                f"({size // (1024 * 1024)}MB).\n\n"
                f"Try `!play {query}` instead."
            )
        )

        try:
            os.remove(mp3_path)
        except OSError:
            pass

        return

    await status.delete()

    embed = discord.Embed(
        title="🎵 Download Ready",
        description=f"**{title}**",
        color=EMBED_COLOR
    )

    thumbnail = info.get(
        "thumbnail"
    )

    if thumbnail:
        embed.set_thumbnail(
            url=thumbnail
        )

    embed.set_footer(
        text=f"Requested by "
             f"{ctx.author.display_name}",
        icon_url=ctx.author.display_avatar.url
    )

    try:

        await ctx.send(
            embed=embed,
            file=discord.File(
                mp3_path,
                filename=(
                    f"{title[:80]}.mp3"
                )
            )
        )

    finally:

        try:
            os.remove(mp3_path)
        except OSError:
            pass


# ============================================================
# ECONOMY
# ============================================================

ECONOMY_FILE = "economy.json"

STARTING_BALANCE = 100
DAILY_AMOUNT = 200

WORK_MIN = 50
WORK_MAX = 150

WORK_COOLDOWN = timedelta(
    hours=1
)

DAILY_COOLDOWN = timedelta(
    hours=24
)


def load_economy():

    if os.path.exists(
        ECONOMY_FILE
    ):

        try:

            with open(
                ECONOMY_FILE,
                "r"
            ) as f:

                return json.load(f)

        except (
            json.JSONDecodeError,
            OSError
        ):

            return {}

    return {}


def save_economy():

    with open(
        ECONOMY_FILE,
        "w"
    ) as f:

        json.dump(
            economy,
            f,
            indent=2
        )


economy = load_economy()


def get_user(uid):

    uid = str(uid)

    if uid not in economy:

        economy[uid] = {
            "balance":
                STARTING_BALANCE,

            "last_daily":
                None,

            "last_work":
                None
        }

    return economy[uid]


@bot.command(
    name="balance",
    aliases=["bal"]
)
async def balance(ctx):

    user = get_user(
        ctx.author.id
    )

    embed = discord.Embed(
        title="💰 Balance",
        description=(
            f"**{user['balance']:,}** coins"
        ),
        color=discord.Color.gold()
    )

    embed.set_author(
        name=ctx.author.display_name,
        icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(
        embed=embed
    )


@bot.command(name="daily")
async def daily(ctx):

    user = get_user(
        ctx.author.id
    )

    now = datetime.now(
        timezone.utc
    )

    if user["last_daily"]:

        last = datetime.fromisoformat(
            user["last_daily"]
        )

        if now - last < DAILY_COOLDOWN:

            remaining = (
                DAILY_COOLDOWN
                - (now - last)
            )

            hrs, rem = divmod(
                int(
                    remaining.total_seconds()
                ),
                3600
            )

            mins = rem // 60

            await ctx.send(
                embed=error_embed(
                    f"Already claimed. "
                    f"Try again in "
                    f"**{hrs}h {mins}m**."
                )
            )

            return

    user["balance"] += DAILY_AMOUNT

    user["last_daily"] = (
        now.isoformat()
    )

    save_economy()

    await ctx.send(
        embed=discord.Embed(
            title="🎁 Daily Reward",
            description=(
                f"Claimed **{DAILY_AMOUNT} coins**!\n"
                f"Balance: "
                f"**{user['balance']:,}**"
            ),
            color=discord.Color.gold()
        )
    )


@bot.command(name="work")
async def work(ctx):

    user = get_user(
        ctx.author.id
    )

    now = datetime.now(
        timezone.utc
    )

    if user["last_work"]:

        last = datetime.fromisoformat(
            user["last_work"]
        )

        if now - last < WORK_COOLDOWN:

            remaining = (
                WORK_COOLDOWN
                - (now - last)
            )

            mins = int(
                remaining.total_seconds()
                // 60
            )

            await ctx.send(
                embed=error_embed(
                    f"You're tired. "
                    f"Rest **{mins}m**."
                )
            )

            return

    earned = random.randint(
        WORK_MIN,
        WORK_MAX
    )

    user["balance"] += earned

    user["last_work"] = (
        now.isoformat()
    )

    save_economy()

    await ctx.send(
        embed=discord.Embed(
            title="🛠️ Work Complete",
            description=(
                f"Earned **{earned} coins**!\n"
                f"Balance: "
                f"**{user['balance']:,}**"
            ),
            color=discord.Color.gold()
        )
    )


# ============================================================
# COINFLIP
# ============================================================

@bot.command(
    name="coinflip",
    aliases=["cf"]
)
async def coinflip(
    ctx,
    amount: int,
    choice: str
):

    choice = choice.lower()

    if choice not in (
        "heads",
        "tails"
    ):

        await ctx.send(
            embed=error_embed(
                "Choose `heads` or `tails`."
            )
        )

        return

    user = get_user(
        ctx.author.id
    )

    if (
        amount <= 0
        or amount > user["balance"]
    ):

        await ctx.send(
            embed=error_embed(
                "Invalid bet amount."
            )
        )

        return

    result = random.choice(
        ["heads", "tails"]
    )

    won = result == choice

    if won:

        user["balance"] += amount

        flavor = random.choice(
            COINFLIP_WIN_LINES
        )

    else:

        user["balance"] -= amount

        flavor = random.choice(
            COINFLIP_LOSE_LINES
        )

    save_economy()

    await ctx.send(
        embed=discord.Embed(
            title="🪙 Coin Flip",
            description=(
                f"Landed on **{result}**!\n"
                f"{'🎉 You won' if won else '💀 You lost'} "
                f"**{amount:,} coins**\n"
                f"Balance: "
                f"**{user['balance']:,}**\n\n"
                f"*\"{flavor}\"*"
            ),
            color=(
                discord.Color.green()
                if won
                else discord.Color.red()
            )
        )
    )


# ============================================================
# SLOTS
# ============================================================

@bot.command(name="slots")
async def slots(
    ctx,
    amount: int
):

    user = get_user(
        ctx.author.id
    )

    if (
        amount <= 0
        or amount > user["balance"]
    ):

        await ctx.send(
            embed=error_embed(
                "Invalid bet amount."
            )
        )

        return

    symbols = [
        "🍒",
        "🍋",
        "🍇",
        "💎",
        "7️⃣"
    ]

    spin = [
        random.choice(symbols)
        for _ in range(3)
    ]

    display = " | ".join(
        spin
    )

    if (
        spin[0]
        == spin[1]
        == spin[2]
    ):

        winnings = amount * 5

        user["balance"] += winnings

        result_text = (
            f"🎉 **JACKPOT!** "
            f"You won "
            f"**{winnings:,} coins**"
        )

        color = discord.Color.gold()

        flavor = random.choice(
            SLOTS_JACKPOT_LINES
        )

    elif (
        spin[0] == spin[1]
        or spin[1] == spin[2]
    ):

        winnings = amount * 2

        user["balance"] += winnings

        result_text = (
            f"✨ **Nice!** "
            f"You won "
            f"**{winnings:,} coins**"
        )

        color = discord.Color.green()

        flavor = random.choice(
            SLOTS_WIN_LINES
        )

    else:

        user["balance"] -= amount

        result_text = (
            f"💀 No match. "
            f"You lost "
            f"**{amount:,} coins**"
        )

        color = discord.Color.red()

        flavor = random.choice(
            SLOTS_LOSE_LINES
        )

    save_economy()

    await ctx.send(
        embed=discord.Embed(
            title="🎰 Slots",
            description=(
                f"**{display}**\n\n"
                f"{result_text}\n"
                f"Balance: "
                f"**{user['balance']:,}**\n\n"
                f"*\"{flavor}\"*"
            ),
            color=color
        )
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

    category = random.choice(
        list(
            EIGHTBALL_RESPONSES.keys()
        )
    )

    reply = random.choice(
        EIGHTBALL_RESPONSES[
            category
        ]
    )

    embed = discord.Embed(
        title="🎱",
        description=(
            f"**{question}**\n\n"
            f"{reply}"
        ),
        color=EMBED_COLOR
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# RPS
# ============================================================

RPS_CHOICES = [
    "rock",
    "paper",
    "scissors"
]

RPS_EMOJI = {
    "rock": "🪨",
    "paper": "📄",
    "scissors": "✂️"
}


def rps_outcome(
    player,
    opponent
):

    if player == opponent:
        return "tie"

    wins = {
        "rock": "scissors",
        "paper": "rock",
        "scissors": "paper"
    }

    if wins[player] == opponent:
        return "win"

    return "lose"


@bot.command(name="rps")
async def rps(
    ctx,
    choice: str
):

    choice = choice.lower()

    if choice not in RPS_CHOICES:

        await ctx.send(
            embed=error_embed(
                "Use `rock`, `paper`, "
                "or `scissors`."
            )
        )

        return

    bot_choice = random.choice(
        RPS_CHOICES
    )

    outcome = rps_outcome(
        choice,
        bot_choice
    )

    user = get_user(
        ctx.author.id
    )

    if outcome == "win":

        reward = 50

        user["balance"] += reward

        save_economy()

        text = (
            f"🎉 **You win!** "
            f"+{reward} coins"
        )

        color = discord.Color.green()

    elif outcome == "tie":

        text = (
            "🤝 Tie. Nobody's buying "
            "a round for that."
        )

        color = EMBED_COLOR

    else:

        text = (
            "💀 You lose. "
            "Try again."
        )

        color = discord.Color.red()

    await ctx.send(
        embed=discord.Embed(
            title="✊ Rock Paper Scissors",
            description=(
                f"You: "
                f"{RPS_EMOJI[choice]} "
                f"vs "
                f"Bot: "
                f"{RPS_EMOJI[bot_choice]}\n\n"
                f"{text}"
            ),
            color=color
        )
    )


# ============================================================
# DICE
# ============================================================

@bot.command(
    name="roll",
    aliases=["dice"]
)
async def roll(
    ctx,
    sides: int = 6
):

    if sides < 2 or sides > 1000:

        await ctx.send(
            embed=error_embed(
                "Choose between "
                "2 and 1000 sides."
            )
        )

        return

    result = random.randint(
        1,
        sides
    )

    await ctx.send(
        embed=discord.Embed(
            description=(
                f"🎲 "
                f"{ctx.author.mention} "
                f"rolled **{result}** "
                f"(1-{sides})"
            ),
            color=EMBED_COLOR
        )
    )


# ============================================================
# LEVELING
# ============================================================

LEVEL_FILE = "levels.json"

XP_MIN = 8
XP_MAX = 18

XP_COOLDOWN_SECONDS = 45

levels = {}

if os.path.exists(
    LEVEL_FILE
):

    try:

        with open(
            LEVEL_FILE,
            "r"
        ) as f:

            levels = json.load(f)

    except (
        json.JSONDecodeError,
        OSError
    ):

        levels = {}

xp_cooldowns = {}

RANK_TITLES = [
    (1, "Newcomer"),
    (5, "Regular"),
    (10, "Regular+"),
    (20, "Veteran"),
    (35, "Elite"),
    (50, "Legend"),
    (100, "Mythic")
]


def save_levels():

    with open(
        LEVEL_FILE,
        "w"
    ) as f:

        json.dump(
            levels,
            f,
            indent=2
        )


def get_level_data(
    guild_id,
    user_id
):

    guild_id = str(guild_id)
    user_id = str(user_id)

    levels.setdefault(
        guild_id,
        {}
    )

    levels[
        guild_id
    ].setdefault(
        user_id,
        {
            "xp": 0,
            "level": 1
        }
    )

    return levels[
        guild_id
    ][user_id]


def xp_required(level):

    return level * 100


def rank_title(level):

    title = "Newcomer"

    for threshold, name in RANK_TITLES:

        if level >= threshold:
            title = name

    return title


def add_xp(
    guild_id,
    user_id,
    amount=None
):

    data = get_level_data(
        guild_id,
        user_id
    )

    old_level = data["level"]

    if amount is None:

        amount = random.randint(
            XP_MIN,
            XP_MAX
        )

    data["xp"] += amount

    while (
        data["xp"]
        >= xp_required(
            data["level"]
        )
    ):

        data["xp"] -= xp_required(
            data["level"]
        )

        data["level"] += 1

    save_levels()

    return (
        amount,
        old_level,
        data["level"]
    )


def make_xp_bar(
    current,
    maximum,
    length=12
):

    if maximum <= 0:
        return "█" * length

    filled = int(
        length
        * min(
            current / maximum,
            1
        )
    )

    return (
        "█" * filled
        + "░" * (
            length - filled
        )
    )


@bot.event
async def on_message(
    message
):

    if message.author.bot:

        await bot.process_commands(
            message
        )

        return

    if message.guild:

        key = (
            f"{message.guild.id}:"
            f"{message.author.id}"
        )

        now = asyncio.get_event_loop().time()

        if (
            now
            - xp_cooldowns.get(
                key,
                0
            )
            >= XP_COOLDOWN_SECONDS
        ):

            xp_cooldowns[key] = now

            (
                amount,
                old_level,
                new_level
            ) = add_xp(
                message.guild.id,
                message.author.id
            )

            if new_level > old_level:

                embed = discord.Embed(
                    description=(
                        f"🎉 "
                        f"{message.author.mention} "
                        f"just hit "
                        f"**Level {new_level}** "
                        f"— **{rank_title(new_level)}** now."
                    ),
                    color=discord.Color.gold()
                )

                try:

                    await message.channel.send(
                        embed=embed
                    )

                except discord.Forbidden:
                    pass

    await bot.process_commands(
        message
    )


@bot.command(
    name="rank",
    aliases=[
        "level",
        "lvl"
    ]
)
async def rank(
    ctx,
    member: discord.Member = None
):

    member = (
        member
        or ctx.author
    )

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
            x[1]["level"],
            x[1]["xp"]
        ),
        reverse=True
    )

    position = next(
        (
            i
            for i, (
                uid,
                _
            ) in enumerate(
                ranking,
                1
            )
            if uid == str(
                member.id
            )
        ),
        len(ranking)
    )

    needed = xp_required(
        data["level"]
    )

    bar = make_xp_bar(
        data["xp"],
        needed
    )

    embed = discord.Embed(
        title=(
            f"⭐ "
            f"{member.display_name}'s Rank"
        ),
        color=EMBED_COLOR
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="Level",
        value=(
            f"**{data['level']}** — "
            f"{rank_title(data['level'])}"
        ),
        inline=True
    )

    embed.add_field(
        name="XP",
        value=(
            f"**{data['xp']:,} / "
            f"{needed:,}**"
        ),
        inline=True
    )

    embed.add_field(
        name="Server Rank",
        value=f"**#{position}**",
        inline=True
    )

    embed.add_field(
        name="Progress",
        value=f"`{bar}`",
        inline=False
    )

    await ctx.send(
        embed=embed
    )


@bot.command(
    name="xpleaderboard",
    aliases=[
        "xplb",
        "levels"
    ]
)
async def xp_leaderboard(ctx):

    guild_data = levels.get(
        str(ctx.guild.id),
        {}
    )

    if not guild_data:

        await ctx.send(
            embed=error_embed(
                "Nobody's earned XP yet."
            )
        )

        return

    ranking = sorted(
        guild_data.items(),
        key=lambda x: (
            x[1]["level"],
            x[1]["xp"]
        ),
        reverse=True
    )[:10]

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    lines = []

    for i, (
        uid,
        data
    ) in enumerate(
        ranking,
        1
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
            f"{prefix} "
            f"**{name}** — "
            f"Level `{data['level']}` "
            f"• `{data['xp']} XP`"
        )

    await ctx.send(
        embed=discord.Embed(
            title="🏆 XP Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
    )


@bot.command(
    name="profile",
    aliases=["me"]
)
async def profile(
    ctx,
    member: discord.Member = None
):

    member = (
        member
        or ctx.author
    )

    user = get_user(
        member.id
    )

    level_data = get_level_data(
        ctx.guild.id,
        member.id
    )

    embed = discord.Embed(
        title=f"👤 {member.display_name}",
        color=EMBED_COLOR
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="⭐ Level",
        value=(
            f"{level_data['level']} — "
            f"{rank_title(level_data['level'])}"
        ),
        inline=True
    )

    embed.add_field(
        name="✨ XP",
        value=f"{level_data['xp']:,}",
        inline=True
    )

    embed.add_field(
        name="💰 Coins",
        value=f"{user['balance']:,}",
        inline=True
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# LEADERBOARD
# ============================================================

@bot.command(
    name="leaderboard",
    aliases=["lb"]
)
async def leaderboard(ctx):

    top = sorted(
        economy.items(),
        key=lambda x: x[1]["balance"],
        reverse=True
    )[:10]

    if not top:

        await ctx.send(
            embed=error_embed(
                "No data yet."
            )
        )

        return

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    lines = []

    for i, (
        uid,
        data
    ) in enumerate(
        top,
        1
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
            f"{prefix} "
            f"{name} — "
            f"`{data['balance']:,}` coins"
        )

    await ctx.send(
        embed=discord.Embed(
            title="🏆 Coin Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
    )


# ============================================================
# INTERACTIVE GAME MENU
# ============================================================

class GameMenuView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

    @discord.ui.button(
        label="🎲 Roll",
        style=discord.ButtonStyle.primary
    )
    async def roll_button(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            f"🎲 Rolled **{random.randint(1, 6)}**!"
        )

    @discord.ui.button(
        label="✊ RPS",
        style=discord.ButtonStyle.success
    )
    async def rps_button(
        self,
        interaction,
        button
    ):

        choice = random.choice(
            RPS_CHOICES
        )

        await interaction.response.send_message(
            f"✊ Random opponent throws "
            f"{RPS_EMOJI[choice]}!"
        )

    @discord.ui.button(
        label="🎱 8-Ball",
        style=discord.ButtonStyle.secondary
    )
    async def ball_button(
        self,
        interaction,
        button
    ):

        category = random.choice(
            list(
                EIGHTBALL_RESPONSES.keys()
            )
        )

        await interaction.response.send_message(
            f"🎱 "
            f"{random.choice(EIGHTBALL_RESPONSES[category])}"
        )


@bot.command(name="games")
async def games_menu(ctx):

    embed = discord.Embed(
        title="🎮 Game Center",
        description=(
            "**Commands**\n\n"
            "`!coinflip <amount> heads/tails`\n"
            "`!slots <amount>`\n"
            "`!rps rock/paper/scissors`\n"
            "`!roll [sides]`\n"
            "`!8ball <question>`\n\n"
            "Or just tap a button below 👇"
        ),
        color=discord.Color.green()
    )

    await ctx.send(
        embed=embed,
        view=GameMenuView()
    )


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


BASE_PERSONALITY = (

    "You are a recurring character who hangs "
    "around this Discord server. "

    "You are NOT a customer support bot. "

    "Talk naturally, casually, and unpredictably. "

    "You don't need to answer every message "
    "with an explanation. Sometimes one sentence "
    "is enough. Sometimes a short reaction is better. "

    "Don't constantly use emojis. "

    "Don't constantly use slang. "

    "Don't call everyone bro. "

    "Don't start every response the same way. "

    "Don't sound like an AI assistant. "

    "If someone jokes, joke back. "

    "If someone roasts you, play along. "

    "If someone vents, actually listen. "

    "If someone asks something serious, become sincere. "

    "Remember details from the recent conversation "
    "when useful. "

    "Keep replies conversational and relatively short. "

    "You're allowed to have opinions. "

    "You're allowed to say you don't know. "

    "Avoid repetitive phrases. "

    "Don't force bartender metaphors into every message. "
)


CHAT_MODES = {

    "bartender": (

        "You're the bartender of this server. "

        "You're relaxed, observant, witty, "
        "slightly sarcastic, and occasionally "
        "unexpectedly thoughtful. "

        "Imagine someone sitting at the bar "
        "talking to you at 1 AM. "

        "You listen more than you lecture. "

        + BASE_PERSONALITY
    ),

    "casino": (

        "You're running a late-night casino. "

        "You're playful, cocky, observant, "
        "and occasionally tempt people into "
        "taking ridiculous bets. "

        + BASE_PERSONALITY
    ),

    "dj": (

        "You're the DJ hanging around after hours. "

        "You're laid-back, music-obsessed, "
        "and occasionally have strong opinions "
        "about songs. "

        + BASE_PERSONALITY
    ),

    "menace": (

        "You're the resident troublemaker. "

        "You're playful, teasing, chaotic, "
        "and quick with jokes. "

        "Don't become genuinely cruel. "

        + BASE_PERSONALITY
    ),

    "normal": (

        "You're a normal friendly regular "
        "hanging around the server. "

        + BASE_PERSONALITY
    )
}


DEFAULT_MODE = "bartender"

channel_modes = {}


@bot.command(name="mode")
async def mode(
    ctx,
    choice: str = None
):

    channel_id = str(
        ctx.channel.id
    )

    if choice is None:

        current = channel_modes.get(
            channel_id,
            DEFAULT_MODE
        )

        await ctx.send(
            embed=discord.Embed(
                title="🎭 Current Mode",
                description=(
                    f"This channel's bot personality "
                    f"is set to **{current}**.\n\n"
                    f"Options: "
                    f"{', '.join(CHAT_MODES.keys())}\n\n"
                    f"Usage: `!mode <name>`"
                ),
                color=EMBED_COLOR
            )
        )

        return

    choice = choice.lower()

    if choice not in CHAT_MODES:

        await ctx.send(
            embed=error_embed(
                "Unknown mode. Options: "
                + ", ".join(
                    CHAT_MODES.keys()
                )
            )
        )

        return

    channel_modes[
        channel_id
    ] = choice

    await ctx.send(
        embed=discord.Embed(
            description=(
                f"🎭 Mode switched to "
                f"**{choice}**."
            ),
            color=EMBED_COLOR
        )
    )


@bot.command(name="chat")
async def chat(
    ctx,
    *,
    message: str
):

    if not ANTHROPIC_API_KEY:

        await ctx.send(
            embed=error_embed(
                "AI chat isn't set up yet — "
                "missing `ANTHROPIC_API_KEY`."
            )
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

    system_prompt = CHAT_MODES.get(
        channel_modes.get(
            channel_id,
            DEFAULT_MODE
        ),
        CHAT_MODES[
            DEFAULT_MODE
        ]
    )

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
                            system_prompt,

                        "messages":
                            history
                    }
                ) as resp:

                    data = await resp.json()

                    if resp.status != 200:

                        logger.error(
                            f"Claude API error: "
                            f"{data}"
                        )

                        await ctx.send(
                            embed=error_embed(
                                "Sorry, I couldn't "
                                "get a response right now."
                            )
                        )

                        return

                    reply = data[
                        "content"
                    ][0]["text"]

        except Exception:

            logger.exception(
                "Claude API call failed"
            )

            await ctx.send(
                embed=error_embed(
                    "Something went wrong "
                    "reaching the AI."
                )
            )

            return

    history.append(
        {
            "role": "assistant",
            "content": reply
        }
    )

    history[:] = history[
        -MAX_HISTORY:
    ]

    embed = discord.Embed(
        description=reply[:4000],
        color=EMBED_COLOR
    )

    if bot.user:

        embed.set_author(
            name="🤖 Music Delivery",
            icon_url=(
                bot.user
                .display_avatar
                .url
            )
        )

    await ctx.send(
        embed=embed
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
        title="🎵 Music Delivery — Commands",
        color=EMBED_COLOR
    )

    embed.add_field(
        name="🎶 Music",
        value=(
            "`!play <song>`\n"
            "`!download <song>`\n"
            "`!join` • `!leave`\n"
            "Tip: `!<song name>` also works."
        ),
        inline=False
    )

    embed.add_field(
        name="⭐ Leveling",
        value=(
            "`!rank`\n"
            "`!profile`\n"
            "`!xpleaderboard`"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Economy",
        value=(
            "`!balance`\n"
            "`!daily`\n"
            "`!work`\n"
            "`!leaderboard`"
        ),
        inline=False
    )

    embed.add_field(
        name="🎮 Games",
        value=(
            "`!games`\n"
            "`!coinflip <amount> heads/tails`\n"
            "`!slots <amount>`\n"
            "`!rps rock/paper/scissors`\n"
            "`!roll [sides]`\n"
            "`!8ball <question>`"
        ),
        inline=False
    )

    embed.add_field(
        name="🎭 Personality",
        value=(
            "`!mode`\n"
            "`!mode bartender`\n"
            "`!mode casino`\n"
            "`!mode dj`\n"
            "`!mode menace`\n"
            "`!mode normal`"
        ),
        inline=False
    )

    embed.add_field(
        name="🤖 AI",
        value=(
            "`!chat <message>`"
        ),
        inline=False
    )

    embed.set_footer(
        text="Music Delivery Bot"
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# UNKNOWN !COMMAND = SEARCH SONG
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
    "8ball",
    "8b",
    "leaderboard",
    "lb",
    "chat",
    "help",
    "commands",
    "rank",
    "level",
    "lvl",
    "xpleaderboard",
    "xplb",
    "levels",
    "profile",
    "me",
    "mode",
    "rps",
    "roll",
    "dice",
    "games"
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
            embed=error_embed(
                "Missing something. "
                "Try `!help`."
            )
        )

        return

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            embed=error_embed(
                "I couldn't understand "
                "that argument. "
                "Try `!help`."
            )
        )

        return

    logger.error(
        f"Command error: {error}"
    )


# ============================================================
# RENDER KEEP-ALIVE WEB SERVER
# ============================================================

async def health(request):

    return web.Response(
        text="Bot is running."
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
        f"Health check server "
        f"listening on port {port}"
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
