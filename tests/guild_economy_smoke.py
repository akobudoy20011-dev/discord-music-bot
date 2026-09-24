import asyncio
import tempfile

from database import Database


async def smoke():
    with tempfile.NamedTemporaryFile(suffix=".db") as handle:
        db = Database(handle.name)
        await db.connect()

        # Atomic wallet withdrawal: the second concurrent-style attempt must fail.
        await db.get_user("server", "user")
        ok, reason, balance = await db.withdraw_balance("server", "user", 100)
        assert ok and balance == 0
        ok, reason, balance = await db.withdraw_balance("server", "user", 1)
        assert not ok and reason == "balance" and balance == 0

        gid, reason = await db.create_guild("server", "server-g1", "Eclipse Vanguard", "user")
        assert gid == "server-g1"
        ok, reason = await db.join_guild(gid, "other", "server")
        assert ok
        assert (await db.get_user_guild("server", "other"))["guild_id"] == gid

        await db.add_balance("server", "other", 1000)
        ok, reason, _ = await db.guild_treasury_deposit(gid, "other", 500)
        assert ok
        guild = await db.get_guild(gid)
        assert guild["treasury"] == 500
        assert guild["level"] == 1

        await db.create_guild_event(gid, "event-1", "Test Event", "test", 10, 100, 10, 3600)
        ok, reason = await db.contribute_guild_event(gid, "other", 10)
        assert ok and reason == "completed"
        reward, reason = await db.claim_guild_event_reward(gid, "other")
        assert reward == (100, 10) and reason == "ok"

        await db.create_guild_boss(gid, "boss-1", "Test Boss", 100, 10, 100, 10, 3600)
        ok, reason, hp = await db.damage_guild_boss(gid, "other", 100)
        assert ok and reason == "defeated" and hp == 0
        reward, reason = await db.claim_guild_boss_reward(gid, "other")
        assert reward == (100, 10) and reason == "ok"

        await db.close()


if __name__ == "__main__":
    asyncio.run(smoke())
    print("guild/economy smoke test passed")
