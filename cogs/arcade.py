"""
cogs/arcade.py
==============
ECLIPSE multiplayer arcade layer.

This cog is intentionally separate from the original games cog so the
existing single-player games remain stable while persistent PvP stats,
daily challenges, and multiplayer tables evolve independently.
"""

import time

import discord
from discord.ext import commands

from constants import COLOR_GOLD, COLOR_PRIMARY, check_achievements, rank_title


MAX_BET = 1_000_000


class Arcade(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def embed(self, title, description, color=COLOR_PRIMARY):
        return discord.Embed(title=title, description=description, color=color)

    async def take_wager(self, guild_id, user_id, amount):
        amount = int(amount)
        if amount < 0 or amount > MAX_BET:
            return False
        if amount == 0:
            return True
        user = await self.db.get_user(guild_id, user_id)
        if int(user["balance"]) < amount:
            return False
        await self.db.add_balance(guild_id, user_id, -amount)
        return True

    async def finish(self, guild_id, user_id, game_id, result, wager=0, net=0, ctx=None):
        await self.db.record_game(guild_id, user_id, game_id, result, wager, net)
        await self.db.advance_arcade_season(guild_id, user_id, result, net)

        xp_reward = {"win": 60, "tie": 30, "loss": 20}.get(result, 0)
        old_level, new_level, _ = await self.db.add_xp(
            guild_id, user_id, xp_reward
        )

        day_key = time.strftime("%Y-%m-%d", time.gmtime())
        await self.db.advance_arcade_daily(guild_id, user_id, day_key, result)

        if ctx is not None:
            user = await self.db.get_user(guild_id, user_id)

            class _FakeCtx:
                pass

            fake = _FakeCtx()
            fake.guild = ctx.guild
            fake.channel = ctx.channel
            fake.author = ctx.guild.get_member(int(user_id)) or ctx.author

            await check_achievements(self.db, fake, fake.author, user)

            if new_level > old_level:
                await ctx.channel.send(
                    f"🎮 **Arcade level up!** <@{user_id}> reached **Level {new_level}** — *{rank_title(new_level)}*"
                )

    @commands.group(name="season", aliases=["arcadeseason"], invoke_without_command=True)
    @commands.guild_only()
    async def season(self, ctx):
        current = await self.db.get_arcade_season(ctx.guild.id)
        if not current:
            await ctx.send("🎮 No active arcade season. Staff can start one with !season start <name> [days].")
            return
        remaining = max(0, int(current["ends_at"] - time.time()))
        days, rem = divmod(remaining, 86400)
        hours = rem // 3600
        board = await self.db.get_arcade_season_leaderboard(ctx.guild.id, current["season_id"], 5)
        lines = [
            f"**{i}.** <@{row['user_id']}> — **{row['points']:,} pts** · {row['wins']}W/{row['plays']}P"
            for i, row in enumerate(board, 1)
        ]
        desc = (
            f"Season **{current['name']}** · <t:{int(current['ends_at'])}:R>\n"
            f"Remaining: **{days}d {hours}h**\n\n"
            + ("\n".join(lines) if lines else "No players have scored yet.")
        )
        await ctx.send(embed=self.embed("🎮 ECLIPSE · ARCADE SEASON", desc, COLOR_GOLD))

    @season.command(name="start")
    @commands.has_guild_permissions(manage_guild=True)
    async def season_start(self, ctx, name: str, days: int = 30):
        season, reason = await self.db.create_arcade_season(ctx.guild.id, name, days, created_by=ctx.author.id)
        if not season:
            return await ctx.send("❌ An arcade season is already active.")
        await ctx.send(
            f"🎮 **Season started:** {season['name']}\n"
            f"Ends <t:{int(season['ends_at'])}:F>\n"
            f"Winner rewards: **{season['reward_coins']:,} coins + {season['reward_xp']:,} XP**."
        )

    @season.command(name="leaderboard", aliases=["lb", "top"])
    async def season_leaderboard(self, ctx):
        season = await self.db.get_arcade_season(ctx.guild.id)
        if not season:
            return await ctx.send("❌ No active arcade season.")
        rows = await self.db.get_arcade_season_leaderboard(ctx.guild.id, season["season_id"], 10)
        if not rows:
            return await ctx.send("🎮 The season leaderboard is empty.")
        lines = [
            f"**{i}.** <@{r['user_id']}> — **{r['points']:,} pts** · {r['wins']} wins · {r['plays']} plays"
            for i, r in enumerate(rows, 1)
        ]
        await ctx.send(embed=self.embed("🏆 SEASON LEADERBOARD", "\n".join(lines), COLOR_GOLD))

    @season.command(name="stats")
    async def season_stats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        season = await self.db.get_arcade_season(ctx.guild.id)
        if not season:
            return await ctx.send("❌ No active arcade season.")
        stats = await self.db.get_arcade_season_stats(ctx.guild.id, member.id, season["season_id"])
        await ctx.send(embed=self.embed(
            f"🎮 {member.display_name} · SEASON STATS",
            f"**Points:** {stats['points']:,}\n**Wins:** {stats['wins']}\n**Plays:** {stats['plays']}\n**Net coins:** {stats['net_coins']:+,}"
        ))

    @season.command(name="end")
    @commands.has_guild_permissions(manage_guild=True)
    async def season_end(self, ctx):
        season = await self.db.get_arcade_season(ctx.guild.id)
        if not season:
            return await ctx.send("❌ No active arcade season.")
        winner = await self.db.finish_arcade_season(ctx.guild.id, season["season_id"])
        if not winner:
            return await ctx.send("🏁 Season ended with no ranked players.")
        await ctx.send(
            f"🏁 **{season['name']} has ended.**\n"
            f"Champion: <@{winner['user_id']}> with **{winner['points']:,} points**.\n"
            f"Reward: **{season['reward_coins']:,} coins + {season['reward_xp']:,} XP**."
        )

    @commands.group(name="tournament", aliases=["tourny"], invoke_without_command=True)
    async def tournament(self, ctx):
        t = await self.db.get_arcade_tournament(ctx.guild.id)
        if not t:
            history = await self.db.tournament_history(ctx.guild.id, 1)
            if history:
                h = history[0]
                await ctx.send(embed=self.embed("🏆 ECLIPSE · TOURNAMENT", f"No active tournament. Last champion: <@{h['winner_id']}>\n**{h['name']}** · prize **{h['prize_awarded']:,}**"))
            else:
                await ctx.send("🏆 No active tournament. Use !tournament create <game> <name> [fee] [players].")
            return
        players = await self.db.get_arcade_tournament_players(t["tournament_id"])
        matches = await self.db.get_arcade_matches(t["tournament_id"])
        ready = [m for m in matches if m["status"] == "ready"]
        desc = (f"**{t['name']}** · `{t['game_id']}`\nStatus: **{t['status']}**\nEntry: **{t['entry_fee']:,}** · Prize pool: **{t['prize_pool']:,}**\nPlayers: **{len(players)}/{t['max_players']}**")
        if ready:
            desc += "\n\n" + "\n".join(f"Match #{m['match_id']}: <@{m['player_a']}> vs <@{m['player_b']}>" for m in ready[:10])
        await ctx.send(embed=self.embed("🏆 ECLIPSE · TOURNAMENT", desc, COLOR_GOLD))

    @tournament.command(name="create")
    @commands.guild_only()
    async def tournament_create(self, ctx, game: str, *, args: str):
        parts = args.rsplit(" ", 2)
        name = parts[0]
        fee = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        max_players = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 8
        max_players = max(2, min(32, max_players))
        allowed = {"ttt", "connect4", "dicebattle"}
        if game.lower() not in allowed:
            return await ctx.send("❌ Tournament game must be: `ttt`, `connect4`, or `dicebattle`.")
        if fee < 0 or fee > MAX_BET:
            return await ctx.send("❌ Entry fee must be between 0 and 1,000,000.")
        if await self.db.get_arcade_tournament(ctx.guild.id):
            return await ctx.send("❌ This server already has an active tournament.")
        t = await self.db.create_arcade_tournament(ctx.guild.id, game.lower(), name, fee, max_players)
        await ctx.send(f"🏆 Tournament created: **{t['name']}** · {game.lower()} · entry **{fee:,}** · max **{max_players}**\nJoin with !tournament join.")

    @tournament.command(name="join")
    async def tournament_join(self, ctx):
        t = await self.db.get_arcade_tournament(ctx.guild.id)
        if not t:
            return await ctx.send("❌ No open tournament.")
        ok, reason = await self.db.join_arcade_tournament(ctx.guild.id, t["tournament_id"], ctx.author.id)
        messages = {"closed":"Tournament is closed.","full":"Tournament is full.","joined":"You already joined.","balance":"You cannot afford the entry fee."}
        if not ok:
            return await ctx.send("❌ " + messages.get(reason, reason))
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        await check_achievements(self.db, ctx, ctx.author, user)
        await ctx.send(f"🎟️ {ctx.author.mention} entered **{t['name']}**.")

    @tournament.command(name="start")
    @commands.has_guild_permissions(manage_guild=True)
    async def tournament_start(self, ctx):
        t = await self.db.get_arcade_tournament(ctx.guild.id)
        if not t:
            return await ctx.send("❌ No open tournament.")
        ok, reason, _ = await self.db.start_arcade_tournament(ctx.guild.id, t["tournament_id"])
        if not ok:
            return await ctx.send("❌ At least 2 players are required." if reason == "players" else "❌ Tournament cannot start.")
        await ctx.send(f"⚔️ **{t['name']} has begun.** Byes advance automatically.")

    @tournament.command(name="bracket")
    async def tournament_bracket(self, ctx):
        t = await self.db.get_arcade_tournament(ctx.guild.id)
        if not t:
            return await ctx.send("❌ No active tournament.")
        matches = await self.db.get_arcade_matches(t["tournament_id"])
        lines = []
        for m in matches:
            a = f"<@{m['player_a']}>" if m["player_a"] else "BYE"
            b = f"<@{m['player_b']}>" if m["player_b"] else "BYE"
            winner = f" → <@{m['winner_id']}>" if m["winner_id"] else ""
            lines.append(f"**R{m['round']} · #{m['match_id']}** — {a} vs {b} · `{m['status']}`{winner}")
        await ctx.send(embed=self.embed("🏆 BRACKET", "\n".join(lines) or "No matches yet."))

    @tournament.command(name="match")
    @commands.has_guild_permissions(manage_guild=True)
    async def tournament_match(self, ctx, match_id: int, winner: discord.Member):
        ok, result = await self.db.resolve_arcade_match(match_id, winner.id)
        if not ok:
            return await ctx.send("❌ Invalid match or winner.")
        if result and result.get("finished"):
            await ctx.send(f"👑 **TOURNAMENT COMPLETE.** {winner.mention} is champion and receives **{result['payout']:,} coins.**")
            user = await self.db.get_user(ctx.guild.id, winner.id)
            await check_achievements(self.db, ctx, winner, user)
        else:
            await ctx.send(f"⚔️ **Match #{match_id} resolved.** {winner.mention} advances. Next round generated automatically.")

    @tournament.command(name="history")
    async def tournament_history(self, ctx):
        rows = await self.db.tournament_history(ctx.guild.id, 10)
        if not rows:
            return await ctx.send("🏆 No completed tournaments yet.")
        lines = [f"**#{r['tournament_id']}** · {r['name']} · `{r['game_id']}` · Champion <@{r['winner_id']}> · **{r['prize_awarded']:,}** prize" for r in rows]
        await ctx.send(embed=self.embed("📜 TOURNAMENT HISTORY", "\n".join(lines), COLOR_GOLD))

    @tournament.command(name="stats")
    async def tournament_stats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        stats = await self.db.get_tournament_stats(ctx.guild.id, member.id)
        await ctx.send(embed=self.embed(f"🏟️ {member.display_name} · TOURNAMENT RECORD", f"Entries: **{stats['entries']}**\nMatch wins: **{stats['match_wins']}**\nChampionships: **{stats['championships']}**\nPrize money won: **{stats['prize_money']:,}**"))

    @tournament.command(name="cancel")
    @commands.has_guild_permissions(manage_guild=True)
    async def tournament_cancel(self, ctx):
        t = await self.db.get_arcade_tournament(ctx.guild.id)
        if not t:
            return await ctx.send("❌ No active tournament.")
        ok, reason, refund = await self.db.cancel_arcade_tournament(ctx.guild.id, t["tournament_id"])
        if not ok:
            return await ctx.send("❌ Only an open tournament can be cancelled/refunded.")
        await ctx.send(f"🛑 **{t['name']} cancelled.** Refunded **{refund:,} coins** to entrants.")

    async def _complete_tournament_match(self, ctx, match, winner_id, reason=None):
        loser_id = (
            match["player_b"]
            if str(winner_id) == str(match["player_a"])
            else match["player_a"]
        )
        ok, result = await self.db.resolve_arcade_match(match["match_id"], winner_id)
        if not ok:
            return False, None

        game_id = str(match["game_id"])
        await self.finish(match["guild_id"], winner_id, game_id, "win", 0, 0, ctx)
        if loser_id:
            await self.finish(match["guild_id"], loser_id, game_id, "loss", 0, 0, ctx)

        if result and result.get("finished"):
            await ctx.send(
                f"👑 **TOURNAMENT COMPLETE.** <@{winner_id}> wins "
                f"**{match['tournament_name']}** and receives "
                f"**{result['payout']:,} coins.**"
            )
        else:
            suffix = f" · {reason}" if reason else ""
            await ctx.send(
                f"⚔️ <@{winner_id}> wins **Match #{match['match_id']}**"
                f"{suffix}. The next round is now ready."
            )
        return True, result

    @tournament.command(name="play", aliases=["fight", "enter"])
    async def tournament_play(self, ctx, match_id: int):
        ok, match = await self.db.claim_arcade_match(
            ctx.guild.id, match_id, ctx.author.id
        )
        if not ok:
            return await ctx.send(
                "❌ That match is not ready, does not belong to this server, "
                "or you are not one of its players."
            )

        game_id = str(match["game_id"])
        player_a = ctx.guild.get_member(int(match["player_a"]))
        player_b = ctx.guild.get_member(int(match["player_b"]))
        if not player_a or not player_b:
            other_id = (
                match["player_b"]
                if str(ctx.author.id) == str(match["player_a"])
                else match["player_a"]
            )
            await self._complete_tournament_match(
                ctx, match, other_id, "opponent unavailable"
            )
            return

        if game_id == "dicebattle":
            import random
            a = random.randint(1, 6)
            b = random.randint(1, 6)
            if a == b:
                await ctx.send(
                    embed=self.embed(
                        "🎲 TOURNAMENT · DICE BATTLE",
                        f"<@{player_a.id}> rolled **{a}**\n"
                        f"<@{player_b.id}> rolled **{b}**\n\n"
                        "👔 **DRAW — roll again.**",
                        COLOR_GOLD,
                    )
                )
                await self.db.reset_arcade_match(match_id)
                return

            winner = player_a if a > b else player_b
            await ctx.send(
                embed=self.embed(
                    "🎲 TOURNAMENT · DICE BATTLE",
                    f"<@{player_a.id}> rolled **{a}**\n"
                    f"<@{player_b.id}> rolled **{b}**",
                )
            )
            await self._complete_tournament_match(ctx, match, winner.id)
            return

        if game_id == "ttt":
            await ctx.send(
                embed=self.embed(
                    "⭕ TOURNAMENT · TIC-TAC-TOE",
                    f"**{player_a.display_name}** (X) vs "
                    f"**{player_b.display_name}** (O)\n"
                    f"Match **#{match_id}** · first player starts.",
                ),
                view=self._tournament_ttt_view(ctx, match, player_a, player_b),
            )
            return

        if game_id == "connect4":
            await ctx.send(
                embed=self.embed(
                    "🔴 TOURNAMENT · CONNECT FOUR",
                    f"**{player_a.display_name}** (🔴) vs "
                    f"**{player_b.display_name}** (🟡)\n"
                    f"Match **#{match_id}** · first player starts.\n\n"
                    + "\n".join("⚪" * 7 for _ in range(6)),
                ),
                view=self._tournament_connect4_view(ctx, match, player_a, player_b),
            )
            return

        await self.db.resolve_arcade_match(match_id, player_b.id)
        await ctx.send("❌ Unsupported tournament game; the match was resolved safely.")

    def _tournament_ttt_view(self, ctx, match, player_a, player_b):
        board = [""] * 9
        players = [player_a, player_b]
        turn = 0
        cog = self

        class TournamentTTT(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=300)
                view.done = False
                for idx in range(9):
                    button = discord.ui.Button(
                        label="·",
                        style=discord.ButtonStyle.secondary,
                        row=idx // 3,
                    )

                    async def press(interaction, index=idx, btn=button):
                        nonlocal turn
                        if view.done:
                            return
                        if interaction.user.id != players[turn].id:
                            return await interaction.response.send_message(
                                "❌ Not your turn.", ephemeral=True
                            )
                        if board[index]:
                            return await interaction.response.send_message(
                                "❌ That square is occupied.", ephemeral=True
                            )

                        board[index] = "X" if turn == 0 else "O"
                        btn.label = board[index]
                        wins = (
                            (0,1,2),(3,4,5),(6,7,8),
                            (0,3,6),(1,4,7),(2,5,8),
                            (0,4,8),(2,4,6),
                        )
                        winner = turn if any(
                            board[a] and board[a] == board[b] == board[c]
                            for a, b, c in wins
                        ) else None
                        draw = winner is None and all(board)

                        if winner is not None or draw:
                            view.done = True
                            view.stop()
                            for child in view.children:
                                child.disabled = True

                            if draw:
                                await interaction.response.edit_message(
                                    embed=cog.embed(
                                        "⭕ TOURNAMENT · TIC-TAC-TOE",
                                        "👔 **DRAW. Replay the match with the same match ID.**",
                                        COLOR_GOLD,
                                    ),
                                    view=view,
                                )
                                await cog.db.reset_arcade_match(match["match_id"])
                                return

                            winner_user = players[winner]
                            await interaction.response.edit_message(
                                embed=cog.embed(
                                    "⭕ TOURNAMENT · TIC-TAC-TOE",
                                    f"🏆 **{winner_user.display_name} wins Match #{match['match_id']}.**",
                                    discord.Color.green(),
                                ),
                                view=view,
                            )
                            await cog._complete_tournament_match(
                                ctx, match, winner_user.id
                            )
                            return

                        turn = 1 - turn
                        await interaction.response.edit_message(
                            embed=cog.embed(
                                "⭕ TOURNAMENT · TIC-TAC-TOE",
                                f"**{players[turn].display_name}**'s turn.\n"
                                f"X · {players[0].display_name}\n"
                                f"O · {players[1].display_name}",
                            ),
                            view=view,
                        )

            async def on_timeout(view):
                if view.done:
                    return
                view.done = True
                view.stop()
                winner = players[1 - turn]
                await cog._complete_tournament_match(
                    ctx, match, winner.id, "opponent timed out"
                )

        return TournamentTTT()

    def _tournament_connect4_view(self, ctx, match, player_a, player_b):
        board = [[None] * 7 for _ in range(6)]
        players = [player_a, player_b]
        turn = 0
        cog = self

        class TournamentConnect4(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=600)
                view.done = False
                select = discord.ui.Select(
                    placeholder="Choose a column",
                    options=[
                        discord.SelectOption(
                            label=f"Column {i + 1}", value=str(i)
                        )
                        for i in range(7)
                    ],
                )

                async def choose(interaction):
                    nonlocal turn
                    if view.done:
                        return
                    if interaction.user.id != players[turn].id:
                        return await interaction.response.send_message(
                            "❌ Not your turn.", ephemeral=True
                        )

                    col = int(select.values[0])
                    row = next(
                        (r for r in range(5, -1, -1) if board[r][col] is None),
                        None,
                    )
                    if row is None:
                        return await interaction.response.send_message(
                            "❌ That column is full.", ephemeral=True
                        )

                    board[row][col] = turn
                    winner = None
                    for r in range(6):
                        for c in range(7):
                            player = board[r][c]
                            if player is None:
                                continue
                            for dr, dc in ((1,0),(0,1),(1,1),(1,-1)):
                                if all(
                                    0 <= r + dr*n < 6
                                    and 0 <= c + dc*n < 7
                                    and board[r + dr*n][c + dc*n] == player
                                    for n in range(4)
                                ):
                                    winner = player
                                    break
                            if winner is not None:
                                break
                        if winner is not None:
                            break

                    full = all(
                        cell is not None
                        for rowv in board
                        for cell in rowv
                    )
                    board_text = "\n".join(
                        "".join(
                            "🔴" if cell == 0 else "🟡" if cell == 1 else "⚪"
                            for cell in rowv
                        )
                        for rowv in board
                    )

                    if winner is not None or full:
                        view.done = True
                        view.stop()
                        for child in view.children:
                            child.disabled = True

                        if winner is None:
                            await interaction.response.edit_message(
                                embed=cog.embed(
                                    "🔴 TOURNAMENT · CONNECT FOUR",
                                    f"{board_text}\n\n"
                                    "👔 **DRAW. Replay the match with the same match ID.**",
                                    COLOR_GOLD,
                                ),
                                view=view,
                            )
                            await cog.db.reset_arcade_match(match["match_id"])
                            return

                        winner_user = players[winner]
                        await interaction.response.edit_message(
                            embed=cog.embed(
                                "🔴 TOURNAMENT · CONNECT FOUR",
                                f"{board_text}\n\n"
                                f"🏆 **{winner_user.display_name} wins "
                                f"Match #{match['match_id']}.**",
                                discord.Color.green(),
                            ),
                            view=view,
                        )
                        await cog._complete_tournament_match(
                            ctx, match, winner_user.id
                        )
                        return

                    turn = 1 - turn
                    await interaction.response.edit_message(
                        embed=cog.embed(
                            "🔴 TOURNAMENT · CONNECT FOUR",
                            f"{board_text}\n\n"
                            f"**{players[turn].display_name}**'s turn.",
                        ),
                        view=view,
                    )

                select.callback = choose
                view.add_item(select)

            async def on_timeout(view):
                if view.done:
                    return
                view.done = True
                view.stop()
                winner = players[1 - turn]
                await cog._complete_tournament_match(
                    ctx, match, winner.id, "opponent timed out"
                )

        return TournamentConnect4()

    @commands.command(name="arcade")
    async def arcade(self, ctx):
        await ctx.send(embed=self.embed(
            "୨୧ ECLIPSE · ARCADE ୨୧",
            "🎮 **PvP** — !ttt · !connect4 · !dicebattle\n"
            "📊 **Records** — !gamestats · !gameleaderboard <game>\n"
            "📜 **Daily** — !dailies · !claimdaily\n\n"
            f"PvP wagers cap at **{MAX_BET:,} coins**."
        ))

    @commands.command(name="arcadeprofile", aliases=["ap", "arcadeid"])
    async def arcadeprofile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        wins = int(user.get("arcade_wins", 0))
        plays = int(user.get("arcade_plays", 0))
        losses = max(0, plays - wins)
        wagered = int(user.get("arcade_wagered", 0))
        net = int(user.get("arcade_net", 0))
        best = int(user.get("arcade_best_streak", 0))
        winrate = (wins / plays * 100) if plays else 0
        embed = self.embed(
            f"🎮 {member.display_name} · ARCADE IDENTITY",
            f"**{plays:,}** games · **{wins:,}** wins · **{losses:,}** losses\\n"
            f"Win rate: **{winrate:.1f}%** · Best streak: **{best}**\\n"
            f"Wagered: **{wagered:,}** · Net: **{net:+,}** coins\\n\\n"
            f"Arcade XP: **{user['xp']:,} / {user['level'] * 100:,}**\\n"
            f"Level **{user['level']}** · *{rank_title(user['level'])}*"
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="gamestats", aliases=["gstats"])
    async def gamestats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        rows = await self.db.get_game_stats(ctx.guild.id, member.id)
        if not rows:
            await ctx.send(f"🎮 **{member.display_name}** has no arcade record yet.")
            return
        total = sum(int(r["plays"]) for r in rows)
        wins = sum(int(r["wins"]) for r in rows)
        losses = sum(int(r["losses"]) for r in rows)
        ties = sum(int(r["ties"]) for r in rows)
        wagered = sum(int(r["wagered"]) for r in rows)
        net = sum(int(r["net_coins"]) for r in rows)
        best = max(int(r["best_streak"]) for r in rows)
        lines = [
            f"**{r['game_id']}** · {r['plays']} plays · {r['wins']}W / {r['losses']}L / {r['ties']}T · streak {r['best_streak']}"
            for r in rows
        ]
        await ctx.send(embed=self.embed(
            f"📊 {member.display_name} · ARCADE RECORD",
            f"**{total}** plays · **{wins}W** · **{losses}L** · **{ties}T**\n"
            f"Wagered: **{wagered:,}** · Net: **{net:+,}**\n"
            f"Best streak: **{best}**\n\n" + "\n".join(lines)
        ))

    @commands.command(name="gameleaderboard", aliases=["gameboard", "glb"])
    async def gameleaderboard(self, ctx, game_id: str):
        rows = await self.db.game_leaderboard(ctx.guild.id, game_id.lower(), 10)
        if not rows:
            await ctx.send("🏆 No records exist for that game yet.")
            return
        lines = []
        for i, row in enumerate(rows, 1):
            lines.append(
                f"**{i}.** <@{row['user_id']}> · {row['wins']}W · "
                f"{row['best_streak']} streak · {int(row['net_coins']):+,} net"
            )
        await ctx.send(embed=self.embed(
            f"🏆 {game_id.upper()} · LEADERBOARD",
            "\n".join(lines),
            COLOR_GOLD
        ))

    @commands.command(name="dailies", aliases=["dailygame", "arcadedaily"])
    async def dailies(self, ctx):
        day_key = time.strftime("%Y-%m-%d", time.gmtime())
        data = await self.db.get_arcade_daily(ctx.guild.id, ctx.author.id, day_key)
        status = "CLAIMED" if data["claimed"] else (
            "READY" if data["progress"] >= data["target"] else "IN PROGRESS"
        )
        await ctx.send(embed=self.embed(
            "📜 ECLIPSE · DAILY ARCADE",
            f"**{data['description']}**\n"
            f"Progress: **{data['progress']}/{data['target']}**\n"
            f"Status: **{status}**\n\n"
            "Reward: **500 coins + 150 XP**"
        ))

    @commands.command(name="claimdaily")
    async def claimdaily(self, ctx):
        day_key = time.strftime("%Y-%m-%d", time.gmtime())
        ok, reason, data = await self.db.claim_arcade_daily(
            ctx.guild.id, ctx.author.id, day_key
        )
        if ok:
            await ctx.send(embed=self.embed(
                "🎁 DAILY ARCADE CLAIMED",
                "You received **500 coins + 150 XP**.\n\n"
                "୨୧ Come back tomorrow for a new challenge. ୨୧",
                discord.Color.green()
            ))
            return
        if reason == "claimed":
            text = "Today's reward has already been claimed."
        else:
            text = f"Still incomplete: **{data['progress']}/{data['target']}**."
        await ctx.send(embed=self.embed("📜 DAILY ARCADE", text, COLOR_GOLD))

    @commands.command(name="dicebattle", aliases=["dicewar", "dbattle"])
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def dicebattle(self, ctx, opponent: discord.Member, bet: int = 0):
        if opponent.bot or opponent.id == ctx.author.id:
            await ctx.send("❌ Choose another human player.")
            return
        if bet < 0 or bet > MAX_BET:
            await ctx.send(f"❌ Wager must be 0–{MAX_BET:,}.")
            return
        if not await self.take_wager(ctx.guild.id, ctx.author.id, bet):
            await ctx.send("❌ You do not have enough coins for that wager.")
            return
        if not await self.take_wager(ctx.guild.id, opponent.id, bet):
            if bet:
                await self.db.add_balance(ctx.guild.id, ctx.author.id, bet)
            await ctx.send("❌ Your opponent does not have enough coins.")
            return

        a, b = __import__("random").randint(1, 6), __import__("random").randint(1, 6)
        if a == b:
            if bet:
                await self.db.add_balance(ctx.guild.id, ctx.author.id, bet)
                await self.db.add_balance(ctx.guild.id, opponent.id, bet)
            await self.finish(ctx.guild.id, ctx.author.id, "dicebattle", "tie", bet, 0, ctx)
            await self.finish(ctx.guild.id, opponent.id, "dicebattle", "tie", bet, 0, ctx)
            text = f"🎲 {ctx.author.mention}: **{a}**\n🎲 {opponent.mention}: **{b}**\n\n👔 **DRAW.**"
        else:
            winner = ctx.author if a > b else opponent
            loser = opponent if winner.id == ctx.author.id else ctx.author
            if bet:
                await self.db.add_balance(ctx.guild.id, winner.id, bet * 2)
            await self.finish(ctx.guild.id, winner.id, "dicebattle", "win", bet, bet, ctx)
            await self.finish(ctx.guild.id, loser.id, "dicebattle", "loss", bet, -bet, ctx)
            text = f"🎲 {ctx.author.mention}: **{a}**\n🎲 {opponent.mention}: **{b}**\n\n🏆 **{winner.display_name} wins.**"
        await ctx.send(embed=self.embed("🎲 DICE BATTLE", text))

    @commands.command(name="ttt", aliases=["tictactoe", "xo"])
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def ttt(self, ctx, opponent: discord.Member, bet: int = 0):
        if opponent.bot or opponent.id == ctx.author.id:
            await ctx.send("❌ Choose another human player.")
            return
        if bet < 0 or bet > MAX_BET:
            await ctx.send(f"❌ Wager must be 0–{MAX_BET:,}.")
            return
        if not await self.take_wager(ctx.guild.id, ctx.author.id, bet):
            await ctx.send("❌ You do not have enough coins for that wager.")
            return
        if not await self.take_wager(ctx.guild.id, opponent.id, bet):
            if bet:
                await self.db.add_balance(ctx.guild.id, ctx.author.id, bet)
            await ctx.send("❌ Your opponent does not have enough coins.")
            return

        board = [""] * 9
        players = [ctx.author, opponent]
        turn = 0
        cog = self

        class Board(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=180)
                view.done = False
                for idx in range(9):
                    button = discord.ui.Button(
                        label="·", style=discord.ButtonStyle.secondary, row=idx // 3
                    )
                    async def press(interaction, index=idx, btn=button):
                        nonlocal turn
                        if interaction.user.id != players[turn].id:
                            await interaction.response.send_message("❌ Not your turn.", ephemeral=True)
                            return
                        if view.done or board[index]:
                            return
                        board[index] = "X" if turn == 0 else "O"
                        btn.label = board[index]
                        lines = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))
                        winner = turn if any(
                            board[a] and board[a] == board[b] == board[c]
                            for a,b,c in lines
                        ) else None
                        draw = winner is None and all(board)
                        if winner is not None or draw:
                            view.done = True
                            view.stop()
                            for child in view.children:
                                child.disabled = True
                            if draw:
                                if bet:
                                    for p in players:
                                        await cog.db.add_balance(ctx.guild.id, p.id, bet)
                                for p in players:
                                    await cog.finish(ctx.guild.id, p.id, "ttt", "tie", bet, 0, ctx)
                                text = "👔 **DRAW.** Bets returned." if bet else "👔 **DRAW.**"
                                color = COLOR_GOLD
                            else:
                                winner_user = players[winner]
                                loser_user = players[1 - winner]
                                if bet:
                                    await cog.db.add_balance(ctx.guild.id, winner_user.id, bet * 2)
                                await cog.finish(ctx.guild.id, winner_user.id, "ttt", "win", bet, bet, ctx)
                                await cog.finish(ctx.guild.id, loser_user.id, "ttt", "loss", bet, -bet, ctx)
                                text = f"🏆 **{winner_user.display_name} wins.**"
                                color = discord.Color.green()
                            await interaction.response.edit_message(
                                embed=cog.embed("⭕ TIC-TAC-TOE", text, color), view=view
                            )
                            return
                        turn = 1 - turn
                        await interaction.response.edit_message(
                            embed=cog.embed(
                                "⭕ TIC-TAC-TOE",
                                f"**{players[turn].display_name}**'s turn.\n"
                                f"X · {players[0].display_name}\nO · {players[1].display_name}"
                            ),
                            view=view
                        )
                    button.callback = press
                    view.add_item(button)

            async def on_timeout(view):
                if view.done:
                    return
                view.done = True
                view.stop()
                if bet:
                    for p in players:
                        await cog.db.add_balance(ctx.guild.id, p.id, bet)
                for p in players:
                    await cog.finish(ctx.guild.id, p.id, "ttt", "tie", bet, 0)
                try:
                    await ctx.send("⏰ Tic-Tac-Toe expired. Any wager was returned.")
                except discord.HTTPException:
                    pass

        await ctx.send(
            embed=self.embed(
                "⭕ TIC-TAC-TOE",
                f"**{ctx.author.display_name}** (X) vs **{opponent.display_name}** (O)\n"
                f"{'Wager: ' + format(bet, ',') + ' each' if bet else 'Friendly match'}"
            ),
            view=Board()
        )

    @commands.command(name="connect4", aliases=["connectfour", "c4"])
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def connect4(self, ctx, opponent: discord.Member, bet: int = 0):
        if opponent.bot or opponent.id == ctx.author.id:
            await ctx.send("❌ Choose another human player.")
            return
        if bet < 0 or bet > MAX_BET:
            await ctx.send(f"❌ Wager must be 0–{MAX_BET:,}.")
            return
        if not await self.take_wager(ctx.guild.id, ctx.author.id, bet):
            await ctx.send("❌ You do not have enough coins for that wager.")
            return
        if not await self.take_wager(ctx.guild.id, opponent.id, bet):
            if bet:
                await self.db.add_balance(ctx.guild.id, ctx.author.id, bet)
            await ctx.send("❌ Your opponent does not have enough coins.")
            return

        board = [[None] * 7 for _ in range(6)]
        players = [ctx.author, opponent]
        turn = 0
        cog = self

        class Board(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=300)
                view.done = False
                select = discord.ui.Select(
                    placeholder="Choose a column",
                    options=[discord.SelectOption(label=f"Column {i+1}", value=str(i)) for i in range(7)]
                )

                async def choose(interaction):
                    nonlocal turn
                    if interaction.user.id != players[turn].id:
                        await interaction.response.send_message("❌ Not your turn.", ephemeral=True)
                        return
                    if view.done:
                        return
                    col = int(select.values[0])
                    row = next((r for r in range(5, -1, -1) if board[r][col] is None), None)
                    if row is None:
                        await interaction.response.send_message("❌ That column is full.", ephemeral=True)
                        return
                    board[row][col] = turn

                    winner = None
                    for r in range(6):
                        for c in range(7):
                            player = board[r][c]
                            if player is None:
                                continue
                            for dr, dc in ((1,0),(0,1),(1,1),(1,-1)):
                                if all(
                                    0 <= r + dr*n < 6 and
                                    0 <= c + dc*n < 7 and
                                    board[r + dr*n][c + dc*n] == player
                                    for n in range(4)
                                ):
                                    winner = player
                                    break
                            if winner is not None:
                                break
                        if winner is not None:
                            break

                    full = all(cell is not None for rowv in board for cell in rowv)
                    if winner is not None or full:
                        view.done = True
                        view.stop()
                        if winner is None:
                            if bet:
                                for p in players:
                                    await cog.db.add_balance(ctx.guild.id, p.id, bet)
                            for p in players:
                                await cog.finish(ctx.guild.id, p.id, "connect4", "tie", bet, 0, ctx)
                            text = "👔 **DRAW.** Bets returned." if bet else "👔 **DRAW.**"
                            color = COLOR_GOLD
                        else:
                            winner_user = players[winner]
                            loser_user = players[1 - winner]
                            if bet:
                                await cog.db.add_balance(ctx.guild.id, winner_user.id, bet * 2)
                            await cog.finish(ctx.guild.id, winner_user.id, "connect4", "win", bet, bet, ctx)
                            await cog.finish(ctx.guild.id, loser_user.id, "connect4", "loss", bet, -bet, ctx)
                            text = f"🏆 **{winner_user.display_name} wins.**"
                            color = discord.Color.green()
                        for child in view.children:
                            child.disabled = True
                        board_text = "\n".join(
                            "".join("🔴" if cell == 0 else "🟡" if cell == 1 else "⚪" for cell in rowv)
                            for rowv in board
                        )
                        await interaction.response.edit_message(
                            embed=cog.embed("🔴 CONNECT FOUR", f"{board_text}\n\n{text}", color),
                            view=view
                        )
                        return

                    turn = 1 - turn
                    board_text = "\n".join(
                        "".join("🔴" if cell == 0 else "🟡" if cell == 1 else "⚪" for cell in rowv)
                        for rowv in board
                    )
                    await interaction.response.edit_message(
                        embed=cog.embed(
                            "🔴 CONNECT FOUR",
                            f"{board_text}\n\n**{players[turn].display_name}**'s turn."
                        ),
                        view=view
                    )

                select.callback = choose
                view.add_item(select)

            async def on_timeout(view):
                if view.done:
                    return
                view.done = True
                view.stop()
                if bet:
                    for p in players:
                        await cog.db.add_balance(ctx.guild.id, p.id, bet)
                for p in players:
                    await cog.finish(ctx.guild.id, p.id, "connect4", "tie", bet, 0)
                try:
                    await ctx.send("⏰ Connect Four expired. Any wager was returned.")
                except discord.HTTPException:
                    pass

        await ctx.send(
            embed=self.embed(
                "🔴 CONNECT FOUR",
                "\n".join("⚪" * 7 for _ in range(6)) +
                f"\n\n**{ctx.author.display_name}** starts."
            ),
            view=Board()
        )


async def setup(bot):
    await bot.add_cog(Arcade(bot))
