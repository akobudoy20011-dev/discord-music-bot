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

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

EMBED_COLOR = discord.Color.from_rgb(88, 101, 242)  # Discord blurple

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
    else:
        user["balance"] -= amount
    save_economy()
    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=(
            f"Landed on **{result}**!\n"
            f"{'🎉 You won' if won else '💀 You lost'} **{amount:,} coins**\n"
            f"Balance: **{user['balance']:,}**"
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
    elif spin[0] == spin[1] or spin[1] == spin[2]:
        winnings = amount * 2
        user["balance"] += winnings
        result_text = f"✨ **Nice!** You won **{winnings:,} coins**"
        color = discord.Color.green()
    else:
        user["balance"] -= amount
        result_text = f"💀 No match. You lost **{amount:,} coins**"
        color = discord.Color.red()
    save_economy()
    embed = discord.Embed(
        title="🎰 Slots",
        description=f"**{display}**\n\n{result_text}\nBalance: **{user['balance']:,}**",
        color=color,
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


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


@bot.command(name="chat")
async def chat(ctx: commands.Context, *, message: str):
    if not ANTHROPIC_API_KEY:
        await ctx.send(embed=error_embed("AI chat isn't set up yet — missing `ANTHROPIC_API_KEY`."))
        return

    channel_id = str(ctx.channel.id)
    history = chat_history.setdefault(channel_id, [])
    history.append({"role": "user", "content": message})
    history[:] = history[-MAX_HISTORY:]

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
                        "system": "You are a friendly, concise Discord bot assistant. Keep replies short and casual, fitting for a chat message.",
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
        name="💰 Economy",
        value="`!balance` `!daily` `!work`\n`!leaderboard`",
        inline=False,
    )
    embed.add_field(
        name="🎮 Games",
        value="`!coinflip <amount> heads/tails`\n`!slots <amount>`",
        inline=False,
    )
    embed.add_field(
        name="🤖 AI Chat",
        value="`!chat <message>`",
        inline=False,
    )
    embed.set_footer(text="Music Delivery Bot")
    await ctx.send(embed=embed)


# Lets people just type "!<song name>" instead of "!play <song name>"
KNOWN_COMMANDS = {"join", "play", "leave", "download", "dl", "send", "balance",
                   "bal", "daily", "work", "coinflip", "cf", "slots",
                   "leaderboard", "lb", "chat", "help", "commands"}


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
