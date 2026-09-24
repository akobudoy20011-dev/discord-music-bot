"""Background health watchdog for Discord voice playback and bot readiness."""

from __future__ import annotations

import asyncio
import time

from discord.ext import commands, tasks


class Watchdog(commands.Cog):
    INTERVAL = 20
    STALE_TRANSITION_SECONDS = 45
    STALE_PLAYING_SECONDS = 90
    VOICE_RECOVERY_COOLDOWN = 30
    MAX_RECOVERY_ATTEMPTS = 3
    CONNECT_TIMEOUT = 30

    def __init__(self, bot):
        self.bot = bot
        self.started_at = time.monotonic()
        self.last_run = None
        self.last_error = None
        self.last_recovery = None
        self.last_voice_failure = None
        self.recovery_count = 0
        self._attempts = {}
        self._last_attempt_at = {}
        self._tick.start()

    def cog_unload(self):
        self._tick.cancel()

    def _connected(self, vc):
        if vc is None:
            return False
        try:
            return bool(vc.is_connected())
        except Exception:
            return False

    def _can_attempt(self, guild_id):
        return time.monotonic() - self._last_attempt_at.get(guild_id, 0) >= self.VOICE_RECOVERY_COOLDOWN

    def _note_attempt(self, guild_id):
        count = self._attempts.get(guild_id, 0) + 1
        self._attempts[guild_id] = count
        self._last_attempt_at[guild_id] = time.monotonic()
        return count

    def _reset_attempts(self, guild_id):
        self._attempts.pop(guild_id, None)
        self._last_attempt_at.pop(guild_id, None)

    async def _channel(self, guild, state):
        channel_id = getattr(state, "voice_channel_id", None)
        if channel_id:
            try:
                channel = guild.get_channel(int(channel_id))
            except (TypeError, ValueError):
                channel = None
            if channel is not None and hasattr(channel, "connect"):
                return channel

        vc = guild.voice_client
        channel = getattr(vc, "channel", None) if vc else None
        if channel is not None and hasattr(channel, "connect"):
            state.voice_channel_id = str(channel.id)
            return channel
        return None

    def _failure(self, guild, state, reason, runtime):
        self.last_voice_failure = {
            "guild_id": guild.id,
            "reason": reason,
            "time": time.time(),
        }
        if runtime:
            runtime.record_voice_failure(state, reason)

    async def _restart_current(self, music, guild, state, reason):
        current = dict(state.current) if state.current else None
        if current is None:
            return False

        state.queue.appendleft({
            "query": current["query"],
            "requester_name": current["requester_name"],
        })
        state.current = None

        runtime = getattr(music, "player_runtime", None)
        if runtime:
            runtime.transition(state, "RECOVERING", reason=reason)

        await music._play_next(guild)
        return True

    async def _recover_voice(self, music, guild, state, reason):
        if getattr(state, "manual_disconnect", False) or not self._can_attempt(guild.id):
            return False

        attempt = self._note_attempt(guild.id)
        runtime = getattr(music, "player_runtime", None)
        self.recovery_count += 1
        self._failure(guild, state, reason, runtime)

        self.last_recovery = {
            "guild_id": guild.id,
            "reason": reason,
            "time": time.time(),
            "attempt": attempt,
            "kind": "voice",
        }

        if runtime:
            runtime.record_recovery(state, reason)
            runtime.transition(state, "RECOVERING", reason=reason)

        channel = await self._channel(guild, state)
        if channel is None:
            if runtime:
                runtime.transition(state, "ERROR", reason="voice recovery has no channel")
            return False

        try:
            vc = guild.voice_client
            if vc is not None and not self._connected(vc):
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass

            vc = guild.voice_client
            if vc is None:
                vc = await asyncio.wait_for(
                    channel.connect(reconnect=True, self_deaf=True),
                    timeout=self.CONNECT_TIMEOUT,
                )
            elif getattr(vc, "channel", None) is not channel:
                await asyncio.wait_for(vc.move_to(channel), timeout=self.CONNECT_TIMEOUT)

            state.manual_disconnect = False

            if state.current:
                await self._restart_current(
                    music, guild, state,
                    "voice reconnected; restarting interrupted track",
                )
            elif state.queue:
                await music._play_next(guild)

            self._reset_attempts(guild.id)
            return True

        except Exception as exc:
            self.last_error = f"voice recovery guild {guild.id}: {type(exc).__name__}: {exc}"
            self._failure(guild, state, self.last_error, runtime)
            if runtime:
                runtime.transition(state, "ERROR", reason=self.last_error)
            return False

    async def _recover_playback(self, music, guild, state, reason):
        if getattr(state, "manual_disconnect", False) or not self._can_attempt(guild.id):
            return False

        vc = guild.voice_client
        if vc is None or not self._connected(vc):
            return await self._recover_voice(music, guild, state, reason)

        if vc.is_playing() or vc.is_paused():
            return False

        attempt = self._note_attempt(guild.id)
        runtime = getattr(music, "player_runtime", None)
        self.recovery_count += 1
        self.last_recovery = {
            "guild_id": guild.id,
            "reason": reason,
            "time": time.time(),
            "attempt": attempt,
            "kind": "playback",
        }

        try:
            if runtime:
                runtime.record_recovery(state, reason)
                runtime.transition(state, "RECOVERING", reason=reason)
            if state.current:
                await self._restart_current(music, guild, state, reason)
            else:
                await music._play_next(guild)
            self._reset_attempts(guild.id)
            return True
        except Exception as exc:
            self.last_error = f"playback recovery guild {guild.id}: {type(exc).__name__}: {exc}"
            if runtime:
                runtime.transition(state, "ERROR", reason=self.last_error)
            return False

    @tasks.loop(seconds=INTERVAL)
    async def _tick(self):
        self.last_run = time.time()
        self.last_error = None

        try:
            if not self.bot.is_ready():
                return

            music = self.bot.get_cog("Music")
            if music is None:
                return

            runtime = getattr(music, "player_runtime", None)

            for guild in list(self.bot.guilds):
                state = music.states.get(guild.id)
                if state is None:
                    continue

                vc = guild.voice_client
                connected = self._connected(vc)
                playing = bool(vc and vc.is_playing())
                paused = bool(vc and vc.is_paused())

                if runtime:
                    runtime.record_voice_check(
                        state,
                        connected=connected,
                        playing=playing,
                        paused=paused,
                    )

                if getattr(state, "manual_disconnect", False):
                    continue

                player_state = getattr(state, "player_state", "IDLE")
                age = runtime.age(state) if runtime else max(
                    0, time.monotonic() - getattr(state, "player_state_since", time.monotonic())
                )

                # Primary fix for the "works for a couple tracks then vanishes"
                # failure: a current track with a lost Discord voice transport.
                if (
                    state.current
                    and player_state in {"PLAYING", "PAUSED"}
                    and not connected
                ):
                    await self._recover_voice(
                        music,
                        guild,
                        state,
                        "voice client missing or disconnected during playback",
                    )
                    continue

                if (
                    player_state == "IDLE"
                    and state.queue
                    and connected
                    and not playing
                    and not paused
                ):
                    await self._recover_playback(
                        music, guild, state,
                        "idle player with queued tracks",
                    )
                    continue

                if player_state in {"STARTING", "TRANSITIONING", "RECOVERING"}:
                    if age >= self.STALE_TRANSITION_SECONDS:
                        if state.current and not connected:
                            await self._recover_voice(
                                music, guild, state,
                                f"stale {player_state.lower()} state with lost voice ({age:.0f}s)",
                            )
                        else:
                            await self._recover_playback(
                                music, guild, state,
                                f"stale {player_state.lower()} state ({age:.0f}s)",
                            )
                    continue

                if (
                    player_state == "PLAYING"
                    and state.current
                    and connected
                    and not playing
                    and not paused
                    and age >= self.STALE_PLAYING_SECONDS
                ):
                    await self._recover_playback(
                        music, guild, state,
                        f"playing state lost audio ({age:.0f}s)",
                    )

        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
