                    f"ALTER TABLE guild_config ADD COLUMN {name} {definition}"
                )

        world_cur = await self._conn.execute("PRAGMA table_info(rpg_worlds)")
        world_columns = {row["name"] for row in await world_cur.fetchall()}
        if "active_event" not in world_columns:
            await self._conn.execute("ALTER TABLE rpg_worlds ADD COLUMN active_event TEXT")
        if "event_until" not in world_columns:
            await self._conn.execute("ALTER TABLE rpg_worlds ADD COLUMN event_until REAL")

        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ------------------------------------------------------------
    # USERS
    # ------------------------------------------------------------

    async def get_user(self, guild_id, user_id):
        guild_id, user_id = str(guild_id), str(user_id)

        cur = await self._conn.execute(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()

        if row is None:
            await self._conn.execute(
                "INSERT INTO users (guild_id, user_id, balance) "
                "VALUES (?, ?, ?)",
                (guild_id, user_id, STARTING_BALANCE)
            )
            await self._conn.commit()

            data = dict(DEFAULT_USER)
            data["guild_id"] = guild_id
            data["user_id"] = user_id
            return data

        data = dict(row)
        data["achievements"] = json.loads(data["achievements"] or "[]")
        return data

    async def update_user(self, guild_id, user_id, **fields):
        """update_user(guild_id, user_id, balance=500, xp=10)"""

        guild_id, user_id = str(guild_id), str(user_id)

        # make sure the row exists first
        await self.get_user(guild_id, user_id)

        if "achievements" in fields:
            fields["achievements"] = json.dumps(fields["achievements"])

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [guild_id, user_id]

        await self._conn.execute(
            f"UPDATE users SET {set_clause} "
            f"WHERE guild_id = ? AND user_id = ?",
            values
        )
        await self._conn.commit()

    async def add_balance(self, guild_id, user_id, amount):
        user = await self.get_user(guild_id, user_id)
        new_balance = max(0, user["balance"] + amount)
        await self.update_user(guild_id, user_id, balance=new_balance)
        return new_balance

    async def add_xp(self, guild_id, user_id, amount):
        """Returns (old_level, new_level, new_xp)."""

        user = await self.get_user(guild_id, user_id)

        xp = user["xp"] + amount
        level = user["level"]
        old_level = level

        while xp >= level * 100:
            xp -= level * 100
            level += 1

        await self.update_user(guild_id, user_id, xp=xp, level=level)

        return old_level, level, xp

    async def add_achievement(self, guild_id, user_id, name):
        user = await self.get_user(guild_id, user_id)

        if name in user["achievements"]:
            return False

        user["achievements"].append(name)

        await self.update_user(
            guild_id, user_id, achievements=user["achievements"]
        )

        return True

    async def leaderboard(self, guild_id, order_by="balance", limit=10):
        assert order_by in (
            "balance", "level", "messages", "wins"
        )

        guild_id = str(guild_id)

        if order_by == "level":
            order_sql = "level DESC, xp DESC"
        else:
            order_sql = f"{order_by} DESC"

        cur = await self._conn.execute(
            f"SELECT * FROM users WHERE guild_id = ? "
            f"ORDER BY {order_sql} LIMIT ?",
            (guild_id, limit)
        )
        rows = await cur.fetchall()

        return [dict(r) for r in rows]

    async def rank_position(self, guild_id, user_id, order_by="level"):
        rows = await self.leaderboard(guild_id, order_by=order_by, limit=10_000)

        for i, row in enumerate(rows, start=1):
            if row["user_id"] == str(user_id):
                return i

        return len(rows) + 1

    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # GAME HALL STATS
    # ------------------------------------------------------------

    async def record_game(self, guild_id, user_id, game_id, result="loss", wager=0, net=0):
        guild_id, user_id, game_id = str(guild_id), str(user_id), str(game_id)
        net = int(net)
        wager = max(0, int(wager))
        await self._conn.execute(
            "INSERT INTO game_stats "
            "(guild_id,user_id,game_id,plays,wins,losses,ties,wagered,won_coins,lost_coins,best_streak,current_streak) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,game_id) DO UPDATE SET "
            "plays=plays+1,wins=wins+excluded.wins,losses=losses+excluded.losses,ties=ties+excluded.ties,"
            "wagered=wagered+excluded.wagered,won_coins=won_coins+excluded.won_coins,lost_coins=lost_coins+excluded.lost_coins,"
            "current_streak=CASE WHEN excluded.wins=1 THEN current_streak+1 ELSE 0 END,"
            "best_streak=MAX(best_streak,CASE WHEN excluded.wins=1 THEN current_streak+1 ELSE best_streak END)",
            (guild_id,user_id,game_id,1,int(result=="win"),int(result=="loss"),int(result=="tie"),
             wager,max(0,net),max(0,-net),int(result=="win"),int(result=="win"))
        )
        await self._conn.commit()
        day_key = time.strftime("%Y-%m-%d", time.gmtime())
        await self.advance_arcade_daily(guild_id, user_id, day_key, result, game_id)

    async def get_game_stats(self, guild_id, user_id, game_id=None):
        if game_id:
            cur = await self._conn.execute(
                "SELECT * FROM game_stats WHERE guild_id=? AND user_id=? AND game_id=?",
                (str(guild_id),str(user_id),str(game_id))
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        cur = await self._conn.execute(
            "SELECT * FROM game_stats WHERE guild_id=? AND user_id=? ORDER BY plays DESC",
            (str(guild_id),str(user_id))
        )
        return [dict(r) for r in await cur.fetchall()]

    async def game_leaderboard(self, guild_id, game_id, limit=10):
        cur = await self._conn.execute(
            "SELECT user_id,plays,wins,losses,ties,wagered,won_coins,lost_coins,best_streak "
            "FROM game_stats WHERE guild_id=? AND game_id=? "
            "ORDER BY wins DESC,best_streak DESC,won_coins DESC LIMIT ?",
            (str(guild_id),str(game_id),int(limit))
        )
        return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------
    # ARCADE DAILY CHALLENGES
    # ------------------------------------------------------------

    ARCADE_DAILY = (
        ("play3", "Play 3 recorded arcade games.", 3),
        ("win2", "Win 2 recorded arcade games.", 2),
        ("play5", "Play 5 recorded arcade games.", 5),
        ("pvpwin1", "Win 1 PvP arcade game.", 1),
    )

    async def get_arcade_daily(self, guild_id, user_id, day_key):
        import datetime
        index = int(day_key.replace("-", "")) % len(self.ARCADE_DAILY)
        challenge_id, description, target = self.ARCADE_DAILY[index]
        await self._conn.execute(
            "INSERT OR IGNORE INTO arcade_daily "
            "(guild_id,user_id,day_key,challenge_id,progress,claimed) VALUES (?,?,?,?,0,0)",
            (str(guild_id), str(user_id), str(day_key), challenge_id)
        )
        await self._conn.commit()