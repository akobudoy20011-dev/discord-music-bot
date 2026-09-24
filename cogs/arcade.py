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

from constants import COLOR_GOLD, COLOR_PRIMARY


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

    async def finish(self, guild_id, user_id, game_id, result, wager=0, net=0):
        await self.db.record_game(guild_id, user_id, game_id, result, wager, net)
        day_key = time.strftime("%Y-%m-%d", time.gmtime())
        await self.db.advance_arcade_daily(guild_id, user_id, day_key, result)

    @commands.command(name="arcade")
    async def arcade(self, ctx):
        await ctx.send(embed=self.embed(
            "୨୧ ECLIPSE · ARCADE ୨୧",
            "🎮 **PvP** — !ttt · !connect4 · !dicebattle\n"
            "📊 **Records** — !gamestats · !gameleaderboard <game>\n"
            "📜 **Daily** — !dailies · !claimdaily\n\n"
            f"PvP wagers cap at **{MAX_BET:,} coins**."
        ))

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
            await self.finish(ctx.guild.id, ctx.author.id, "dicebattle", "tie", bet, 0)
            await self.finish(ctx.guild.id, opponent.id, "dicebattle", "tie", bet, 0)
            text = f"🎲 {ctx.author.mention}: **{a}**\n🎲 {opponent.mention}: **{b}**\n\n👔 **DRAW.**"
        else:
            winner = ctx.author if a > b else opponent
            loser = opponent if winner.id == ctx.author.id else ctx.author
            if bet:
                await self.db.add_balance(ctx.guild.id, winner.id, bet * 2)
            await self.finish(ctx.guild.id, winner.id, "dicebattle", "win", bet, bet)
            await self.finish(ctx.guild.id, loser.id, "dicebattle", "loss", bet, -bet)
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
                                    await cog.finish(ctx.guild.id, p.id, "ttt", "tie", bet, 0)
                                text = "👔 **DRAW.** Bets returned." if bet else "👔 **DRAW.**"
                                color = COLOR_GOLD
                            else:
                                winner_user = players[winner]
                                loser_user = players[1 - winner]
                                if bet:
                                    await cog.db.add_balance(ctx.guild.id, winner_user.id, bet * 2)
                                await cog.finish(ctx.guild.id, winner_user.id, "ttt", "win", bet, bet)
                                await cog.finish(ctx.guild.id, loser_user.id, "ttt", "loss", bet, -bet)
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
                                await cog.finish(ctx.guild.id, p.id, "connect4", "tie", bet, 0)
                            text = "👔 **DRAW.** Bets returned." if bet else "👔 **DRAW.**"
                            color = COLOR_GOLD
                        else:
                            winner_user = players[winner]
                            loser_user = players[1 - winner]
                            if bet:
                                await cog.db.add_balance(ctx.guild.id, winner_user.id, bet * 2)
                            await cog.finish(ctx.guild.id, winner_user.id, "connect4", "win", bet, bet)
                            await cog.finish(ctx.guild.id, loser_user.id, "connect4", "loss", bet, -bet)
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
