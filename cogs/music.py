"""
cogs/music.py
=============
Voice playback with a real per-guild queue (skip/pause/resume/loop/
shuffle/volume), plus !download for people who just want the mp3 file.

Tracks are stored in the queue as raw search queries and only resolved
(hit yt-dlp) right before they play — YouTube stream URLs expire after
a while, so resolving lazily avoids a long queue going stale.
"""

import asyncio
import logging
import os
import random
import shutil
from collections import deque

import discord
import yt_dlp
from discord.ext import commands

from constants import COLOR_MUSIC, footer

logger = logging.getLogger("music_bot")

YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE") or "cookies.txt"

# yt-dlp rewrites the cookie file after every request (YouTube rotates
# session cookies), so it needs a writable path. Render (and similar
# hosts) mount "Secret Files" read-only at /etc/secrets/..., which
# breaks that write with "[Errno 30] Read-only file system". Use a
# local writable path instead — if the env var points to a read-only
# location, we'll fall back to "cookies.txt" in the working directory.
if YTDLP_COOKIES_FILE and YTDLP_COOKIES_FILE.startswith("/etc/secrets/"):
    logger.info(
        f"YTDLP_COOKIES_FILE points to read-only path ({YTDLP_COOKIES_FILE}). "
        f"Using local writable path 'cookies.txt' instead."
    )
    YTDLP_COOKIES_FILE = "cookies.txt"
elif YTDLP_COOKIES_FILE and os.path.exists(YTDLP_COOKIES_FILE):
    if not os.access(YTDLP_COOKIES_FILE, os.W_OK):
        try:
            writable_copy = os.path.join(
                os.getenv("TMPDIR", "."), "yt_cookies.txt"
            )
            shutil.copyfile(YTDLP_COOKIES_FILE, writable_copy)
            logger.info(
                f"YTDLP_COOKIES_FILE ({YTDLP_COOKIES_FILE}) is read-only — "
                f"using a writable copy at {writable_copy} instead."
            )
            YTDLP_COOKIES_FILE = writable_copy
        except OSError:
            logger.exception(
                "Could not copy YTDLP_COOKIES_FILE to a writable location — "
                "falling back to 'cookies.txt'."
            )
            YTDLP_COOKIES_FILE = "cookies.txt"

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "extractor_args": {"youtube": {"player_client": ["android"]}},

}

if YTDLP_COOKIES_FILE:
    YTDL_OPTIONS["cookiefile"] = YTDLP_COOKIES_FILE

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    ),
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class SongDownloadError(Exception):
    pass


async def resolve_query(loop, query):
    """Runs yt-dlp for `query`, returns the info dict (blocking call offloaded)."""

    q = query if query.startswith("http") else f"ytsearch1:{query}"

    def extract():
        return ytdl.extract_info(q, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
    except Exception as e:
        logger.exception("yt-dlp extraction failed")

        if "Sign in to confirm" in str(e):
            raise SongDownloadError(
                "YouTube is blocking this server as a bot — needs "
                "YTDLP_COOKIES_FILE configured."
            ) from e

        raise SongDownloadError(str(e)) from e

    if "entries" in data:
        data = data["entries"][0]

    return data


async def fetch_song_mp3(query):
    """
    Downloads `query` to an mp3 on disk for !download / the AI chat
    tool. Returns (title, mp3_path); caller must delete the file.
    """

    q = query if query.startswith("http") else f"ytsearch1:{query}"

    os.makedirs("downloads", exist_ok=True)

    dl_opts = {
        "format": "bestaudio/best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    
    }

    if YTDLP_COOKIES_FILE:
        dl_opts["cookiefile"] = YTDLP_COOKIES_FILE

    loop = asyncio.get_event_loop()

    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(q, download=True)
            )

            if "entries" in info:
                info = info["entries"][0]

            base, _ = os.path.splitext(ydl.prepare_filename(info))
            mp3_path = base + ".mp3"

    except Exception as e:
        logger.exception("Download failed")

        if "Sign in to confirm" in str(e):
            raise SongDownloadError(
                "YouTube is blocking this server as a bot — needs "
                "YTDLP_COOKIES_FILE configured."
            ) from e

        raise SongDownloadError(str(e)) from e

    if not os.path.exists(mp3_path):
        raise SongDownloadError("MP3 conversion failed.")

    return info.get("title", "audio"), mp3_path


async def send_song_as_file(channel, query, guild=None):
    """Downloads `query` and posts it as an mp3 attachment. Returns (ok, message)."""

    try:
        title, mp3_path = await fetch_song_mp3(query)
    except SongDownloadError as e:
        return False, f"Couldn't download '{query}': {e}"

    try:
        limit = guild.filesize_limit if guild else 25 * 1024 * 1024
        size = os.path.getsize(mp3_path)

        if size > limit:
            return False, (
                f"'{title}' is too large to upload here "
                f"(over {limit // (1024 * 1024)}MB)."
            )

        await channel.send(
            content=f"🎵 **{title}**",
            file=discord.File(mp3_path, filename=f"{title[:80]}.mp3")
        )
        return True, f"Sent '{title}' as an mp3 in the channel."

    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


class GuildMusicState:
    def __init__(self):
        self.queue = deque()            # list of {"query", "requester_name"}
        self.current = None             # currently playing track dict
        self.volume = 0.5
        self.loop_mode = "off"          # off / single / queue
        self.text_channel = None


class Music(commands.Cog):
    """Voice playback: queue, skip, pause/resume, loop, volume, shuffle."""

    def __init__(self, bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def state_for(self, guild_id) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    # ------------------------------------------------------------
    @commands.command(name="join")
    async def join(self, ctx):
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("🎤 Join a voice channel first.")
            return

        channel = ctx.author.voice.channel

        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()

        await ctx.send(f"🎵 Joined **{channel.name}**.")

    @commands.command(name="leave", aliases=["disconnect", "dc"])
    async def leave(self, ctx):
        if ctx.voice_client is None:
            await ctx.send("I'm not in a voice channel.")
            return

        state = self.state_for(ctx.guild.id)
        state.queue.clear()
        state.current = None

        await ctx.voice_client.disconnect()
        await ctx.send("👋 Disconnected.")

    # ------------------------------------------------------------
    async def enqueue(self, ctx, query):
        """Adds `query` to the guild queue and starts playback if idle."""

        if ctx.voice_client is None:
            if ctx.author.voice is None or ctx.author.voice.channel is None:
                await ctx.send("🎤 Join a voice channel first.")
                return

            await ctx.author.voice.channel.connect()

        state = self.state_for(ctx.guild.id)
        state.text_channel = ctx.channel

        state.queue.append({
            "query": query,
            "requester_name": ctx.author.display_name
        })

        vc = ctx.voice_client

        if vc.is_playing() or vc.is_paused():
            await ctx.send(
                f"➕ Queued **{query}** (position {len(state.queue)})."
            )
        else:
            await self._play_next(ctx.guild)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query):
        await self.enqueue(ctx, query)

    async def _play_next(self, guild):
        state = self.states.get(guild.id)

        if state is None or guild.voice_client is None:
            return

        next_query = None
        requester_name = None

        if state.loop_mode == "single" and state.current:
            next_query = state.current["query"]
            requester_name = state.current["requester_name"]
        elif state.queue:
            item = state.queue.popleft()
            next_query = item["query"]
            requester_name = item["requester_name"]

            if state.loop_mode == "queue" and state.current:
                state.queue.append({
                    "query": state.current["query"],
                    "requester_name": state.current["requester_name"]
                })

        if next_query is None:
            state.current = None

            if state.text_channel:
                await state.text_channel.send("📭 Queue finished.")
            return

        loop = asyncio.get_event_loop()

        try:
            data = await resolve_query(loop, next_query)
        except SongDownloadError as e:
            if state.text_channel:
                await state.text_channel.send(f"❌ Skipping '{next_query}': {e}")
            await self._play_next(guild)
            return

        stream_url = data["url"]
        title = data.get("title", next_query)
        webpage_url = data.get("webpage_url")

        state.current = {
            "query": next_query,
            "title": title,
            "webpage_url": webpage_url,
            "requester_name": requester_name
        }

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_playing(error):
            if error:
                logger.error(f"Player error: {error}")

            fut = asyncio.run_coroutine_threadsafe(
                self._play_next(guild), self.bot.loop
            )
            try:
                fut.result()
            except Exception:
                logger.exception("Error advancing queue")

        guild.voice_client.play(source, after=after_playing)

        if state.text_channel:
            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**{title}**\n{webpage_url or ''}",
                color=COLOR_MUSIC
            )
            embed.set_footer(text=f"Requested by {requester_name}")
            await state.text_channel.send(embed=embed)

    # ------------------------------------------------------------
    @commands.command(name="pause")
    async def pause(self, ctx):
        vc = ctx.voice_client

        if vc is None or not vc.is_playing():
            await ctx.send("Nothing is playing.")
            return

        vc.pause()
        await ctx.send("⏸️ Paused.")

    @commands.command(name="resume")
    async def resume(self, ctx):
        vc = ctx.voice_client

        if vc is None or not vc.is_paused():
            await ctx.send("Nothing is paused.")
            return

        vc.resume()
        await ctx.send("▶️ Resumed.")

    @commands.command(name="skip")
    async def skip(self, ctx):
        vc = ctx.voice_client

        if vc is None or not (vc.is_playing() or vc.is_paused()):
            await ctx.send("Nothing to skip.")
            return

        vc.stop()  # triggers after_playing -> _play_next
        await ctx.send("⏭️ Skipped.")

    @commands.command(name="stop")
    async def stop(self, ctx):
        vc = ctx.voice_client
        state = self.state_for(ctx.guild.id)

        state.queue.clear()
        state.current = None

        if vc:
            vc.stop()

        await ctx.send("⏹️ Stopped and cleared the queue.")

    # ------------------------------------------------------------
    @commands.command(name="queue", aliases=["q"])
    async def queue_cmd(self, ctx):
        state = self.state_for(ctx.guild.id)

        lines = []

        if state.current:
            lines.append(f"▶️ **{state.current['title']}** *(now playing)*")

        for i, item in enumerate(state.queue, start=1):
            lines.append(f"{i}. {item['query']} — added by {item['requester_name']}")

        if not lines:
            await ctx.send("📭 The queue is empty.")
            return

        embed = discord.Embed(
            title="🎵 Queue",
            description="\n".join(lines[:15]),
            color=COLOR_MUSIC
        )
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="nowplaying", aliases=["np"])
    async def nowplaying(self, ctx):
        state = self.state_for(ctx.guild.id)

        if not state.current:
            await ctx.send("Nothing is playing.")
            return

        embed = discord.Embed(
            title="🎵 Now Playing",
            description=(
                f"**{state.current['title']}**\n"
                f"{state.current.get('webpage_url') or ''}"
            ),
            color=COLOR_MUSIC
        )
        embed.set_footer(text=f"Requested by {state.current['requester_name']}")
        await ctx.send(embed=embed)

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, percent: int):
        if percent < 0 or percent > 200:
            await ctx.send("🔊 Choose a volume between 0 and 200.")
            return

        state = self.state_for(ctx.guild.id)
        state.volume = percent / 100

        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = state.volume

        await ctx.send(f"🔊 Volume set to **{percent}%**.")

    @commands.command(name="loop")
    async def loop_cmd(self, ctx, mode: str = None):
        state = self.state_for(ctx.guild.id)

        if mode is None:
            await ctx.send(f"🔁 Current loop mode: **{state.loop_mode}**.")
            return

        mode = mode.lower()

        if mode not in ("off", "single", "queue"):
            await ctx.send("🔁 Choose `off`, `single`, or `queue`.")
            return

        state.loop_mode = mode
        await ctx.send(f"🔁 Loop mode set to **{mode}**.")

    @commands.command(name="shuffle")
    async def shuffle(self, ctx):
        state = self.state_for(ctx.guild.id)

        if len(state.queue) < 2:
            await ctx.send("Not enough songs in the queue to shuffle.")
            return

        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)

        await ctx.send("🔀 Queue shuffled.")

    # ------------------------------------------------------------
    @commands.command(name="download", aliases=["dl", "send"])
    async def download_song(self, ctx, *, query):
        status = await ctx.send(f"⏳ Fetching **{query}**...")

        ok, result_message = await send_song_as_file(ctx.channel, query, ctx.guild)

        if ok:
            await status.delete()
        else:
            await status.edit(content=f"❌ {result_message}")


async def setup(bot):
    await bot.add_cog(Music(bot))
