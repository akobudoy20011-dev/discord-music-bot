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
import time
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
        self.queue = deque()
        self.current = None
        self.last_track = None
        self.recent = deque(maxlen=12)
        self.history = deque(maxlen=25)
        self.volume = 0.5
        self.loop_mode = "off"
        self.autoplay = False
        self.twentyfour_seven = False
        self.auto_disconnect = True
        self.queue_limit = 50
        self.search_behavior = "youtube"
        self.dj_role_id = None
        self.voice_channel_id = None
        self.text_channel = None
        self.playback_generation = 0
        self.intentional_stop_generation = None
        self.settings_loaded = False
        self.auto_disconnect_task = None
        self.reconnect_task = None
        self.manual_disconnect = False
        self.playback_lock = asyncio.Lock()


class QueuePageView(discord.ui.View):
    """Ephemeral queue navigation; buttons never mutate playback state."""

    def __init__(self, cog, guild_id, page, total_pages):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page
        self.total_pages = total_pages
        self.previous_button.disabled = page <= 1
        self.next_button.disabled = page >= total_pages

    async def interaction_check(self, interaction):
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "This queue belongs to another server.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction, button):
        await self.cog.send_queue(
            interaction.guild,
            interaction.channel,
            interaction=interaction,
            page=self.page - 1,
        )

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction, button):
        await self.cog.send_queue(
            interaction.guild,
            interaction.channel,
            interaction=interaction,
            page=self.page + 1,
        )


class MusicControlView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction):
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("This control panel belongs to another server.", ephemeral=True)
            return False
        if not self.cog.can_control_member(interaction.guild, interaction.user):
            await interaction.response.send_message("You need the DJ role or Manage Server permission to use this control.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause_button(self, interaction, button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused.", ephemeral=True)
        elif vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip_button(self, interaction, button):
        await self.cog._skip_guild(interaction.guild, interaction.channel, announce=False)
        await interaction.response.send_message("⏭️ Skipped.", ephemeral=True)

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction, button):
        await self.cog._stop_guild(interaction.guild, disconnect=False)
        await interaction.response.send_message("⏹️ Stopped and cleared.", ephemeral=True)

    @discord.ui.button(label="Loop", emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop_button(self, interaction, button):
        state = await self.cog.ensure_settings(interaction.guild.id)
        modes = ["off", "single", "queue"]
        state.loop_mode = modes[(modes.index(state.loop_mode) + 1) % len(modes)]
        await self.cog.persist_settings(interaction.guild.id, state)
        await interaction.response.send_message(f"🔁 Loop: {state.loop_mode}.", ephemeral=True)

    @discord.ui.button(label="Shuffle", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle_button(self, interaction, button):
        state = await self.cog.ensure_settings(interaction.guild.id)
        if len(state.queue) < 2:
            await interaction.response.send_message("Not enough songs to shuffle.", ephemeral=True)
            return
        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)
        await interaction.response.send_message("🔀 Queue shuffled.", ephemeral=True)

    @discord.ui.button(label="Queue", emoji="📜", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction, button):
        await self.cog.send_queue(interaction.guild, interaction.channel, interaction=interaction)


class Music(commands.Cog):
    AUTODISCONNECT_SECONDS = 300
    MAX_RECOVERY_ATTEMPTS = 2

    def __init__(self, bot):
        self.bot = bot
        self.states = {}

    def state_for(self, guild_id):
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    async def ensure_settings(self, guild_id):
        state = self.state_for(guild_id)
        if state.settings_loaded:
            return state
        config = await self.bot.db.get_music_config(guild_id)
        state.volume = config["volume"]
        state.loop_mode = config["loop_mode"] if config["loop_mode"] in {"off", "single", "queue"} else "off"
        state.autoplay = config["autoplay"]
        state.twentyfour_seven = config["twentyfour_seven"]
        state.auto_disconnect = config["auto_disconnect"]
        state.queue_limit = config["queue_limit"]
        state.search_behavior = config["search_behavior"]
        state.dj_role_id = config["dj_role_id"]
        state.voice_channel_id = config["voice_channel_id"]
        state.settings_loaded = True
        return state

    async def persist_settings(self, guild_id, state):
        await self.bot.db.set_music_config(
            guild_id,
            volume=float(state.volume),
            loop_mode=state.loop_mode,
            autoplay=int(state.autoplay),
            twentyfour_seven=int(state.twentyfour_seven),
            auto_disconnect=int(state.auto_disconnect),
            queue_limit=int(state.queue_limit),
            search_behavior=state.search_behavior,
            dj_role_id=state.dj_role_id,
            voice_channel_id=state.voice_channel_id,
        )

    def can_control_member(self, guild, member):
        if member.guild_permissions.manage_guild or member.guild_permissions.manage_channels:
            return True
        state = self.state_for(guild.id)
        if state.dj_role_id:
            return any(str(role.id) == str(state.dj_role_id) for role in getattr(member, "roles", []))
        return False

    async def require_control(self, ctx):
        await self.ensure_settings(ctx.guild.id)
        if not self.can_control_member(ctx.guild, ctx.author):
            await ctx.send("🛡️ Music control requires the configured DJ role or Manage Server.")
            return None
        return self.state_for(ctx.guild.id)

    def _cancel_autodisconnect(self, state):
        task = state.auto_disconnect_task
        if task and not task.done():
            task.cancel()
        state.auto_disconnect_task = None

    def _schedule_autodisconnect(self, guild):
        state = self.state_for(guild.id)
        self._cancel_autodisconnect(state)
        if state.twentyfour_seven or not state.auto_disconnect:
            return
        async def worker():
            try:
                await asyncio.sleep(self.AUTODISCONNECT_SECONDS)
                vc = guild.voice_client
                if vc and not vc.is_playing() and not vc.is_paused() and not state.queue:
                    state.manual_disconnect = True
                    await vc.disconnect()
                    state.current = None
                    if state.text_channel:
                        await state.text_channel.send("👋 Left voice after 5 minutes of inactivity.")
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Auto-disconnect failed for guild %s", guild.id)
        state.auto_disconnect_task = asyncio.create_task(worker())

    async def _connect_to_channel(self, guild, channel):
        vc = guild.voice_client
        if vc:
            try:
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
            except Exception:
                logger.exception("Voice move failed for guild %s", guild.id)
            return guild.voice_client
        return await channel.connect(reconnect=True, self_deaf=True)

    async def _remember_voice(self, guild, channel):
        state = await self.ensure_settings(guild.id)
        state.voice_channel_id = str(channel.id)
        state.manual_disconnect = False
        await self.persist_settings(guild.id, state)

    async def _restore_24_7(self, guild):
        state = await self.ensure_settings(guild.id)
        if not state.twentyfour_seven or state.manual_disconnect or not state.voice_channel_id:
            return
        channel = guild.get_channel(int(state.voice_channel_id))
        if channel is None or not hasattr(channel, "connect"):
            return
        if guild.voice_client:
            return
        try:
            await self._connect_to_channel(guild, channel)
        except Exception as error:
            logger.warning("24/7 reconnect failed for %s: %s", guild.id, error)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            asyncio.create_task(self._restore_24_7(guild))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not self.bot.user or member.id != self.bot.user.id or before.channel is after.channel:
            return
        guild = member.guild
        state = await self.ensure_settings(guild.id)
        if after.channel is None and before.channel is not None and state.twentyfour_seven and not state.manual_disconnect:
            if state.reconnect_task and not state.reconnect_task.done():
                return
            async def reconnect():
                try:
                    await asyncio.sleep(2)
                    channel = guild.get_channel(int(state.voice_channel_id)) if state.voice_channel_id else None
                    if channel and guild.voice_client is None and state.twentyfour_seven and not state.manual_disconnect:
                        await self._connect_to_channel(guild, channel)
                        if state.current:
                            current = dict(state.current)
                            state.queue.appendleft({"query": current["query"], "requester_name": current["requester_name"]})
                            state.current = None
                            await self._play_next(guild)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("24/7 voice reconnect failed for guild %s", guild.id)
                finally:
                    state.reconnect_task = None
            state.reconnect_task = asyncio.create_task(reconnect())

    @commands.command(name="join")
    async def join(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("🎤 Join a voice channel first.")
            return
        channel = ctx.author.voice.channel
        await self._connect_to_channel(ctx.guild, channel)
        await self._remember_voice(ctx.guild, channel)
        await ctx.send(f"🎵 Joined **{channel.name}**.")

    @commands.command(name="leave", aliases=["disconnect", "dc"])
    async def leave(self, ctx):
        if not await self.require_control(ctx):
            return
        if ctx.voice_client is None:
            await ctx.send("I'm not in a voice channel.")
            return
        state = await self.ensure_settings(ctx.guild.id)
        state.manual_disconnect = True
        self._cancel_autodisconnect(state)
        state.queue.clear()
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            generation = state.current.get("generation") if state.current else None
            state.intentional_stop_generation = generation
            ctx.voice_client.stop()
        state.current = None
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Disconnected.")

    async def enqueue(self, ctx, query):
        if ctx.voice_client is None:
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("🎤 Join a voice channel first.")
                return
            await self._connect_to_channel(ctx.guild, ctx.author.voice.channel)
            await self._remember_voice(ctx.guild, ctx.author.voice.channel)
        state = await self.ensure_settings(ctx.guild.id)
        state.text_channel = ctx.channel
        state.manual_disconnect = False
        self._cancel_autodisconnect(state)
        if len(state.queue) >= state.queue_limit:
            await ctx.send(f"🧱 Queue limit reached ({state.queue_limit}).")
            return
        state.queue.append({"query": query.strip(), "requester_name": ctx.author.display_name})
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            await ctx.send(f"➕ Queued **{query}** · position **{len(state.queue)}**.")
        else:
            await self._play_next(ctx.guild)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query):
        await self.enqueue(ctx, query)

    async def _resolve_for_playback(self, guild, query):
        return await resolve_query(asyncio.get_running_loop(), query)

    async def _autoplay_candidate(self, guild, seed):
        loop = asyncio.get_running_loop()
        q = seed if seed.startswith("http") else f"ytsearch5:{seed}"
        options = _build_ytdl_options(None)
        def extract():
            with yt_dlp.YoutubeDL(options) as extractor:
                return extractor.extract_info(q, download=False)
        data = await loop.run_in_executor(None, extract)
        entries = [e for e in (data or {}).get("entries", []) if e]
        state = self.state_for(guild.id)
        for entry in entries:
            if not entry.get("url") or not entry.get("webpage_url"):
                continue
            availability = str(entry.get("availability") or "").lower()
            if availability in {"private", "premium only", "needs_auth"}:
                continue
            key = entry.get("webpage_url") or entry.get("id")
            if key and key in state.recent:
                continue
            return entry
        return None

    async def _start_resolved_track(self, guild, state, query, requester_name, data):
        stream_url = data.get("url")
        if not stream_url:
            raise SongDownloadError("YouTube returned no stream URL.")
        title = data.get("title", query)
        webpage_url = data.get("webpage_url")
        state.playback_generation += 1
        generation = state.playback_generation
        state.intentional_stop_generation = None
        state.current = {
            "query": query,
            "title": title,
            "webpage_url": webpage_url,
            "requester_name": requester_name,
            "stream_url": stream_url,
            "generation": generation,
            "key": webpage_url or data.get("id") or query,
        }
        state.recent.append(state.current["key"])
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_playing(error):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_player_end(guild, query, requester_name, generation, error),
                    self.bot.loop,
                )
            except Exception:
                logger.exception("Could not schedule player-end callback for guild %s", guild.id)

        try:
            vc = guild.voice_client
            if vc is None:
                raise RuntimeError("Voice connection disappeared before playback started.")
            vc.play(source, after=after_playing)
        except Exception:
            if state.playback_generation == generation:
                state.current = None
            raise
        if state.text_channel:
            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**{title}**\n{webpage_url or ''}",
                color=COLOR_MUSIC,
            )
            embed.set_footer(text=f"Requested by {requester_name}")
            await state.text_channel.send(embed=embed, view=MusicControlView(self, guild.id))

    async def _handle_player_end(self, guild, query, requester_name, generation, error):
        state = self.states.get(guild.id)
        if state is None or generation != state.playback_generation:
            return
        if state.intentional_stop_generation == generation:
            state.intentional_stop_generation = None
            if state.current and state.current.get("generation") == generation:
                state.current = None
            if state.current is None and not state.queue:
                return
            await self._play_next(guild)
            return
        if error:
            logger.error("FFmpeg/player error for '%s': %s", query, error)
            for _ in range(self.MAX_RECOVERY_ATTEMPTS):
                try:
                    fresh = await self._resolve_for_playback(guild, query)
                    if guild.voice_client is not None:
                        await self._start_resolved_track(guild, state, query, requester_name, fresh)
                        if state.text_channel:
                            await state.text_channel.send("🔄 Stream failed; ECLIPSE refreshed the source.")
                        return
                except Exception as refresh_error:
                    logger.warning("Playback recovery failed for '%s': %s", query, refresh_error)
        if state.current and state.current.get("generation") == generation:
            finished = dict(state.current)
            state.history.append(finished)
            state.last_track = finished
            state.current = None
        await self._play_next(guild)

    async def _play_next(self, guild):
        state = self.states.get(guild.id)
        if state is None:
            return
        async with state.playback_lock:
            await self._play_next_unlocked(guild)

    async def _play_next_unlocked(self, guild):
        state = self.states.get(guild.id)
        if state is None:
            return
        await self.ensure_settings(guild.id)
        vc = guild.voice_client
        if vc is None:
            if state.twentyfour_seven and state.voice_channel_id and not state.manual_disconnect:
                await self._restore_24_7(guild)
            return
        next_query = None
        requester_name = None
        if state.loop_mode == "single" and state.last_track:
            next_query = state.last_track["query"]
            requester_name = state.last_track["requester_name"]
        elif state.queue:
            item = state.queue.popleft()
            next_query = item["query"]
            requester_name = item["requester_name"]
            if state.loop_mode == "queue" and state.last_track:
                state.queue.append({"query": state.last_track["query"], "requester_name": state.last_track["requester_name"]})
        if next_query is None and state.autoplay and state.last_track and state.loop_mode == "off":
            try:
                candidate = await self._autoplay_candidate(guild, state.last_track.get("title") or state.last_track.get("query", ""))
                if candidate:
                    next_query = candidate.get("webpage_url") or candidate.get("url")
                    requester_name = "ECLIPSE Autoplay"
                    data = candidate
                else:
                    data = None
            except Exception as error:
                logger.warning("Autoplay search failed for guild %s: %s", guild.id, error)
                data = None
        else:
            data = None
        if next_query is None:
            state.current = None
            if state.text_channel:
                await state.text_channel.send("📭 Queue finished.")
            self._schedule_autodisconnect(guild)
            return
        self._cancel_autodisconnect(state)
        try:
            data = data or await self._resolve_for_playback(guild, next_query)
        except Exception as first_error:
            if state.text_channel:
                await state.text_channel.send(f"❌ Couldn't start **{next_query}**: {first_error}")
            state.current = None
            while state.queue:
                failed = state.queue.popleft()
                try:
                    data = await self._resolve_for_playback(guild, failed["query"])
                    next_query = failed["query"]
                    requester_name = failed["requester_name"]
                    break
                except Exception as retry_error:
                    if state.text_channel:
                        await state.text_channel.send(f"❌ Skipping **{failed['query']}**: {retry_error}")
            else:
                self._schedule_autodisconnect(guild)
                return
        try:
            await self._start_resolved_track(guild, state, next_query, requester_name, data)
        except Exception as playback_error:
            logger.error("Playback start failed for '%s': %s", next_query, playback_error)
            try:
                fresh = await self._resolve_for_playback(guild, next_query)
                await self._start_resolved_track(guild, state, next_query, requester_name, fresh)
                if state.text_channel:
                    await state.text_channel.send("🔄 Stream refreshed and playback restarted.")
                return
            except Exception:
                state.current = None
                await self._play_next_unlocked(guild)

    async def _skip_guild(self, guild, channel=None, announce=False):
        state = await self.ensure_settings(guild.id)
        vc = guild.voice_client
        if vc is None or not (vc.is_playing() or vc.is_paused()):
            if channel and announce:
                await channel.send("Nothing to skip.")
            return False
        generation = state.current.get("generation") if state.current else None
        state.intentional_stop_generation = generation
        vc.stop()
        if channel and announce:
            await channel.send("⏭️ Skipped.")
        return True

    async def _stop_guild(self, guild, disconnect=False):
        state = await self.ensure_settings(guild.id)
        state.queue.clear()
        self._cancel_autodisconnect(state)
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            generation = state.current.get("generation") if state.current else None
            state.intentional_stop_generation = generation
            vc.stop()
        state.current = None
        if disconnect and vc:
            state.manual_disconnect = True
            await vc.disconnect()

    async def send_queue(self, guild, channel, interaction=None, page=1):
        state = await self.ensure_settings(guild.id)
        items = list(state.queue)
        page_size = 10
        total_pages = max(1, (len(items) + page_size - 1) // page_size)
        page = max(1, min(int(page), total_pages))

        lines = []
        if state.current:
            lines.append(
                f"▶️ **{state.current['title']}** · {state.current['requester_name']}"
            )

        if items:
            start_index = (page - 1) * page_size
            end_index = min(start_index + page_size, len(items))
            for absolute_index, item in enumerate(
                items[start_index:end_index],
                start_index + 1,
            ):
                lines.append(
                    f"{absolute_index:02} · {item['query']} · {item['requester_name']}"
                )

        content = "📭 The queue is empty." if not lines else "\n".join(lines)
        embed = discord.Embed(
            title="🎵 ECLIPSE QUEUE",
            description=content,
            color=COLOR_MUSIC,
        )
        embed.set_footer(
            text=(
                f"Page {page}/{total_pages} · "
                f"Loop: {state.loop_mode} · "
                f"Autoplay: {'on' if state.autoplay else 'off'} · "
                f"Limit: {state.queue_limit}"
            )
        )

        view = QueuePageView(self, guild.id, page, total_pages) if total_pages > 1 else None
        if interaction:
            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True,
            )
        else:
            await channel.send(
                embed=embed,
                view=view or MusicControlView(self, guild.id),
            )

    @commands.command(name="pause")
    async def pause(self, ctx):
        await self.ensure_settings(ctx.guild.id)
        vc = ctx.voice_client
        if vc is None or not vc.is_playing():
            await ctx.send("Nothing is playing.")
            return
        if not self.can_control_member(ctx.guild, ctx.author):
            await ctx.send("🛡️ You need the DJ role or Manage Server.")
            return
        vc.pause()
        await ctx.send("⏸️ Paused.")

    @commands.command(name="resume")
    async def resume(self, ctx):
        await self.ensure_settings(ctx.guild.id)
        vc = ctx.voice_client
        if vc is None or not vc.is_paused():
            await ctx.send("Nothing is paused.")
            return
        if not self.can_control_member(ctx.guild, ctx.author):
            await ctx.send("🛡️ You need the DJ role or Manage Server.")
            return
        vc.resume()
        await ctx.send("▶️ Resumed.")

    @commands.command(name="previous", aliases=["prev", "back"])
    async def previous(self, ctx):
        if not await self.require_control(ctx):
            return
        state = await self.ensure_settings(ctx.guild.id)
        if not state.history:
            await ctx.send("⏮️ There is no previous track in the playback history.")
            return
        previous_track = state.history.pop()
        current = dict(state.current) if state.current else None
        if current:
            state.queue.appendleft({
                "query": current["query"],
                "requester_name": current["requester_name"],
            })
        state.queue.appendleft({
            "query": previous_track["query"],
            "requester_name": previous_track["requester_name"],
        })
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            generation = state.current.get("generation") if state.current else None
            state.intentional_stop_generation = generation
            vc.stop()
        else:
            await self._play_next(ctx.guild)
        await ctx.send(f"⏮️ Returning to **{previous_track['title']}**.")

    @commands.command(name="replay", aliases=["again"])
    async def replay(self, ctx):
        if not await self.require_control(ctx):
            return
        state = await self.ensure_settings(ctx.guild.id)
        if not state.current:
            if state.last_track:
                state.queue.appendleft({
                    "query": state.last_track["query"],
                    "requester_name": state.last_track["requester_name"],
                })
                await self._play_next(ctx.guild)
                return
            await ctx.send("Nothing is available to replay.")
            return

        track = dict(state.current)
        state.queue.appendleft({
            "query": track["query"],
            "requester_name": track["requester_name"],
        })
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            generation = state.current.get("generation")
            state.intentional_stop_generation = generation
            vc.stop()
        else:
            state.current = None
            await self._play_next(ctx.guild)
        await ctx.send(f"🔂 Replaying **{track['title']}**.")

    @commands.command(name="skip")
    async def skip(self, ctx):
        if not await self.require_control(ctx):
            return
        await self._skip_guild(ctx.guild, ctx.channel, announce=True)

    @commands.command(name="stop")
    async def stop(self, ctx):
        if not await self.require_control(ctx):
            return
        await self._stop_guild(ctx.guild)
        await ctx.send("⏹️ Stopped and cleared the queue.")

    @commands.command(name="queue", aliases=["q"])
    async def queue_cmd(self, ctx, page: int = 1):
        if page < 1:
            await ctx.send("❌ Queue page must be 1 or higher.")
            return
        await self.send_queue(ctx.guild, ctx.channel, page=page)

    @commands.command(name="remove")
    async def remove(self, ctx, position: int):
        if not await self.require_control(ctx):
            return
        state = self.state_for(ctx.guild.id)
        items = list(state.queue)
        if position < 1 or position > len(items):
            await ctx.send("❌ Invalid queue position.")
            return
        item = items.pop(position - 1)
        state.queue = deque(items)
        await ctx.send(f"🗑️ Removed **{item['query']}**.")

    @commands.command(name="move")
    async def move(self, ctx, from_position: int, to_position: int):
        if not await self.require_control(ctx):
            return
        state = self.state_for(ctx.guild.id)
        items = list(state.queue)
        if not (1 <= from_position <= len(items) and 1 <= to_position <= len(items)):
            await ctx.send("❌ Both positions must be inside the current queue.")
            return
        item = items.pop(from_position - 1)
        items.insert(to_position - 1, item)
        state.queue = deque(items)
        await ctx.send(f"↕️ Moved **{item['query']}** to position **{to_position}**.")

    @commands.command(name="jump")
    async def jump(self, ctx, position: int):
        if not await self.require_control(ctx):
            return

        state = await self.ensure_settings(ctx.guild.id)
        items = list(state.queue)

        if position < 1 or position > len(items):
            await ctx.send(
                f"❌ Invalid queue position. Choose a position from 1 to {len(items)}."
            )
            return

        target = items[position - 1]
        state.queue = deque(items[position:])

        target_item = {
            "query": target["query"],
            "requester_name": target["requester_name"],
        }

        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            generation = state.current.get("generation") if state.current else None
            state.intentional_stop_generation = generation
            state.queue.appendleft(target_item)
            vc.stop()
        else:
            state.queue.appendleft(target_item)
            await self._play_next(ctx.guild)

        await ctx.send(
            f"⏭️ Jumping to **{target['query']}** at queue position **{position}**."
        )

    @commands.command(name="clear")
    async def clear_queue(self, ctx):
        if not await self.require_control(ctx):
            return
        state = self.state_for(ctx.guild.id)
        count = len(state.queue)
        state.queue.clear()
        await ctx.send(f"🧹 Cleared {count} queued track(s).")

    @commands.command(name="shuffle")
    async def shuffle(self, ctx):
        if not await self.require_control(ctx):
            return
        state = await self.ensure_settings(ctx.guild.id)
        if len(state.queue) < 2:
            await ctx.send("Not enough songs in the queue to shuffle.")
            return
        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)
        await ctx.send("🔀 Queue shuffled.")

    @staticmethod
    def _format_duration(seconds):
        if seconds is None:
            return "LIVE"
        try:
            total = max(0, int(seconds))
        except (TypeError, ValueError):
            return "?:??"
        minutes, secs = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"

    def _current_position(self, state):
        track = state.current
        if not track:
            return 0.0
        elapsed = time.monotonic() - track.get("started_at", time.monotonic())
        elapsed -= track.get("paused_total", 0.0)
        if track.get("paused_at") is not None:
            elapsed -= time.monotonic() - track["paused_at"]
        return max(0.0, elapsed)

    def _progress_bar(self, position, duration, width=18):
        if not duration or duration <= 0:
            return "🔴 LIVE"
        ratio = min(1.0, max(0.0, position / duration))
        filled = int(ratio * width)
        return "▬" * filled + "🔘" + "▬" * (width - filled)

    @commands.command(name="nowplaying", aliases=["np", "music"])
    async def nowplaying(self, ctx):
        state = await self.ensure_settings(ctx.guild.id)
        if not state.current:
            await ctx.send("Nothing is playing.")
            return
        track = state.current
        duration = track.get("duration")
        position = self._current_position(state)
        embed = discord.Embed(
            title="🎵 ECLIPSE NOW PLAYING",
            description=(
                f"**{track['title']}**\n"
                f"{self._progress_bar(position, duration)}\n"
                f"`{self._format_duration(position)} / {self._format_duration(duration)}`"
            ),
            color=COLOR_MUSIC,
        )
        embed.add_field(name="Requester", value=track["requester_name"], inline=True)
        embed.add_field(name="Queue", value=str(len(state.queue)), inline=True)
        embed.add_field(name="Loop", value=state.loop_mode, inline=True)
        embed.add_field(name="Volume", value=f"{round(state.volume * 100)}%", inline=True)
        embed.add_field(name="Autoplay", value="on" if state.autoplay else "off", inline=True)
        embed.add_field(name="24/7", value="on" if state.twentyfour_seven else "off", inline=True)
        embed.set_footer(text="Progress shown at the moment this panel was opened.")
        await ctx.send(embed=embed, view=MusicControlView(self, ctx.guild.id))

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, percent: int):
        if not await self.require_control(ctx):
            return
        if not 0 <= percent <= 200:
            await ctx.send("🔊 Choose a volume between 0 and 200.")
            return
        state = await self.ensure_settings(ctx.guild.id)
        state.volume = percent / 100
        if ctx.voice_client and ctx.voice_client.source:
            try:
                ctx.voice_client.source.volume = state.volume
            except AttributeError:
                pass
        await self.persist_settings(ctx.guild.id, state)
        await ctx.send(f"🔊 Volume set to {percent}% and saved.")

    @commands.command(name="loop")
    async def loop_cmd(self, ctx, mode: str = None):
        if not await self.require_control(ctx):
            return
        state = await self.ensure_settings(ctx.guild.id)
        if mode is None:
            await ctx.send(f"🔁 Current loop mode: {state.loop_mode}.")
            return
        mode = mode.lower()
        if mode not in ("off", "single", "queue"):
            await ctx.send("🔁 Choose off, single, or queue.")
            return
        state.loop_mode = mode
        await self.persist_settings(ctx.guild.id, state)
        await ctx.send(f"🔁 Loop mode set to {mode} and saved.")

    @commands.command(name="autoplay", aliases=["ap"])
    async def autoplay(self, ctx, mode: str = None):
        if not await self.require_control(ctx):
            return
        state = await self.ensure_settings(ctx.guild.id)
        if mode is None:
            await ctx.send(f"✨ Autoplay is {'on' if state.autoplay else 'off'}.")
            return
        mode = mode.lower()
        if mode not in {"on", "off", "true", "false"}:
            await ctx.send("✨ Use on or off.")
            return
        state.autoplay = mode in {"on", "true"}
        await self.persist_settings(ctx.guild.id, state)
        await ctx.send(f"✨ Autoplay {'enabled' if state.autoplay else 'disabled'}.")

    @commands.command(name="247")
    async def twentyfour_seven(self, ctx, mode: str = None):
        if not await self.require_control(ctx):
            return
        state = await self.ensure_settings(ctx.guild.id)
        if mode is None:
            await ctx.send(f"♾️ 24/7 mode is {'on' if state.twentyfour_seven else 'off'}.")
            return
        mode = mode.lower()
        if mode not in {"on", "off", "true", "false"}:
            await ctx.send("♾️ Use on or off.")
            return
        state.twentyfour_seven = mode in {"on", "true"}
        if state.twentyfour_seven:
            state.auto_disconnect = False
        await self.persist_settings(ctx.guild.id, state)
        await ctx.send(f"♾️ 24/7 mode {'enabled' if state.twentyfour_seven else 'disabled'}.")

    @commands.command(name="djrole")
    @commands.has_guild_permissions(manage_guild=True)
    async def djrole(self, ctx, role: discord.Role = None):
        state = await self.ensure_settings(ctx.guild.id)
        if role is None:
            state.dj_role_id = None
            await self.persist_settings(ctx.guild.id, state)
            await ctx.send("🎧 DJ role cleared; Manage Server is now required for music controls.")
            return
        state.dj_role_id = str(role.id)
        await self.persist_settings(ctx.guild.id, state)
        await ctx.send(f"🎧 DJ role set to {role.name}.")

    @commands.command(name="musicsettings", aliases=["musicconfig"])
    @commands.has_guild_permissions(manage_guild=True)
    async def musicsettings(self, ctx, setting: str = None, value: str = None):
        state = await self.ensure_settings(ctx.guild.id)
        if not setting:
            description = (
                f"Volume: {round(state.volume*100)}%\n"
                f"Loop: {state.loop_mode}\n"
                f"Autoplay: {'on' if state.autoplay else 'off'}\n"
                f"24/7: {'on' if state.twentyfour_seven else 'off'}\n"
                f"Auto-disconnect: {'on' if state.auto_disconnect else 'off'}\n"
                f"Queue limit: {state.queue_limit}\n"
                f"Search: {state.search_behavior}\n"
                + (f"DJ role: <@&{state.dj_role_id}>" if state.dj_role_id else "DJ role: Manage Server")
            )
            embed = discord.Embed(title="🎵 ECLIPSE MUSIC SETTINGS", description=description, color=COLOR_MUSIC)
            await ctx.send(embed=embed)
            return
        key = setting.lower().replace("-", "_")
        if value is None:
            await ctx.send("Provide a value for that setting.")
            return
        if key == "volume":
            try: pct = int(value)
            except ValueError:
                await ctx.send("Volume must be 0-200."); return
            if not 0 <= pct <= 200:
                await ctx.send("Volume must be 0-200."); return
            state.volume = pct / 100
        elif key in {"loop", "loop_mode"}:
            if value.lower() not in {"off", "single", "queue"}:
                await ctx.send("Loop must be off, single, or queue."); return
            state.loop_mode = value.lower()
        elif key in {"autoplay", "auto_play"}:
            state.autoplay = value.lower() in {"on", "true", "1", "yes"}
        elif key in {"247", "24_7", "twentyfour_seven"}:
            state.twentyfour_seven = value.lower() in {"on", "true", "1", "yes"}
            if state.twentyfour_seven:
                state.auto_disconnect = False
        elif key in {"auto_disconnect", "autodisconnect"}:
            state.auto_disconnect = value.lower() in {"on", "true", "1", "yes"}
        elif key in {"queue_limit", "limit"}:
            try: limit = int(value)
            except ValueError:
                await ctx.send("Queue limit must be 1-250."); return
            if not 1 <= limit <= 250:
                await ctx.send("Queue limit must be 1-250."); return
            state.queue_limit = limit
        elif key in {"search", "search_behavior"}:
            if value.lower() not in {"youtube", "yt"}:
                await ctx.send("Search behavior currently supports youtube."); return
            state.search_behavior = "youtube"
        else:
            await ctx.send("Unknown setting. Use musicsettings without arguments to view them."); return
        await self.persist_settings(ctx.guild.id, state)
        await ctx.send(f"⚙️ Saved {key}.")

    @commands.command(name="panel")
    async def panel(self, ctx):
        await self.nowplaying(ctx)

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