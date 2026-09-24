import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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

        # Exercise every one of the thirteen restored specials through the
        # real persistence + combat path, not just the registry.
        for special_id, data in SPECIALS.items():
            class_key = data["class_keys"][0]
            level = int(data["level"])
            await db.delete_rpg_battle("smoke-guild", "smoke-user")
            await db.update_rpg_player(
                "smoke-guild",
                "smoke-user",
                class_key=class_key,
                level=level,
                mp=200,
                hp=1000,
                max_hp=1000,
            )
            await db.set_rpg_battle(
                "smoke-guild",
                "smoke-user",
                enemy_id="smoke_target",
                enemy_name="Smoke Target",
                enemy_hp=999999,
                enemy_max_hp=999999,
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
                special_id,
            )
            assert result["ok"] is True, (special_id, result)
            assert result["special_id"] == special_id
            battle = await db.get_rpg_battle("smoke-guild", "smoke-user")
            assert battle is not None
            assert f'"{special_id}":{int(data["cooldown"])}' in battle["special_cooldowns"]

        # Infinite Darkness keeps its original five-move freeze behavior:
        # the cast consumes the first enemy turn and persists four more.
        await db.delete_rpg_battle("smoke-guild", "smoke-user")
        await db.update_rpg_player(
            "smoke-guild",
            "smoke-user",
            class_key="wraith",
            level=3,
            mp=40,
            hp=1000,
            max_hp=1000,
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
        assert result["enemy_skipped"] is True
        assert result["effects"]["enemy_freeze_turns"] == 4

        await db.close()


if __name__ == "__main__":
    asyncio.run(smoke())
    print("RPG specials smoke test passed")
