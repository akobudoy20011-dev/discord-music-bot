"""Small, dependency-free runtime state machine for Discord music playback.

The Discord cog still owns commands and queue policy. This module owns the
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

    def snapshot(self, state) -> dict:
        return {
            "state": getattr(state, "player_state", "IDLE"),
            "age": round(self.age(state), 2),
            "transition_id": getattr(state, "player_transition_id", 0),
            "reason": getattr(state, "last_transition_reason", ""),
            "generation": getattr(state, "playback_generation", 0),
            "has_current": bool(getattr(state, "current", None)),
            "queue_size": len(getattr(state, "queue", ()) or ()),
        }
