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
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== MUSIC ====================

YTDL_OPTIONS = {
    "format": "bestaudio/best",
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


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.command(name="join")
async def join(ctx: commands.Context):
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("You need to be in a voice channel first.")
        return
    channel = ctx.author.voice.channel
    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
    await ctx.send(f"Joined **{channel.name}**.")


async def play_song(ctx: commands.Context, query: str):
    """Shared logic: joins voice if needed, searches/streams, and posts the link."""
    if ctx.voice_client is None:
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("You need to be in a voice channel, or use !join first.")
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
            await ctx.send(f"Couldn't find or play that: {e}")
            return

        def after_playing(error):
            if error:
                logger.error(f"Player error: {error}")

        voice_client.play(player, after=after_playing)

    link = player.webpage_url or ""
    await ctx.send(f"🎵 Now playing: **{player.title}**\n{link}")


@bot.command(name="play")
async def play(ctx: commands.Context, *, query: str):
    await play_song(ctx, query)


@bot.command(name="leave")
async def leave(ctx: commands.Context):
    if ctx.voice_client is None:
        await ctx.send("I'm not connected to a voice channel.")
        return
    await ctx.voice_client.disconnect()
    await ctx.send("Disconnected.")


# Lets people just type "!<song name>" instead of "!play <song name>"
KNOWN_COMMANDS = {"join", "play", "leave", "balance", "bal", "daily", "work",
                   "coinflip", "cf", "slots", "leaderboard", "lb", "chat", "help"}


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        query = ctx.message.content[len(ctx.prefix):].strip()
        if query and query.split()[0].lower() not in KNOWN_COMMANDS:
            await play_song(ctx, query)
        return
    logger.error(f"Command error: {error}")


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


@bot.command(name="balance", aliases=["bal"])
async def balance(ctx):
    user = get_user(ctx.author.id)
    await ctx.send(f"💰 {ctx.author.mention}, you have **{user['balance']}** coins.")


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
            await ctx.send(f"⏳ Already claimed. Try again in {hrs}h {mins}m.")
            return
    user["balance"] += DAILY_AMOUNT
    user["last_daily"] = now.isoformat()
    save_economy()
    await ctx.send(f"✅ {ctx.author.mention} claimed **{DAILY_AMOUNT}** coins! Balance: {user['balance']}.")


@bot.command(name="work")
async def work(ctx):
    user = get_user(ctx.author.id)
    now = datetime.now(timezone.utc)
    if user["last_work"]:
        last = datetime.fromisoformat(user["last_work"])
        if now - last < WORK_COOLDOWN:
            remaining = WORK_COOLDOWN - (now - last)
            mins = int(remaining.total_seconds() // 60)
            await ctx.send(f"⏳ You're tired. Rest {mins}m before working again.")
            return
    earned = random.randint(WORK_MIN, WORK_MAX)
    user["balance"] += earned
    user["last_work"] = now.isoformat()
    save_economy()
    await ctx.send(f"🛠️ {ctx.author.mention} earned **{earned}** coins! Balance: {user['balance']}.")


@bot.command(name="coinflip", aliases=["cf"])
async def coinflip(ctx, amount: int, choice: str):
    choice = choice.lower()
    if choice not in ("heads", "tails"):
        await ctx.send("Choose `heads` or `tails`. Usage: `!coinflip <amount> <heads/tails>`")
        return
    user = get_user(ctx.author.id)
    if amount <= 0 or amount > user["balance"]:
        await ctx.send("Invalid bet amount.")
        return
    result = random.choice(["heads", "tails"])
    if result == choice:
        user["balance"] += amount
        outcome = f"🎉 It landed on **{result}**! You won **{amount}** coins."
    else:
        user["balance"] -= amount
        outcome = f"💀 It landed on **{result}**! You lost **{amount}** coins."
    save_economy()
    await ctx.send(f"{outcome} Balance: {user['balance']}.")


@bot.command(name="slots")
async def slots(ctx, amount: int):
    user = get_user(ctx.author.id)
    if amount <= 0 or amount > user["balance"]:
        await ctx.send("Invalid bet amount. Usage: `!slots <amount>`")
        return
    symbols = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
    spin = [random.choice(symbols) for _ in range(3)]
    display = " | ".join(spin)
    if spin[0] == spin[1] == spin[2]:
        winnings = amount * 5
        user["balance"] += winnings
        result = f"🎰 {display} — JACKPOT! You won **{winnings}** coins."
    elif spin[0] == spin[1] or spin[1] == spin[2]:
        winnings = amount * 2
        user["balance"] += winnings
        result = f"🎰 {display} — Nice! You won **{winnings}** coins."
    else:
        user["balance"] -= amount
        result = f"🎰 {display} — No match. You lost **{amount}** coins."
    save_economy()
    await ctx.send(f"{result} Balance: {user['balance']}.")


@bot.command(name="leaderboard", aliases=["lb"])
async def leaderboard(ctx):
    top = sorted(economy.items(), key=lambda x: x[1]["balance"], reverse=True)[:10]
    if not top:
        await ctx.send("No data yet.")
        return
    lines = []
    for i, (uid, data) in enumerate(top, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        lines.append(f"{i}. {name} — {data['balance']} coins")
    await ctx.send("🏆 **Leaderboard**\n" + "\n".join(lines))


# ==================== AI CHAT ====================

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap; swap to "claude-sonnet-5" for smarter replies

# Keeps last few messages per channel so the bot has short-term context
chat_history = {}
MAX_HISTORY = 6


@bot.command(name="chat")
async def chat(ctx: commands.Context, *, message: str):
    if not ANTHROPIC_API_KEY:
        await ctx.send("AI chat isn't set up yet — missing ANTHROPIC_API_KEY.")
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
                        await ctx.send("Sorry, I couldn't get a response right now.")
                        return
                    reply = data["content"][0]["text"]
        except Exception:
            logger.exception("Claude API call failed")
            await ctx.send("Something went wrong reaching the AI.")
            return

    history.append({"role": "assistant", "content": reply})
    history[:] = history[-MAX_HISTORY:]

    # Discord messages cap at 2000 chars
    for i in range(0, len(reply), 2000):
        await ctx.send(reply[i:i + 2000])


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
