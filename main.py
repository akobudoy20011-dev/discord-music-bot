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

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Render Secret File:
# /etc/secrets/cookies.txt
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

if YTDLP_COOKIES_FILE:
    if os.path.isfile(YTDLP_COOKIES_FILE):
        logger.info("YouTube cookies file found.")
    else:
        logger.warning(
            f"YouTube cookies file was configured but not found: "
            f"{YTDLP_COOKIES_FILE}"
        )
else:
    logger.warning(
        "YTDLP_COOKIES_FILE is not set. "
        "YouTube may reject requests from the Render server."
    )


# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
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

    # YouTube client settings
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    },
}

# Add cookies only if Render provided the cookie path.
if YTDLP_COOKIES_FILE:
    YTDL_OPTIONS["cookiefile"] = YTDLP_COOKIES_FILE


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

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data
        self.title = data.get("title", "Unknown")
        self.url = data.get("url")
        self.webpage_url = data.get("webpage_url")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):

        loop = loop or asyncio.get_event_loop()

        # If the user typed a YouTube URL, use it.
        # Otherwise search YouTube.
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

        if not data:
            raise RuntimeError("No YouTube result was found.")

        if "entries" in data:
            entries = data.get("entries") or []

            if not entries:
                raise RuntimeError("No YouTube result was found.")

            data = entries[0]

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


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    logger.info(
        f"Logged in as {bot.user} "
        f"(ID: {bot.user.id})"
    )


# ============================================================
# JOIN
# ============================================================

@bot.command(name="join")
async def join(ctx: commands.Context):

    if (
        ctx.author.voice is None
        or ctx.author.voice.channel is None
    ):
        await ctx.send(
            "🎤 You need to be in a voice channel first."
        )
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()

    await ctx.send(
        f"🎤 Joined **{channel.name}**."
    )


# ============================================================
# PLAY MUSIC
# ============================================================

async def play_song(
    ctx: commands.Context,
    query: str
):

    # Join user's voice channel automatically.
    if ctx.voice_client is None:

        if (
            ctx.author.voice is None
            or ctx.author.voice.channel is None
        ):
            await ctx.send(
                "🎤 You need to be in a voice channel, "
                "or use `!join` first."
            )
            return

        await ctx.author.voice.channel.connect()

    voice_client = ctx.voice_client

    # Stop currently playing song.
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
                or "not a bot" in error_text
                or "cookies" in error_text.lower()
            ):

                await ctx.send(
                    "❌ YouTube blocked the request.\n"
                    "Make sure the Render `cookies.txt` Secret File "
                    "and `YTDLP_COOKIES_FILE` environment variable "
                    "are configured correctly."
                )

            else:

                await ctx.send(
                    f"❌ Couldn't find or play that: "
                    f"`{error_text[:500]}`"
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

    link = player.webpage_url or ""

    await ctx.send(
        f"🎵 **Now playing:** {player.title}\n"
        f"{link}"
    )


@bot.command(name="play")
async def play(
    ctx: commands.Context,
    *,
    query: str
):

    await play_song(ctx, query)


# ============================================================
# LEAVE
# ============================================================

@bot.command(name="leave")
async def leave(ctx: commands.Context):

    if ctx.voice_client is None:

        await ctx.send(
            "I'm not connected to a voice channel."
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
    ctx: commands.Context,
    *,
    query: str
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
        "format": "bestaudio/best",

        "outtmpl": (
            "downloads/%(id)s.%(ext)s"
        ),

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
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
        },
    }

    # IMPORTANT:
    # Give the download system the same cookies.
    if YTDLP_COOKIES_FILE:
        dl_opts["cookiefile"] = YTDLP_COOKIES_FILE

    loop = asyncio.get_event_loop()

    mp3_path = None
    info = None

    try:

        with yt_dlp.YoutubeDL(dl_opts) as ydl:

            info = await loop.run_in_executor(
                None,
                lambda: ydl.extract_info(
                    query_url,
                    download=True
                )
            )

            if not info:
                raise RuntimeError(
                    "No YouTube result was found."
                )

            if "entries" in info:

                entries = info.get("entries") or []

                if not entries:
                    raise RuntimeError(
                        "No YouTube result was found."
                    )

                info = entries[0]

            base, _ = os.path.splitext(
                ydl.prepare_filename(info)
            )

            mp3_path = base + ".mp3"

    except Exception as e:

        logger.exception(
            "Download failed"
        )

        error_text = str(e)

        if (
            "Sign in to confirm" in error_text
            or "not a bot" in error_text
            or "cookies" in error_text.lower()
        ):

            await status.edit(
                content=(
                    "❌ YouTube blocked the download.\n"
                    "Check the Render `cookies.txt` Secret File "
                    "and `YTDLP_COOKIES_FILE` environment variable."
                )
            )

        else:

            await status.edit(
                content=(
                    f"❌ Couldn't download that:\n"
                    f"`{error_text[:500]}`"
                )
            )

        return

    # Make sure the MP3 actually exists.
    if not mp3_path or not os.path.exists(mp3_path):

        await status.edit(
            content=(
                "❌ The MP3 file wasn't created."
            )
        )

        return

    # Discord upload limit.
    limit = (
        ctx.guild.filesize_limit
        if ctx.guild
        else 25 * 1024 * 1024
    )

    size = os.path.getsize(mp3_path)

    title = info.get(
        "title",
        "audio"
    )

    # Discord file too large.
    if size > limit:

        await status.edit(
            content=(
                f"⚠️ **{title}** is too large to upload here "
                f"({size // (1024 * 1024)}MB).\n"
                f"Try `!play {query}` to stream it instead."
            )
        )

        try:
            os.remove(mp3_path)
        except OSError:
            pass

        return

    # Upload file.
    await status.delete()

    safe_filename = (
        title[:80]
        .replace("/", "_")
        .replace("\\", "_")
    )

    await ctx.send(
        content=f"🎵 **{title}**",
        file=discord.File(
            mp3_path,
            filename=f"{safe_filename}.mp3"
        )
    )

    # Delete temporary MP3.
    try:
        os.remove(mp3_path)
    except OSError:
        pass


# ============================================================
# KNOWN COMMANDS
# ============================================================

KNOWN_COMMANDS = {
    "join",
    "play",
    "leave",
    "download",
    "dl",
    "send",

    # Economy
    "balance",
    "bal",
    "daily",
    "work",
    "coinflip",
    "cf",
    "slots",
    "leaderboard",
    "lb",

    # AI
    "chat",

    # Help
    "help",
}


# ============================================================
# COMMAND ERROR HANDLER
# ============================================================

@bot.event
async def on_command_error(
    ctx: commands.Context,
    error
):

    # User typed !play without a song.
    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ Missing something.\n"
            "Example: `!play amatz`"
        )

        return

    # Unknown command = automatically search YouTube.
    if isinstance(
        error,
        commands.CommandNotFound
    ):

        query = (
            ctx.message.content[
                len(ctx.prefix):
            ]
            .strip()
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

    logger.error(
        f"Command error: {error}"
    )


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
            "balance": STARTING_BALANCE,
            "last_daily": None,
            "last_work": None
        }

    return economy[uid]


# ============================================================
# BALANCE
# ============================================================

@bot.command(
    name="balance",
    aliases=["bal"]
)
async def balance(ctx):

    user = get_user(
        ctx.author.id
    )

    await ctx.send(
        f"💰 {ctx.author.mention}, "
        f"you have **{user['balance']}** coins."
    )


# ============================================================
# DAILY
# ============================================================

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

        if (
            now - last
            < DAILY_COOLDOWN
        ):

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
                f"⏳ Already claimed. "
                f"Try again in **{hrs}h {mins}m**."
            )

            return

    user["balance"] += DAILY_AMOUNT

    user["last_daily"] = (
        now.isoformat()
    )

    save_economy()

    await ctx.send(
        f"✅ {ctx.author.mention} claimed "
        f"**{DAILY_AMOUNT}** coins!\n"
        f"💰 Balance: **{user['balance']}**."
    )


# ============================================================
# WORK
# ============================================================

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

        if (
            now - last
            < WORK_COOLDOWN
        ):

            remaining = (
                WORK_COOLDOWN
                - (now - last)
            )

            mins = int(
                remaining.total_seconds()
                // 60
            )

            await ctx.send(
                f"⏳ You're tired. "
                f"Rest **{mins}m** before working again."
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
        f"🛠️ {ctx.author.mention} earned "
        f"**{earned}** coins!\n"
        f"💰 Balance: **{user['balance']}**."
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
            "Choose `heads` or `tails`.\n"
            "Usage: `!coinflip <amount> <heads/tails>`"
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
            "❌ Invalid bet amount."
        )

        return

    result = random.choice(
        [
            "heads",
            "tails"
        ]
    )

    if result == choice:

        user["balance"] += amount

        outcome = (
            f"🎉 It landed on **{result}**!\n"
            f"You won **{amount}** coins."
        )

    else:

        user["balance"] -= amount

        outcome = (
            f"💀 It landed on **{result}**!\n"
            f"You lost **{amount}** coins."
        )

    save_economy()

    await ctx.send(
        f"{outcome}\n"
        f"💰 Balance: **{user['balance']}**."
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
            "❌ Invalid bet amount.\n"
            "Usage: `!slots <amount>`"
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

    display = " | ".join(spin)

    # Jackpot
    if (
        spin[0]
        == spin[1]
        == spin[2]
    ):

        winnings = amount * 5

        user["balance"] += winnings

        result = (
            f"🎰 {display}\n"
            f"🎉 **JACKPOT!** "
            f"You won **{winnings}** coins."
        )

    # Two matching
    elif (
        spin[0] == spin[1]
        or spin[1] == spin[2]
    ):

        winnings = amount * 2

        user["balance"] += winnings

        result = (
            f"🎰 {display}\n"
            f"✨ Nice! "
            f"You won **{winnings}** coins."
        )

    # Lose
    else:

        user["balance"] -= amount

        result = (
            f"🎰 {display}\n"
            f"💀 No match. "
            f"You lost **{amount}** coins."
        )

    save_economy()

    await ctx.send(
        f"{result}\n"
        f"💰 Balance: **{user['balance']}**."
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
            "No economy data yet."
        )

        return

    lines = []

    for i, (uid, data) in enumerate(
        top,
        start=1
    ):

        member = (
            ctx.guild.get_member(
                int(uid)
            )
            if ctx.guild
            else None
        )

        name = (
            member.display_name
            if member
            else f"User {uid}"
        )

        lines.append(
            f"**{i}.** {name} — "
            f"💰 {data['balance']} coins"
        )

    await ctx.send(
        "🏆 **Leaderboard**\n"
        + "\n".join(lines)
    )


# ============================================================
# AI CHAT / CLAUDE
# ============================================================

CLAUDE_API_URL = (
    "https://api.anthropic.com/v1/messages"
)

CLAUDE_MODEL = (
    "claude-haiku-4-5-20251001"
)

# Keeps the last few messages per channel.
chat_history = {}

MAX_HISTORY = 6


@bot.command(name="chat")
async def chat(
    ctx: commands.Context,
    *,
    message: str
):

    if not ANTHROPIC_API_KEY:

        await ctx.send(
            "🤖 AI chat isn't set up yet — "
            "missing `ANTHROPIC_API_KEY`."
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
                            "application/json",
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
                                "short and casual, "
                                "fitting for a chat message."
                            ),

                        "messages":
                            history,
                    },

                ) as resp:

                    data = await resp.json()

                    if resp.status != 200:

                        logger.error(
                            f"Claude API error: {data}"
                        )

                        await ctx.send(
                            "❌ Sorry, I couldn't "
                            "get a response right now."
                        )

                        return

                    reply = (
                        data["content"][0]["text"]
                    )

        except Exception:

            logger.exception(
                "Claude API call failed"
            )

            await ctx.send(
                "❌ Something went wrong "
                "reaching the AI."
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

    # Discord messages have a 2000-character limit.
    for i in range(
        0,
        len(reply),
        2000
    ):

        await ctx.send(
            reply[i:i + 2000]
        )


# ============================================================
# RENDER KEEP-ALIVE / HEALTH SERVER
# ============================================================

async def health(
    request
):

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
        f"Health check server listening "
        f"on port {port}"
    )


# ============================================================
# MAIN
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
