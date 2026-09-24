"""Smoke tests for the ECLIPSE RPG special-move subsystem."""

import asyncio
import tempfile

from database import Database
from rpg.combat import special as cast_special
from rpg.specials import SPECIALS, available_specials, get_special


async def smoke():
    assert len(SPECIALS) == 13

    darkness = get_special("infinite_darkness")
    assert darkness is not None
    assert darkness["duration"] == 5

    # Level-gated codex exposure.
    assert "infinite_darkness" in {
        sid for sid, _ in available_specials("wraith", 3)
    }
    assert "worldbreaker" not in {
        sid for sid, _ in available_specials("wraith", 3)
    }

    with tempfile.NamedTemporaryFile(suffix=".db") as handle:
        db = Database(handle.name)
        await db.connect()

        await db.update_rpg_player(
            "smoke-guild",
            "smoke-user",
            class_key="wraith",
            level=3,
            mp=40,
        )
        await db.set_rpg_battle(
            "smoke-guild",
            "smoke-user",
            enemy_id="smoke_target",
            enemy_name="Smoke Target",
            enemy_hp=999,
            enemy_max_hp=999,
            enemy_attack=1,
            turn=1,
            guarding=0,
            effects="{}",
            special_cooldowns="{}",
        )

        result = await cast_special(
            db,
            "smoke-guild",
            "smoke-user",
            "infinite_darkness",
        )

        assert result["ok"] is True
        assert result["special_id"] == "infinite_darkness"
        assert result["enemy_skipped"] is True
        # The cast consumes the first of the five enemy turns immediately;
        # four remaining frozen turns are persisted for the next actions.
        assert result["effects"]["enemy_freeze_turns"] == 4

        battle = await db.get_rpg_battle("smoke-guild", "smoke-user")
        assert battle is not None
        assert '"infinite_darkness":5' in battle["special_cooldowns"]

        await db.close()


if __name__ == "__main__":
    asyncio.run(smoke())
    print("RPG specials smoke test passed")
