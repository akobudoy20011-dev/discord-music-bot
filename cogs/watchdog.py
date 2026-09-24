"""Background health watchdog for Discord voice playback and bot readiness."""

from __future__ import annotations

import time

from discord.ext import commands, tasks


class Watchdog(commands.Cog):
    """Detects stale music states and nudges the player back into a safe state.

    The watchdog is deliberately conservative: normal Discord/FFmpeg callbacks
    remain the primary transition mechanism. Recovery only happens when a state
    has been stale long enough to be considered abnormal.
    """

    INTERVAL = 20
    STALE_TRANSITION_SECONDS = 45
    STALE_PLAYING_SECONDS = 90

    def __init__(self, bot):
        self.bot = bot
        self.started_at = time.monotonic()
        self.last_run = None
        self.last_error = None
        self.last_recovery = None
        self.recovery_count = 0
        self._tick.start()

    def cog_unload(self):
        self._tick.cancel()

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
                player_state = getattr(state, "player_state", "IDLE")
                age = (
                    runtime.age(state)
                    if runtime is not None
                    else max(0.0, time.monotonic() - getattr(
                        state, "player_state_since", time.monotonic()
                    ))
                )

                # A queued guild with an idle voice client should not remain
                # stranded after a missed callback.
                if (
                    player_state == "IDLE"
                    and state.queue
                    and vc is not None
                    and not vc.is_playing()
                    and not vc.is_paused()
                ):
                    await self._recover(guild, state, "idle player with queued tracks")
                    continue

                # STARTING/TRANSITIONING are normally very short-lived. If
                # one persists, the player may have lost its callback or
                # Discord's voice player may have wedged.
                if player_state in {"STARTING", "TRANSITIONING", "RECOVERING"}:
                    if age >= self.STALE_TRANSITION_SECONDS:
                        await self._recover(
                            guild, state, f"stale {player_state.lower()} state ({age:.0f}s)"
                        )
                    continue

                # A PLAYING state with no actual Discord audio for a long
                # period is the other common silent-failure mode. Do not
                # touch short gaps; Discord/FFmpeg can legitimately take a
                # moment to tear down a stream.
                if (
                    player_state == "PLAYING"
                    and state.current
                    and vc is not None
                    and not vc.is_playing()
                    and not vc.is_paused()
                    and age >= self.STALE_PLAYING_SECONDS
                ):
                    await self._recover(
                        guild, state, f"playing state lost audio ({age:.0f}s)"
                    )

        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"

    async def _recover(self, guild, state, reason):
        music = self.bot.get_cog("Music")
        if music is None:
            return

        vc = guild.voice_client
        if vc is not None and (vc.is_playing() or vc.is_paused()):
            return

        self.recovery_count += 1
        self.last_recovery = {
            "guild_id": guild.id,
            "reason": reason,
            "time": time.time(),
        }

        runtime = getattr(music, "player_runtime", None)
        if runtime is not None:
            runtime.transition(state, "RECOVERING", reason=reason)
        else:
            state.player_state = "RECOVERING"

        try:
            await music._play_next(guild)
        except Exception as exc:
            self.last_error = f"recovery {guild.id}: {type(exc).__name__}: {exc}"
            if runtime is not None:
                runtime.transition(state, "ERROR", reason=self.last_error)
        