"""Runtime state and diagnostics for Discord music playback.

The Discord cog still owns commands and queue policy. This module owns
lifecycle bookkeeping so watchdog/recovery code can reason about a player
without duplicating transition rules.
"""

from __future__ import annotations

import time


class PlaybackRuntime:
    STATES = frozenset({
        "IDLE",
        "STARTING",
        "PLAYING",
        "PAUSED",
        "TRANSITIONING",
        "RECOVERING",
        "ERROR",
    })

    def transition(self, state, new_state: str, *, reason: str = ""):
        if new_state not in self.STATES:
            raise ValueError(f"Unknown playback state: {new_state}")

        old_state = getattr(state, "player_state", "IDLE")
        now = time.monotonic()

        state.player_state = new_state
        state.player_state_since = now
        state.player_transition_id = getattr(state, "player_transition_id", 0) + 1
        state.last_transition_reason = reason
        return old_state, new_state

    def age(self, state) -> float:
        return max(0.0, time.monotonic() - getattr(
            state, "player_state_since", time.monotonic()
        ))

    def record_voice_check(self, state, *, connected, playing, paused):
        state.last_voice_check_at = time.time()
        state.last_voice_connected = bool(connected)
        state.last_voice_playing = bool(playing)
        state.last_voice_paused = bool(paused)

    def record_voice_failure(self, state, reason):
        state.last_voice_failure = reason
        state.last_voice_failure_at = time.time()

    def record_recovery(self, state, reason):
        state.last_recovery_reason = reason
        state.last_recovery_at = time.time()

    def snapshot(self, state) -> dict:
        return {
            "state": getattr(state, "player_state", "IDLE"),
            "age": round(self.age(state), 2),
            "transition_id": getattr(state, "player_transition_id", 0),
            "reason": getattr(state, "last_transition_reason", ""),
            "generation": getattr(state, "playback_generation", 0),
            "has_current": bool(getattr(state, "current", None)),
            "queue_size": len(getattr(state, "queue", ()) or ()),
            "voice": {
                "connected": getattr(state, "last_voice_connected", None),
                "playing": getattr(state, "last_voice_playing", None),
                "paused": getattr(state, "last_voice_paused", None),
                "last_check": getattr(state, "last_voice_check_at", None),
                "last_failure": getattr(state, "last_voice_failure", None),
                "last_failure_at": getattr(state, "last_voice_failure_at", None),
            },
            "recovery": {
                "last_reason": getattr(state, "last_recovery_reason", None),
                "last_at": getattr(state, "last_recovery_at", None),
            },
        }
