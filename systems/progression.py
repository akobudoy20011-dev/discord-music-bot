"""ECLIPSE profile/progression service.

This layer keeps Discord cogs independent from presentation details and
provides a single place for profile snapshots and progression math.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileSnapshot:
    guild_id: str
    user_id: str
    balance: int
    xp: int
    level: int
    messages: int
    games: int
    wins: int
    daily_streak: int
    achievements: tuple

    @property
    def xp_needed(self):
        return max(1, self.level * 100)

    @property
    def xp_percent(self):
        return min(100.0, (self.xp / self.xp_needed) * 100)


def snapshot(user):
    return ProfileSnapshot(
        guild_id=str(user.get("guild_id", "")),
        user_id=str(user.get("user_id", "")),
        balance=int(user.get("balance", 0)),
        xp=int(user.get("xp", 0)),
        level=int(user.get("level", 1)),
        messages=int(user.get("messages", 0)),
        games=int(user.get("games", 0)),
        wins=int(user.get("wins", 0)),
        daily_streak=int(user.get("daily_streak", 0)),
        achievements=tuple(user.get("achievements") or ()),
    )


async def get_snapshot(db, guild_id, user_id):
    return snapshot(await db.get_user(guild_id, user_id))
