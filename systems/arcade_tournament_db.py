"""Live tournament match persistence helpers.

Kept separate from the large legacy database module so the arcade match
state machine can evolve without rewriting database.py wholesale.
"""


async def claim_arcade_match(self, guild_id, match_id, user_id):
    cur = await self._conn.execute(
        """
        SELECT m.*, t.guild_id, t.game_id, t.name AS tournament_name
        FROM arcade_tournament_matches m
        JOIN arcade_tournaments t ON t.tournament_id = m.tournament_id
        WHERE m.match_id = ?
        """,
        (int(match_id),),
    )
    row = await cur.fetchone()
    if not row:
        return False, None

    match = dict(row)
    if str(match["guild_id"]) != str(guild_id):
        return False, None
    if match["status"] != "ready":
        return False, None

    uid = str(user_id)
    if uid not in {str(match["player_a"]), str(match["player_b"])}:
        return False, None

    cur = await self._conn.execute(
        """
        UPDATE arcade_tournament_matches
        SET status='playing'
        WHERE match_id=? AND status='ready'
        """,
        (int(match_id),),
    )
    if cur.rowcount != 1:
        await self._conn.rollback()
        return False, None

    await self._conn.commit()
    match["status"] = "playing"
    return True, match


async def reset_arcade_match(self, match_id):
    cur = await self._conn.execute(
        """
        UPDATE arcade_tournament_matches
        SET status='ready'
        WHERE match_id=? AND status='playing'
        """,
        (int(match_id),),
    )
    await self._conn.commit()
    if cur.rowcount != 1:
        return False

    cur = await self._conn.execute(
        "SELECT * FROM arcade_tournament_matches WHERE match_id=?",
        (int(match_id),),
    )
    row = await cur.fetchone()
    return dict(row) if row else False


async def resolve_arcade_match(self, match_id, winner_id, guild_id=None):
    cur = await self._conn.execute(
        """
        SELECT m.*, t.guild_id, t.game_id, t.name AS tournament_name
        FROM arcade_tournament_matches m
        JOIN arcade_tournaments t ON t.tournament_id = m.tournament_id
        WHERE m.match_id = ?
        """,
        (int(match_id),),
    )
    row = await cur.fetchone()
    if not row:
        return False, None

    match = dict(row)
    if guild_id is not None and str(match["guild_id"]) != str(guild_id):
        return False, None

    winner_id = str(winner_id)
    if match["status"] not in ("ready", "playing"):
        return False, None
    if winner_id not in {
        str(match["player_a"]),
        str(match["player_b"]),
    }:
        return False, None

    cur = await self._conn.execute(
        """
        UPDATE arcade_tournament_matches
        SET winner_id=?, status='complete'
        WHERE match_id=? AND status IN ('ready','playing')
        """,
        (winner_id, int(match_id)),
    )
    if cur.rowcount != 1:
        await self._conn.rollback()
        return False, None

    loser_id = (
        match["player_b"]
        if winner_id == str(match["player_a"])
        else match["player_a"]
    )

    await self._conn.execute(
        """
        UPDATE arcade_tournament_players
        SET wins=wins+1
        WHERE tournament_id=? AND user_id=?
        """,
        (int(match["tournament_id"]), winner_id),
    )

    if loser_id:
        await self._conn.execute(
            """
            UPDATE arcade_tournament_players
            SET eliminated=1
            WHERE tournament_id=? AND user_id=?
            """,
            (int(match["tournament_id"]), str(loser_id)),
        )

    await self._conn.commit()
    result = await self._advance_tournament(int(match["tournament_id"]))
    return True, result


def bind_database(Database):
    """Attach the live-match API to the existing Database class."""
    Database.claim_arcade_match = claim_arcade_match
    Database.reset_arcade_match = reset_arcade_match
    Database.resolve_arcade_match = resolve_arcade_match
