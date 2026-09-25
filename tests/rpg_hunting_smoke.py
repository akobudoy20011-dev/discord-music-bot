import asyncio
import tempfile

from database import Database
from rpg.hunting import board, start_hunt
from rpg.combat import start as start_battle


async def smoke():
    with tempfile.NamedTemporaryFile(suffix=".db") as handle:
        db = Database(handle.name)
        await db.connect()

        player = await db.get_rpg_player("hunt-guild", "hunt-user")
        assert player["level"] == 1

        result = await board(db, "hunt-guild", "hunt-user")
        assert result["contracts"]
        assert result["profile"]["hunt_level"] == 1

        prepared = await start_hunt(
            db, "hunt-guild", "hunt-user", result["contracts"][0]["contract_id"]
        )
        assert prepared["ok"]
        assert prepared["target"]["monster_level"] >= 1

        # The prepared hunt must retain the exact display name in persistence.
        active_prepared = await db.get_rpg_hunt_active("hunt-guild", "hunt-user")
        assert active_prepared["enemy_name"] == prepared["target"]["name"]

        battle = await start_battle(
            db,
            "hunt-guild",
            "hunt-user",
            enemy_override=prepared["target"],
            hunt_mode=True,
        )
        assert battle["ok"]
        assert battle["battle"]["enemy_name"] == prepared["target"]["name"]

        active = await db.get_rpg_hunt_active("hunt-guild", "hunt-user")
        assert active["enemy_id"] == prepared["target"]["id"]

        await db.close()


if __name__ == "__main__":
    asyncio.run(smoke())
    print("rpg hunting smoke test passed")
