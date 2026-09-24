import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import tempfile

from database import Database
from systems.arcade_tournament_db import bind_database


async def smoke():
    with tempfile.NamedTemporaryFile(suffix=".db") as handle:
        db = Database(handle.name)
        bind_database(Database)
        await db.connect()

        guild = "arcade-guild"
        p1 = "player-1"
        p2 = "player-2"

        await db.get_user(guild, p1)
        await db.get_user(guild, p2)

        tournament = await db.create_arcade_tournament(
            guild, "dicebattle", "CI Cup", entry_fee=10, max_players=2
        )

        ok, reason = await db.join_arcade_tournament(
            guild, tournament["tournament_id"], p1
        )
        assert ok and reason == "joined"

        ok, reason = await db.join_arcade_tournament(
            guild, tournament["tournament_id"], p2
        )
        assert ok and reason == "joined"

        ok, reason, _ = await db.start_arcade_tournament(
            guild, tournament["tournament_id"]
        )
        assert ok and reason == "started"

        matches = await db.get_arcade_matches(tournament["tournament_id"])
        ready = [m for m in matches if m["status"] == "ready"]
        assert len(ready) == 1

        match_id = ready[0]["match_id"]

        ok, claimed = await db.claim_arcade_match(guild, match_id, p1)
        assert ok
        assert claimed["status"] == "playing"

        ok, _ = await db.claim_arcade_match(guild, match_id, p2)
        assert not ok

        ok, result = await db.resolve_arcade_match(match_id, p1)
        assert ok
        assert result["finished"] is True
        assert result["winner_id"] == p1
        assert result["payout"] == 20

        champion = await db.get_user(guild, p1)
        runner_up = await db.get_user(guild, p2)
        assert champion["balance"] == 110
        assert runner_up["balance"] == 90
        assert champion["tournament_wins"] == 1
        assert runner_up["tournament_wins"] == 0

        finished = await db.get_arcade_tournament(
            guild, tournament["tournament_id"]
        )
        assert finished["status"] == "finished"
        assert finished["prize_awarded"] == 20

        await db.close()


if __name__ == "__main__":
    asyncio.run(smoke())
    print("arcade tournament smoke test passed")
