import os
import asyncio
import logging

import discord
from discord.ext import commands
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# yt-dlp options
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",  # bind to ipv4
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

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )

        if "entries" in data:
            # Take first item from a playlist/search result
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


@bot.command(name="play")
async def play(ctx: commands.Context, *, url: str):
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
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
        except Exception as e:
            logger.exception("Failed to extract/stream audio")
            await ctx.send(f"Error retrieving audio: {e}")
            return

        def after_playing(error):
            if error:
                logger.error(f"Player error: {error}")

        voice_client.play(player, after=after_playing)

    await ctx.send(f"Now playing: **{player.title}**")


@bot.command(name="leave")
async def leave(ctx: commands.Context):
    if ctx.voice_client is None:
        await ctx.send("I'm not connected to a voice channel.")
        return

    await ctx.voice_client.disconnect()
    await ctx.send("Disconnected.")


@play.before_invoke
async def ensure_voice(ctx: commands.Context):
    if ctx.voice_client is None:
        if ctx.author.voice is None:
            raise commands.CommandError("You are not connected to a voice channel.")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
