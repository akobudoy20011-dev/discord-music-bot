"""
main.py
=======
Entrypoint: sets up the bot, connects the database, loads every cog,
and starts the Render health-check server alongside the Discord client.
"""

import asyncio
import logging
import os
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database
from web.server import start_web_server

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

if not os.getenv("ANTHROPIC_API_KEY"):
    logger.warning(
        "ANTHROPIC_API_KEY is not set — !chat will reply "
        "'AI isn't configured' until it is."
    )

if not os.getenv("YTDLP_COOKIES_FILE"):
    logger.warning(
        "YTDLP_COOKIES_FILE is not set — using default 'cookies.txt'. "
        "YouTube may still block requests as a bot without valid cookies. "
        "For best results, export your browser cookies to cookies.txt and "
        "set YTDLP_COOKIES_FILE=cookies.txt in your environment."
    )

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

COGS = [
    "cogs.leveling",
    "cogs.economy",
    "cogs.games",
    "cogs.music",
    "cogs.fun",
    "cogs.admin",
    "cogs.ai",
    "cogs.help",
]


@bot.event
async def setup_hook():
    bot.db = Database()
    await bot.db.connect()

    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Loaded {cog}")
        except Exception as e:
            logger.error(f"❌ Failed to load {cog}: {e}")
            logger.error(traceback.format_exc())

    asyncio.create_task(start_web_server())


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} server(s)")

    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="!help"
            )
        )
    except Exception:
        pass


@bot.check
async def guild_only_globally(ctx):
    """
    Almost everything here is scoped per-server (economy, levels,
    music). Block DM usage globally instead of crashing on ctx.guild.id
    inside individual commands.
    """
    if ctx.command and ctx.command.qualified_name in ("help", "commands"):
        return True

    if ctx.guild is None:
        raise commands.NoPrivateMessage(
            "This command only works inside a server."
        )

    return True


@bot.event
async def on_command_error(ctx, error):
    error = getattr(error, "original", error)

    # If the command (or its cog) already has its own error handler, let that handle it.
    if ctx.command and (
        ctx.command.has_error_handler() or
        (ctx.cog and ctx.cog.has_error_handler())
    ):
        return

    if isinstance(error, commands.CommandNotFound):
        # Ignored to prevent treating game commands or unknown input as music searches
        return

    if isinstance(error, commands.MissingRequiredArgument):
        param = error.param.name
        await ctx.send(
            f"❌ Missing `{param}`. Use `!help` to see how to use "
            f"`!{ctx.command}`."
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(
            f"❌ That doesn't look right. Use `!help` to see how to use "
            f"`!{ctx.command}`."
        )
        return

    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ I couldn't find that member.")
        return

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Slow down — try again in {error.retry_after:.1f}s.")
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to do that.")
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ That command only works in a server.")
        return

    logger.error(f"Unhandled command error in !{ctx.command}: {error}")


async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
