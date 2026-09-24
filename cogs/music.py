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

YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE") or ""

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
    "retries": 3,
    "extractor_retries": 3,
    "fragment_retries": 3,
    "socket_timeout": 20,

}

if YTDLP_COOKIES_FILE and os.path.isfile(YTDLP_COOKIES_FILE):
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


def _youtube_error_message(error, action="play"):
    message = str(error)
    lowered = message.lower()

    if "sign in to confirm" in lowered or "confirm you're not a bot" in lowered:
        return (
            f"YouTube blocked this {action} request as automated traffic. "
            "Use a fresh yt-dlp build and, if the host is challenged, "
            "configure YTDLP_COOKIES_FILE or a supported PO-token provider."
        )

    if "po token" in lowered or "poh" in lowered:
        return (
            f"YouTube requires a PO token for this {action} request. "
            "The bot is no longer forcing the legacy Android client; "
            "configure a supported PO-token provider if YouTube still requires one."
        )

    if "403" in lowered or "forbidden" in lowered:
        return (
            f"YouTube returned HTTP 403 while trying to {action} this track. "
            "Persistent 403s require cookies/PO-token support."
        )

    if "age-restricted" in lowered or "sign in" in lowered:
        return f"This YouTube track requires authentication before it can be used to {action}."

    return f"yt-dlp could not {action} this track: {message}"


def _build_ytdl_options(client=None):
    options = dict(YTDL_OPTIONS)
    if client:
        options["extractor_args"] = {"youtube": {"player_client": [client]}}
    return options


def _select_playable_entry(entries):
    """Pick a useful search result instead of blindly trusting entry #1."""
    usable = []

    for entry in entries:
        if not entry:
            continue

        if not entry.get("url") or not entry.get("webpage_url"):
            continue

        availability = str(entry.get("availability") or "").lower()
        if availability in {"private", "premium only", "needs_auth"}:
            continue

        is_live = bool(entry.get("is_live"))
        duration_missing = entry.get("duration") is None
        title_length = len(entry.get("title") or "")
        usable.append((is_live, duration_missing, title_length, entry))

    if not usable:
        return None

    usable.sort(key=lambda item: (item[0], item[1], item[2]))
    return usable[0][3]


async def resolve_query(loop, query):
    """Resolve a YouTube URL/search query with maintained-client fallbacks."""
    is_url = query.startswith("http")
    q = query if is_url else f"ytsearch5:{query}"
    clients = [None, "web", "mweb"]
    last_error = None

    for client in clients:
        options = _build_ytdl_options(client)

        def extract(options=options):
            with yt_dlp.YoutubeDL(options) as extractor:
                return extractor.extract_info(q, download=False)

        try:
            data = await loop.run_in_executor(None, extract)

            if not data:
                raise SongDownloadError("YouTube returned no playable result.")

            if "entries" in data:
                entries = [entry for entry in data["entries"] if entry]
                if not entries:
                    raise SongDownloadError("YouTube returned no search results for that query.")
                data = _select_playable_entry(entries)
                if data is None:
                    raise SongDownloadError("YouTube returned results, but none had a usable audio stream.")

            if not data.get("url"):
                raise SongDownloadError("yt-dlp returned a result without a playable stream URL.")

            return data

        except SongDownloadError as error:
            last_error = error
            logger.warning("yt-dlp resolve rejected %s using client=%s: %s", query, client or "default", error)
        except Exception as error:
            last_error = error
            logger.warning("yt-dlp resolve failed for %s using client=%s: %s", query, client or "default", error)

    raise SongDownloadError(_youtube_error_message(last_error or "unknown error", "play"))


async def fetch_song_mp3(query):
    """
    Download a query to mp3 for !download. Retries maintained YouTube
    clients because extraction rules can differ between playback/download.
    """
    q = query if query.startswith("http") else f"ytsearch5:{query}"
    os.makedirs("downloads", exist_ok=True)
    loop = asyncio.get_event_loop()
    clients = [None, "web", "mweb"]
    last_error = None

    for client in clients:
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
            "retries": 3,
            "extractor_retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 20,
        }

        if client:
            dl_opts["extractor_args"] = {"youtube": {"player_client": [client]}}

        if YTDLP_COOKIES_FILE and os.path.isfile(YTDLP_COOKIES_FILE):
            dl_opts["cookiefile"] = YTDLP_COOKIES_FILE

        try:
            def download():
                with yt_dlp.YoutubeDL(dl_opts) as extractor:
                    return extractor.extract_info(q, download=True)

            info = await loop.run_in_executor(None, download)

            if not info:
                raise SongDownloadError("YouTube returned no downloadable result.")

            if "entries" in info:
                entries = [entry for entry in info["entries"] if entry]
                if not entries:
                    raise SongDownloadError("YouTube returned no downloadable search result.")
                info = entries[0]

            with yt_dlp.YoutubeDL(dl_opts) as extractor:
                base = os.path.splitext(extractor.prepare_filename(info))[0]

            mp3_path = base + ".mp3"

            if not os.path.exists(mp3_path):
                raise SongDownloadError("MP3 conversion failed.")

            return info.get("title", "audio"), mp3_path

        except SongDownloadError as error:
            last_error = error
            logger.warning("YouTube download failed using client=%s: %s", client or "default", error)
        except Exception as error:
            last_error = error
            logger.warning("YouTube download failed using client=%s: %s", client or "default", error)

    raise SongDownloadError(_youtube_error_message(last_error or "unknown error", "download"))


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

    async def _resolve_for_playback(self, guild, query):
        """Resolve a fresh stream URL immediately before playback."""
        loop = asyncio.get_event_loop()
        return await resolve_query(loop, query)

    async def _start_resolved_track(self, guild, state, query, requester_name, data):
        stream_url = data.get("url")
        if not stream_url:
            raise SongDownloadError("YouTube returned no stream URL.")

        title = data.get("title", query)
        webpage_url = data.get("webpage_url")

        state.current = {
            "query": query,
            "title": title,
            "webpage_url": webpage_url,
            "requester_name": requester_name,
            "stream_url": stream_url,
        }

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_playing(error):
            fut = asyncio.run_coroutine_threadsafe(
                self._handle_player_end(guild, query, requester_name, error),
                self.bot.loop
            )
            try:
                fut.result()
            except Exception:
                logger.exception("Error handling playback completion")

    async def _handle_player_end(self, guild, query, requester_name, error):
        state = self.states.get(guild.id)
        if state is None:
            return

        if error:
            logger.error("FFmpeg/player error for '%s': %s", query, error)
            try:
                fresh = await self._resolve_for_playback(guild, query)
                if guild.voice_client is not None:
                    await self._start_resolved_track(
                        guild, state, query, requester_name, fresh
                    )
                    if state.text_channel:
                        await state.text_channel.send(
                            "🔄 YouTube stream failed; refreshed and resumed."
                        )
                    return
            except Exception as refresh_error:
                logger.error(
                    "Automatic stream refresh failed for '%s': %s",
                    query,
                    refresh_error,
                )

        state.current = None
        await self._play_next(guild)

        guild.voice_client.play(source, after=after_playing)

        if state.text_channel:
            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**{title}**\\n{webpage_url or ''}",
                color=COLOR_MUSIC
            )
            embed.set_footer(text=f"Requested by {requester_name}")
            await state.text_channel.send(embed=embed)

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

        # Resolve a fresh URL. Stream URLs are intentionally never stored
        # in the queue because they expire.
        try:
            data = await self._resolve_for_playback(guild, next_query)
        except SongDownloadError as first_error:
            if state.text_channel:
                await state.text_channel.send(
                    f"❌ Couldn't start '{next_query}': {first_error}"
                )

            state.current = None

            while state.queue:
                failed = state.queue.popleft()
                try:
                    data = await self._resolve_for_playback(guild, failed["query"])
                    next_query = failed["query"]
                    requester_name = failed["requester_name"]
                    break
                except SongDownloadError as retry_error:
                    if state.text_channel:
                        await state.text_channel.send(
                            "❌ Skipping '{}' : {}".format(
                                failed["query"], retry_error
                            )
                        )
            else:
                if state.text_channel:
                    await state.text_channel.send("📭 Queue finished.")
                return

        try:
            await self._start_resolved_track(
                guild, state, next_query, requester_name, data
            )
        except Exception as playback_error:
            logger.error(
                "Playback start failed for '%s': %s",
                next_query,
                playback_error,
            )

            # One complete re-resolution is important here: a freshly
            # extracted YouTube URL can still be rejected by FFmpeg if
            # it expires or is invalidated between extraction and opening.
            try:
                fresh = await self._resolve_for_playback(guild, next_query)
                await self._start_resolved_track(
                    guild, state, next_query, requester_name, fresh
                )
                if state.text_channel:
                    await state.text_channel.send(
                        "🔄 Stream refreshed and playback restarted."
                    )
                return
            except Exception as refresh_error:
                logger.error(
                    "Stream refresh failed for '%s': %s",
                    next_query,
                    refresh_error,
                )
                state.current = None

                if state.text_channel:
                    await state.text_channel.send(
                        f"❌ Couldn't start **{next_query}** after a stream refresh."
                    )

                await self._play_next(guild)

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
