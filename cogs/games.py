"""
cogs/games.py
================
Full collection of mini-games: trivia, rps, roll, guess, coinflip, slots, blackjack, and 8ball.
Integrated with server coin economy (bot.db) and AI-powered 8-ball responses.
"""

import asyncio
import os
import random
import time

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, COLOR_GOLD, footer

# Optional Gemini import for AI-powered 8ball
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

MAX_BET = 1_000_000

TRIVIA_QUESTIONS = [
    {
        "q": "Which element has the chemical symbol 'O'?",
        "options": ["Gold", "Oxygen", "Osmium", "Silver"],
        "answer": 1,
        "reward": 250
    },
    {
        "q": "How many sides does a hexagon have?",
        "options": ["5", "6", "7", "8"],
        "answer": 1,
        "reward": 200
    },
    {
        "q": "What year was Discord officially released?",
        "options": ["2013", "2015", "2017", "2019"],
        "answer": 1,
        "reward": 300
    },
    {
        "q": "Which planet in our solar system is known as the Red Planet?",
        "options": ["Venus", "Jupiter", "Mars", "Saturn"],
        "answer": 2,
        "reward": 200
    },
    {
        "q": "In gaming, what does 'NPC' stand for?",
        "options": ["Non-Playable Character", "New Player Character", "Next Level Player", "Non-Point Character"],
        "answer": 0,
        "reward": 150
    }
]


class TriviaView(discord.ui.View):
    def __init__(self, cog, ctx, question_data):
        super().__init__(timeout=30)
        self.cog = cog
        self.ctx = ctx
        self.qdata = question_data
        self.answered = False

        labels = ["A", "B", "C", "D"]
        for idx, option in enumerate(question_data["options"]):
            button = discord.ui.Button(
                label=f"{labels[idx]}: {option}",
                style=discord.ButtonStyle.primary,
                custom_id=str(idx)
            )
            button.callback = self.make_callback(idx)
            self.add_item(button)

    def make_callback(self, chosen_idx):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("❌ This trivia isn't for you!", ephemeral=True)
                return

            if self.answered:
                return

            self.answered = True
            self.stop()

            correct_idx = self.qdata["answer"]

            for item in self.children:
                item.disabled = True
                if int(item.custom_id) == correct_idx:
                    item.style = discord.ButtonStyle.green
                elif int(item.custom_id) == chosen_idx:
                    item.style = discord.ButtonStyle.red

            if chosen_idx == correct_idx:
                reward = self.qdata["reward"]
                new_bal = await self.cog.db.add_balance(self.ctx.guild.id, self.ctx.author.id, reward)
                embed = discord.Embed(
                    title="🎉 Correct Answer!",
                    description=(
                        f"**Question:** {self.qdata['q']}\n"
                        f"✅ You picked: **{self.qdata['options'][chosen_idx]}**\n\n"
                        f"💰 Earned: **+{reward:,} coins**\n"
                        f"💳 Balance: **{new_bal:,}**"
                    ),
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="❌ Wrong Answer!",
                    description=(
                        f"**Question:** {self.qdata['q']}\n"
                        f"❌ You picked: {self.qdata['options'][chosen_idx]}\n"
                        f"✅ Correct answer: **{self.qdata['options'][correct_idx]}**"
                    ),
                    color=discord.Color.red()
                )

            await interaction.response.edit_message(embed=embed, view=self)

        return callback


class RPSView(discord.ui.View):
    def __init__(self, cog, ctx, bet: int = 0):
        super().__init__(timeout=30)
        self.cog = cog
        self.ctx = ctx
        self.bet = bet

    @discord.ui.button(label="Rock 🪨", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play_game(interaction, "rock")

    @discord.ui.button(label="Paper 📄", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play_game(interaction, "paper")

    @discord.ui.button(label="Scissors ✂️", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play_game(interaction, "scissors")

    async def play_game(self, interaction: discord.Interaction, player_choice: str):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return

        self.stop()
        for item in self.children:
            item.disabled = True

        choices = ["rock", "paper", "scissors"]
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        bot_choice = random.choice(choices)

        if player_choice == bot_choice:
            result = "tie"
        elif (
            (player_choice == "rock" and bot_choice == "scissors") or
            (player_choice == "paper" and bot_choice == "rock") or
            (player_choice == "scissors" and bot_choice == "paper")
        ):
            result = "win"
        else:
            result = "loss"

        if self.bet > 0:
            if result == "win":
                winnings = self.bet * 2
                new_bal = await self.cog.db.add_balance(self.ctx.guild.id, self.ctx.author.id, winnings)
                desc = f"🎉 **You won {self.bet:,} coins!**\n💰 Balance: **{new_bal:,}**"
                color = discord.Color.green()
            elif result == "tie":
                new_bal = await self.cog.db.add_balance(self.ctx.guild.id, self.ctx.author.id, self.bet)
                desc = f"👔 **It's a tie!** Bet returned.\n💰 Balance: **{new_bal:,}**"
                color = COLOR_GOLD
            else:
                new_bal = (await self.cog.db.get_user(self.ctx.guild.id, self.ctx.author.id))["balance"]
                desc = f"❌ **You lost {self.bet:,} coins.**\n💰 Balance: **{new_bal:,}**"
                color = discord.Color.red()
        else:
            if result == "win":
                desc = "🎉 **You won!** Good job!"
                color = discord.Color.green()
            elif result == "tie":
                desc = "👔 **It's a tie!**"
                color = COLOR_GOLD
            else:
                desc = "❌ **You lost!**"
                color = discord.Color.red()

        embed = discord.Embed(
            title="🎮 Rock, Paper, Scissors",
            description=(
                f"You chose: {emojis[player_choice]} **{player_choice.capitalize()}**\n"
                f"Bot chose: {emojis[bot_choice]} **{bot_choice.capitalize()}**\n\n"
                f"{desc}"
            ),
            color=color
        )
        await interaction.response.edit_message(embed=embed, view=self)


class BlackjackView(discord.ui.View):
    def __init__(self, cog, ctx, bet, player_hand, dealer_hand, deck):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.bet = bet
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.deck = deck

    def calc_score(self, hand):
        score = 0
        aces = 0
        for rank, suit in hand:
            if rank in ["J", "Q", "K"]:
                score += 10
            elif rank == "A":
                aces += 1
                score += 11
            else:
                score += int(rank)
        while score > 21 and aces:
            score -= 10
            aces -= 1
        return score

    def render_hand(self, hand, hide_dealer=False):
        if hide_dealer:
            return f"`{hand[0][0]}{hand[0][1]}` `🂠`"
        return " ".join([f"`{rank}{suit}`" for rank, suit in hand])

    @discord.ui.button(label="Hit 🃏", style=discord.ButtonStyle.green)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return

        self.player_hand.append(self.deck.pop())
        p_score = self.calc_score(self.player_hand)

        if p_score > 21:
            self.stop()
            for item in self.children:
                item.disabled = True

            new_bal = (await self.cog.db.get_user(self.ctx.guild.id, self.ctx.author.id))["balance"]
            embed = discord.Embed(
                title="🃏 Blackjack - BUST!",
                description=(
                    f"**Dealer's Hand:** {self.render_hand(self.dealer_hand)} ({self.calc_score(self.dealer_hand)})\n"
                    f"**Your Hand:** {self.render_hand(self.player_hand)} (**{p_score}**)\n\n"
                    f"💥 You busted and lost **{self.bet:,} coins**!\n"
                    f"💰 Balance: **{new_bal:,}**"
                ),
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return

        embed = discord.Embed(
            title="🃏 Blackjack",
            description=(
                f"**Dealer's Hand:** {self.render_hand(self.dealer_hand, hide_dealer=True)}\n"
                f"**Your Hand:** {self.render_hand(self.player_hand)} (**{p_score}**)\n\n"
                f"Choose your action below!"
            ),
            color=COLOR_PRIMARY
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand 🛑", style=discord.ButtonStyle.red)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return

        self.stop()
        for item in self.children:
            item.disabled = True

        p_score = self.calc_score(self.player_hand)
        d_score = self.calc_score(self.dealer_hand)

        while d_score < 17:
            self.dealer_hand.append(self.deck.pop())
            d_score = self.calc_score(self.dealer_hand)

        if d_score > 21 or p_score > d_score:
            winnings = self.bet * 2
            new_bal = await self.cog.db.add_balance(self.ctx.guild.id, self.ctx.author.id, winnings)
            embed = discord.Embed(
                title="🃏 Blackjack - WIN!",
                description=(
                    f"**Dealer's Hand:** {self.render_hand(self.dealer_hand)} ({d_score})\n"
                    f"**Your Hand:** {self.render_hand(self.player_hand)} ({p_score})\n\n"
                    f"🎉 You won **{self.bet:,} coins**!\n"
                    f"💰 Balance: **{new_bal:,}**"
                ),
                color=discord.Color.green()
            )
        elif p_score == d_score:
            new_bal = await self.cog.db.add_balance(self.ctx.guild.id, self.ctx.author.id, self.bet)
            embed = discord.Embed(
                title="🃏 Blackjack - PUSH!",
                description=(
                    f"**Dealer's Hand:** {self.render_hand(self.dealer_hand)} ({d_score})\n"
                    f"**Your Hand:** {self.render_hand(self.player_hand)} ({p_score})\n\n"
                    f"👔 It's a tie! Your bet was returned.\n"
                    f"💰 Balance: **{new_bal:,}**"
                ),
                color=COLOR_GOLD
            )
        else:
            new_bal = (await self.cog.db.get_user(self.ctx.guild.id, self.ctx.author.id))["balance"]
            embed = discord.Embed(
                title="🃏 Blackjack - LOSS!",
                description=(
                    f"**Dealer's Hand:** {self.render_hand(self.dealer_hand)} ({d_score})\n"
                    f"**Your Hand:** {self.render_hand(self.player_hand)} ({p_score})\n\n"
                    f"❌ Dealer won! You lost **{self.bet:,} coins**.\n"
                    f"💰 Balance: **{new_bal:,}**"
                ),
                color=discord.Color.red()
            )

        await interaction.response.edit_message(embed=embed, view=self)


class GamesHubView(discord.ui.View):
    """Interactive ECLIPSE Game Center."""

    def __init__(self, *, author_id=None, timeout=300):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.game_select = discord.ui.Select(
            placeholder="୨୧  Choose a game · view its rules",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Trivia", value="trivia", emoji="🧠", description="Questions · speed · rewards"),
                discord.SelectOption(label="Rock Paper Scissors", value="rps", emoji="🪨", description="Classic duel · wager"),
                discord.SelectOption(label="Roll", value="roll", emoji="🎲", description="Risk · roll · payout"),
                discord.SelectOption(label="Guess", value="guess", emoji="🔢", description="Hidden number · 5×"),
                discord.SelectOption(label="Coinflip", value="coinflip", emoji="🪙", description="Heads or tails · 2×"),
                discord.SelectOption(label="Slots", value="slots", emoji="🎰", description="Reels · symbols · jackpot"),
                discord.SelectOption(label="Blackjack", value="blackjack", emoji="🃏", description="Beat the dealer"),
                discord.SelectOption(label="8-Ball", value="8ball", emoji="🎱", description="Ask the oracle"),
                discord.SelectOption(label="Tic-Tac-Toe", value="ttt", emoji="⭕", description="Player vs player"),
                discord.SelectOption(label="Connect Four", value="connect4", emoji="🔴", description="Four in a row"),
                discord.SelectOption(label="Dice Battle", value="dicebattle", emoji="⚔️", description="Dice duel · wager"),
            ],
        )
        self.game_select.callback = self._select_game
        self.add_item(self.game_select)

    async def _guard(self, interaction):
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This Game Center is locked to its creator.",
                ephemeral=True,
            )
            return False
        return True

    async def _select_game(self, interaction):
        if not await self._guard(interaction):
            return
        game = self.game_select.values[0]
        pages = {
            "trivia": ("🧠  TRIVIA", COLOR_PRIMARY, "!trivia", "Answer a multiple-choice question before the timer expires. Correct answers earn coins.", "① Start !trivia\n② Read the question\n③ Tap A / B / C / D\n④ Collect the reward", "Read carefully before locking your answer."),
            "rps": ("🪨  ROCK · PAPER · SCISSORS", COLOR_PRIMARY, "!rps  or  !rps rock 1000", "Rock beats Scissors. Scissors beats Paper. Paper beats Rock. Winning wagers pay 2×; ties return the wager.", "① Start the button game\n② Choose your move\n③ Add a wager if desired\n④ Collect your result", "Use !rps for the interactive version."),
            "roll": ("🎲  ROLL", COLOR_PRIMARY, "!roll 1000  or  !roll 100 1000", "Roll the die and reach the current winning threshold.", "① Choose your wager\n② Optionally choose die sides\n③ Roll\n④ Check the result", "The two-number form lets you choose the sides."),
            "guess": ("🔢  GUESS", COLOR_PRIMARY, "!guess 7 1000", "Choose a number from 1–10 and wager on it. Hit the hidden number for the 5× payout.", "① Pick 1–10\n② Enter your wager\n③ Submit\n④ Hit the number", "One exact number. Ten possibilities. 5× if you nail it."),
            "coinflip": ("🪙  COINFLIP", COLOR_PRIMARY, "!coinflip heads 1000", "Call Heads or Tails. Correct calls pay 2× the wager.", "① Choose Heads / Tails\n② Place your wager\n③ Flip\n④ Collect the result", "Simple 50/50 risk."),
            "slots": ("🎰  SLOTS", COLOR_GOLD, "!slots 1000", "Spin three reels. Matching symbols determine your payout.", "① Choose your wager\n② Spin\n③ Watch the reels\n④ Match symbols for payout", "Three matching symbols are the dream."),
            "blackjack": ("🃏  BLACKJACK", COLOR_GOLD, "!blackjack 1000", "Get closer to 21 than the dealer without going over. Use Hit to draw or Stand to stop.", "① Place your wager\n② Receive cards\n③ Hit or Stand\n④ Beat the dealer", "21 is the ceiling. Going over means bust."),
            "8ball": ("🎱  MAGIC 8-BALL", COLOR_PRIMARY, "!8ball Will I win?", "Ask the ECLIPSE oracle a question. No wager required.", "① Ask a question\n② Send it to the 8-Ball\n③ Read the oracle\n④ Decide whether you believe it", "Best for yes/no-style questions."),
            "ttt": ("⭕  TIC · TAC · TOE", COLOR_GOLD, "!ttt @player  or  !ttt @player 1000", "Two players take turns placing X and O. Get three in a row. A draw returns both wagers.", "① Challenge a player\n② Choose moves\n③ Block their line\n④ Make three in a row", "Think ahead. The center is valuable."),
            "connect4": ("🔴  CONNECT FOUR", COLOR_GOLD, "!connect4 @player  or  !connect4 @player 1000", "Drop pieces into seven columns. Connect four horizontally, vertically, or diagonally.", "① Challenge a player\n② Choose a column\n③ Build your line\n④ Connect four", "Create threats in more than one direction."),
            "dicebattle": ("⚔️  DICE BATTLE", COLOR_GOLD, "!dicebattle @player  or  !dicebattle @player 1000", "Both players roll. The higher roll wins the wager. A tie returns both wagers.", "① Challenge a player\n② Set the wager\n③ Both roll\n④ Highest roll wins", "Pure dice luck. Keep the wager sensible."),
        }
        title, color, command, rules, steps, tip = pages[game]
        embed = discord.Embed(
            title=f"╭─── {title} ───╮",
            description=f"**HOW TO PLAY**\n{rules}\n\n**COMMAND**\n{command}\n\n**PLAY FLOW**\n{steps}\n\n**୨୧ TIP**\n{tip}",
            color=color,
        )
        embed.add_field(name="◈ STATUS", value="Ready to play", inline=True)
        embed.add_field(name="◈ WAGER CAP", value="1,000,000 coins", inline=True)
        embed.set_footer(text="ECLIPSE GAME CENTER · Select a game above")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Home", emoji="🏠", style=discord.ButtonStyle.primary)
    async def game_list(self, interaction, button):
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(embed=build_games_home_embed(), view=self)

    @discord.ui.button(label="Arcade", emoji="⚔️", style=discord.ButtonStyle.secondary)
    async def arcade(self, interaction, button):
        if not await self._guard(interaction):
            return
        embed = discord.Embed(
            title="╭─── ⚔️  ECLIPSE ARCADE ───╮",
            description=(
                "**MULTIPLAYER DISTRICT**\n"
                "DUEL  ·  WAGER  ·  WIN\n\n"
                "**⚔️ DUELS**\n"
                "!ttt @player [bet]  ·  Tic-Tac-Toe\n"
                "!connect4 @player [bet]  ·  Connect Four\n"
                "!dicebattle @player [bet]  ·  Dice Battle\n\n"
                "**🏆 PROGRESSION**\n"
                "!arcadeprofile  ·  Personal record\n"
                "!gamestats  ·  Detailed statistics\n"
                "!gameleaderboard <game>  ·  Leaderboard\n"
                "!season  ·  Current season\n"
                "!dailies  ·  Daily challenge\n"
                "!claimdaily  ·  Claim reward\n\n"
                "**👑 TOURNAMENTS**\n"
                "!tournament  ·  Tournament hub\n\n"
                "୨୧ WAGER LIMIT: 1,000,000 coins"
            ),
            color=COLOR_GOLD,
        )
        embed.set_footer(text="ECLIPSE · MULTIPLAYER ARCADE")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="How to Play", emoji="❔", style=discord.ButtonStyle.success)
    async def how_it_works(self, interaction, button):
        if not await self._guard(interaction):
            return
        embed = discord.Embed(
            title="╭─── ❔  HOW TO PLAY ───╮",
            description=(
                "**① CHOOSE**\nOpen the game menu and select a title to see its command and rules.\n\n"
                "**② WAGER**\nOnly games that display a wager accept coins. Multiplayer wagers cap at 1,000,000.\n\n"
                "**③ PLAY**\nFollow the command or use the interactive controls provided by the game.\n\n"
                "**④ WIN**\nPayouts depend on the individual game's rules. Ties return wagers where supported.\n\n"
                "**⑤ PROGRESS**\nUse Arcade for stats, leaderboards, seasons, dailies and tournaments.\n\n"
                "୨୧ NEW HERE? Start with !games, choose a game, then follow its PLAY FLOW."
            ),
            color=COLOR_PRIMARY,
        )
        embed.set_footer(text="ECLIPSE · PLAY FAIR · PLAY SMART")
        await interaction.response.edit_message(embed=embed, view=self)


def build_games_home_embed():
    embed = discord.Embed(
        title="╭─── 🎮  E C L I P S E ───╮",
        description=(
            "             G A M E   C E N T E R\n"
            "       ─────────────────────\n"
            "          PLAY  ·  RISK  ·  WIN\n\n"
            "**୨୧  SOLO CHAMBER**\n"
            "🧠 Trivia · 🪨 RPS · 🎲 Roll · 🔢 Guess\n"
            "🪙 Coinflip · 🎰 Slots · 🃏 Blackjack · 🎱 8-Ball\n\n"
            "**⚔️  ARCADE DISTRICT**\n"
            "⭕ Tic-Tac-Toe · 🔴 Connect Four · ⚔️ Dice Battle\n\n"
            "**🏆  ECLIPSE PROGRESSION**\n"
            "!arcadeprofile · !gamestats · !gameleaderboard <game>\n"
            "!season · !dailies · !claimdaily · !tournament\n\n"
            "╰──────────────୨୧──────────────╯\n"
            "**11 GAMES** · **1,000,000 MAX WAGER**\n"
            "Use the menu above to open a game's HOW TO PLAY card."
        ),
        color=COLOR_PRIMARY,
    )
    embed.add_field(name="🎯 QUICK START", value="!trivia · !rps · !slots · !blackjack", inline=False)
    embed.set_footer(text="ECLIPSE GAME CENTER · Choose a game from the menu")
    return embed


class Games(commands.Cog):
    """Interactive mini-games and gambling hub."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

        # Setup AI client for intelligent 8ball answers if API key exists
        self.ai_client = None
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if HAS_GENAI and api_key:
            self.ai_client = genai.Client(api_key=api_key)

    @commands.command(name="games")
    async def games(self, ctx):
        """Open the interactive ECLIPSE game center."""
        await ctx.send(
            embed=build_games_home_embed(),
            view=GamesHubView(author_id=ctx.author.id),
        )

    @commands.command(name="trivia")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def trivia(self, ctx):
        """Play a random trivia question for coins."""
        qdata = random.choice(TRIVIA_QUESTIONS)
        view = TriviaView(self, ctx, qdata)

        embed = discord.Embed(
            title="🧠 Trivia Challenge",
            description=f"**{qdata['q']}**\n\n*Select your answer below within 30 seconds!*",
            color=COLOR_PRIMARY
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="rps")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def rps(self, ctx, choice: str = None, bet: int = 0):
        """Play Rock Paper Scissors. Usage: !rps [rock/paper/scissors] [bet]"""
        if choice and choice.isdigit() and bet == 0:
            bet = int(choice)
            choice = None

        if bet < 0:
            await ctx.send("❌ Bet cannot be negative.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Maximum bet is **{MAX_BET:,} coins**.")
            return

        if bet > 0:
            user = await self.db.get_user(ctx.guild.id, ctx.author.id)
            if user["balance"] < bet:
                await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
                return
            ok, _, _ = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, bet)
            if not ok:
                await ctx.send("💸 Your balance changed before the wager could be placed.")
                return

        view = RPSView(self, ctx, bet)

        if choice and choice.lower() in ["rock", "paper", "scissors"]:
            choices = ["rock", "paper", "scissors"]
            emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
            player_choice = choice.lower()
            bot_choice = random.choice(choices)

            if player_choice == bot_choice:
                result = "tie"
            elif (
                (player_choice == "rock" and bot_choice == "scissors") or
                (player_choice == "paper" and bot_choice == "rock") or
                (player_choice == "scissors" and bot_choice == "paper")
            ):
                result = "win"
            else:
                result = "loss"

            if bet > 0:
                if result == "win":
                    winnings = bet * 2
                    new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
                    desc = f"🎉 **You won {bet:,} coins!**\n💰 Balance: **{new_bal:,}**"
                    color = discord.Color.green()
                elif result == "tie":
                    new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, bet)
                    desc = f"👔 **It's a tie!** Bet returned.\n💰 Balance: **{new_bal:,}**"
                    color = COLOR_GOLD
                else:
                    new_bal = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
                    desc = f"❌ **You lost {bet:,} coins.**\n💰 Balance: **{new_bal:,}**"
                    color = discord.Color.red()
            else:
                if result == "win":
                    desc = "🎉 **You won!** Good job!"
                    color = discord.Color.green()
                elif result == "tie":
                    desc = "👔 **It's a tie!**"
                    color = COLOR_GOLD
                else:
                    desc = "❌ **You lost!**"
                    color = discord.Color.red()

            embed = discord.Embed(
                title="🎮 Rock, Paper, Scissors",
                description=(
                    f"You chose: {emojis[player_choice]} **{player_choice.capitalize()}**\n"
                    f"Bot chose: {emojis[bot_choice]} **{bot_choice.capitalize()}**\n\n"
                    f"{desc}"
                ),
                color=color
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="🎮 Rock, Paper, Scissors",
                description=f"Choose your move below! {'(Bet: ' + f'{bet:,} coins)' if bet > 0 else ''}",
                color=COLOR_PRIMARY
            )
            await ctx.send(embed=embed, view=view)

    @commands.command(name="roll", aliases=["dice"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def roll(self, ctx, arg1: int = 100, arg2: int = None):
        """Roll a die! Usage: !roll <bet> OR !roll <sides> <bet>"""
        sides = 100
        if arg2 is not None:
            sides = arg1
            bet = arg2
        else:
            bet = arg1

        if sides < 2:
            await ctx.send("❌ Dice sides must be at least 2.")
            return
        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Maximum bet is **{MAX_BET:,} coins**.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        ok, _, _ = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, bet)
        if not ok:
            await ctx.send("💸 Your balance changed before the wager could be placed.")
            return

        embed = discord.Embed(
            title="🎲 Dice Roll",
            description="Rolling the dice... 🎲",
            color=COLOR_PRIMARY
        )
        msg = await ctx.send(embed=embed)

        for _ in range(2):
            await asyncio.sleep(0.5)
            embed.description = f"Rolling the dice... **{random.randint(1, sides)}** 🎲"
            await msg.edit(embed=embed)

        await asyncio.sleep(0.6)
        roll_val = random.randint(1, sides)

        if roll_val >= int(sides * 0.55):
            winnings = bet * 2
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
            embed.color = discord.Color.green()
            embed.description = (
                f"🎲 You rolled a **{roll_val}** out of {sides}!\n"
                f"🎉 You won **{bet:,} coins**!\n"
                f"💰 Balance: **{new_bal:,}**"
            )
        else:
            new_bal = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            embed.color = discord.Color.red()
            embed.description = (
                f"🎲 You rolled a **{roll_val}** out of {sides}!\n"
                f"❌ You lost **{bet:,} coins**.\n"
                f"💰 Balance: **{new_bal:,}**"
            )

        await msg.edit(embed=embed)

    @commands.command(name="guess")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def guess(self, ctx, number: int, bet: int = 100):
        """Guess secret number between 1 and 10! Usage: !guess <1-10> [bet]"""
        if number < 1 or number > 10:
            await ctx.send("❌ Guess must be between 1 and 10.")
            return

        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Maximum bet is **{MAX_BET:,} coins**.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        ok, _, _ = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, bet)
        if not ok:
            await ctx.send("💸 Your balance changed before the wager could be placed.")
            return

        secret = random.randint(1, 10)

        embed = discord.Embed(
            title="🔢 Guess the Number",
            description=f"Picking a secret number between 1 and 10...",
            color=COLOR_PRIMARY
        )
        msg = await ctx.send(embed=embed)

        await asyncio.sleep(1.2)

        if number == secret:
            winnings = bet * 5
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
            embed.color = discord.Color.green()
            embed.description = (
                f"🎯 **EXACT MATCH!** The number was **{secret}**!\n"
                f"🎉 You won **{winnings:,} coins** (5x Multiplier)!\n"
                f"💰 Balance: **{new_bal:,}**"
            )
        else:
            new_bal = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            embed.color = discord.Color.red()
            embed.description = (
                f"❌ Wrong! The secret number was **{secret}** (You guessed {number}).\n"
                f"💸 You lost **{bet:,} coins**.\n"
                f"💰 Balance: **{new_bal:,}**"
            )

        await msg.edit(embed=embed)

    @commands.command(name="coinflip", aliases=["cf"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def coinflip(self, ctx, arg1: str, arg2: str):
        """Flip a coin! Usage: !coinflip <heads/tails> <bet>"""
        bet, choice = None, None

        if arg1.isdigit():
            bet = int(arg1)
            choice = arg2.lower()
        elif arg2.isdigit():
            bet = int(arg2)
            choice = arg1.lower()
        else:
            await ctx.send("❌ Usage: `!coinflip <bet> <heads/tails>`")
            return

        if choice not in ["heads", "tails", "h", "t"]:
            await ctx.send("❌ Choose either `heads` or `tails`.")
            return

        choice = "heads" if choice in ["heads", "h"] else "tails"

        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Maximum bet is **{MAX_BET:,} coins**.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        ok, _, _ = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, bet)
        if not ok:
            await ctx.send("💸 Your balance changed before the wager could be placed.")
            return

        embed = discord.Embed(
            title="🪙 Coinflip",
            description="Flipping coin... 🟡",
            color=COLOR_PRIMARY
        )
        msg = await ctx.send(embed=embed)

        await asyncio.sleep(0.6)
        embed.description = "Flipping coin... 🪙"
        await msg.edit(embed=embed)

        await asyncio.sleep(0.6)
        outcome = random.choice(["heads", "tails"])

        if outcome == choice:
            winnings = bet * 2
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
            embed.color = discord.Color.green()
            embed.description = (
                f"🪙 It landed on **{outcome.capitalize()}**!\n"
                f"🎉 You won **{bet:,} coins**!\n"
                f"💰 Balance: **{new_bal:,}**"
            )
        else:
            new_bal = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            embed.color = discord.Color.red()
            embed.description = (
                f"🪙 It landed on **{outcome.capitalize()}**!\n"
                f"❌ You lost **{bet:,} coins**.\n"
                f"💰 Balance: **{new_bal:,}**"
            )

        await msg.edit(embed=embed)

    @commands.command(name="slots")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def slots(self, ctx, bet: int):
        """Play slot machine! Usage: !slots <bet>"""
        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Maximum bet is **{MAX_BET:,} coins**.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        symbols = ["🍋", "🍒", "🍇", "🔔", "💎", "7️⃣"]

        ok, _, _ = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, bet)
        if not ok:
            await ctx.send("💸 Your balance changed before the wager could be placed.")
            return

        embed = discord.Embed(
            title="🎰 Slot Machine",
            description=f"**[ 🎰 | 🎰 | 🎰 ]**\n\n*Spinning reels...*",
            color=COLOR_PRIMARY
        )
        msg = await ctx.send(embed=embed)

        for _ in range(3):
            await asyncio.sleep(0.6)
            r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
            embed.description = f"**[ {r1} | {r2} | {r3} ]**\n\n*Spinning reels...*"
            await msg.edit(embed=embed)

        r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        await asyncio.sleep(0.7)

        if r1 == r2 == r3:
            multiplier = 5 if r1 in ["💎", "7️⃣"] else 3
            winnings = bet * multiplier
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
            embed.color = discord.Color.gold()
            embed.description = (
                f"**[ {r1} | {r2} | {r3} ]**\n\n"
                f"🎉 **JACKPOT!** You won **{winnings:,} coins** ({multiplier}x)!\n"
                f"💰 Balance: **{new_bal:,}**"
            )
        elif r1 == r2 or r2 == r3 or r1 == r3:
            winnings = int(bet * 1.5)
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
            embed.color = discord.Color.green()
            embed.description = (
                f"**[ {r1} | {r2} | {r3} ]**\n\n"
                f"✨ **SMALL WIN!** You won **{winnings:,} coins** (1.5x)!\n"
                f"💰 Balance: **{new_bal:,}**"
            )
        else:
            new_bal = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            embed.color = discord.Color.red()
            embed.description = (
                f"**[ {r1} | {r2} | {r3} ]**\n\n"
                f"❌ You lost **{bet:,} coins**.\n"
                f"💰 Balance: **{new_bal:,}**"
            )

        await msg.edit(embed=embed)

    @commands.command(name="blackjack", aliases=["bj"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def blackjack(self, ctx, bet: int):
        """Play Blackjack! Usage: !blackjack <bet>"""
        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Maximum bet is **{MAX_BET:,} coins**.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        ok, _, _ = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, bet)
        if not ok:
            await ctx.send("💸 Your balance changed before the wager could be placed.")
            return

        suits = ["♠️", "♥️", "♦️", "♣️"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        deck = [(rank, suit) for suit in suits for rank in ranks]
        random.shuffle(deck)

        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        view = BlackjackView(self, ctx, bet, player_hand, dealer_hand, deck)
        p_score = view.calc_score(player_hand)

        if p_score == 21:
            winnings = int(bet * 2.5)
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, winnings)
            embed = discord.Embed(
                title="🃏 BLACKJACK!",
                description=(
                    f"**Dealer's Hand:** {view.render_hand(dealer_hand)}\n"
                    f"**Your Hand:** {view.render_hand(player_hand)} (**21**)\n\n"
                    f"🎉 **Natural Blackjack!** You won **{winnings:,} coins**!\n"
                    f"💰 Balance: **{new_bal:,}**"
                ),
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="🃏 Blackjack",
            description=(
                f"**Dealer's Hand:** {view.render_hand(dealer_hand, hide_dealer=True)}\n"
                f"**Your Hand:** {view.render_hand(player_hand)} (**{p_score}**)\n\n"
                f"Choose your action below!"
            ),
            color=COLOR_PRIMARY
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="8ball")
    async def eightball(self, ctx, *, question: str):
        """Ask the Magic 8-Ball a question! Gives a statement-aware prediction."""
        async with ctx.typing():
            answer = None

            # Try AI generation first for context-aware 8-ball statement responses
            if self.ai_client:
                for model_name in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]:
                    try:
                        res = await self.bot.loop.run_in_executor(
                            None,
                            lambda m=model_name: self.ai_client.models.generate_content(
                                model=m,
                                contents=f"Answer this 8ball question directly based on the statement. Give a short, mystical 1-sentence prediction with an appropriate emoji: '{question}'",
                                config=types.GenerateContentConfig(
                                    system_instruction="You are a fortune-telling Magic 8-Ball. Give concise, direct 1-sentence answers tailored specifically to what the user asks or states.",
                                    temperature=0.8,
                                    max_output_tokens=100,
                                )
                            )
                        )
                        if res and res.text:
                            answer = res.text.strip()
                            break
                    except Exception:
                        continue

            # Fallback: Deterministic seed based on question string so identical questions get consistent answers
            if not answer:
                responses = [
                    "🟢 It is certain based on what you said.",
                    "🟢 Without a doubt, the signs point to yes.",
                    "🟢 Yes, definitely looks favorable.",
                    "🟢 You may rely on it happening.",
                    "🟢 As I see it, yes.",
                    "🟡 Reply hazy, state it differently and ask again.",
                    "🟡 Ask again later when the future is clearer.",
                    "🟡 Better not tell you now.",
                    "🟡 Cannot predict this outcome yet.",
                    "🔴 Don't count on it at all.",
                    "🔴 My reply is a clear no.",
                    "🔴 My sources say no.",
                    "🔴 Very doubtful that will happen."
                ]
                # Seed with question hash for statement consistency
                q_seed = sum(ord(c) for c in question.lower())
                answer = responses[q_seed % len(responses)]

            embed = discord.Embed(
                title="🎱 Magic 8-Ball",
                description=(
                    f"**Question:** {question}\n\n"
                    f"🔮 **Answer:** {answer}"
                ),
                color=COLOR_PRIMARY
            )
            await ctx.send(embed=footer(embed, ctx))


    # ============================================================
    # ECLIPSE EXPANSION — NEW GAME HALL
    # ============================================================

    MAX_BET = 1_000_000

    async def _take_bet(self, ctx, amount):
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return False, "Invalid bet."
        if amount <= 0:
            return False, "Bet must be positive."
        if amount > self.MAX_BET:
            return False, f"Maximum bet is {self.MAX_BET:,} coins."
        ok, reason, balance = await self.db.withdraw_balance(ctx.guild.id, ctx.author.id, amount)
        if not ok:
            if reason == "balance":
                return False, f"You only have {int(balance):,} coins."
            return False, "Unable to place that wager."
        return True, amount

    async def _payout(self, ctx, bet, multiplier):
        amount = int(bet * multiplier)
        balance = await self.db.add_balance(ctx.guild.id, ctx.author.id, amount)
        return amount, balance

    async def _refund(self, ctx, bet):
        return await self.db.add_balance(ctx.guild.id, ctx.author.id, bet)

    def _game_embed(self, title, text, color=COLOR_PRIMARY):
        return discord.Embed(title=title, description=text, color=color)

    @commands.command(name="roulette", aliases=["wheel"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def roulette(self, ctx, choice: str, bet: int):
        choice = {"r": "red", "b": "black", "g": "green"}.get(choice.lower(), choice.lower())
        if choice not in {"red", "black", "green"}:
            await ctx.send("Use red, black, or green.")
            return
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        number = random.randint(0, 36)
        landed = "green" if number == 0 else ("red" if number % 2 else "black")
        multiplier = {"red": 2, "black": 2, "green": 14}[choice] if landed == choice else 0
        if multiplier:
            payout, balance = await self._payout(ctx, result, multiplier)
            text = f"Wheel: {number} · {landed.upper()}\n\n🎉 {multiplier}x payout: {payout:,} coins\nBalance: {balance:,}"
            color = discord.Color.green()
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            text = f"Wheel: {number} · {landed.upper()}\n\n❌ You lost {result:,} coins.\nBalance: {balance:,}"
            color = discord.Color.red()
        await ctx.send(embed=self._game_embed("🔴 ROULETTE", text, color))

    @commands.command(name="oddeven", aliases=["oe"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def oddeven(self, ctx, choice: str, bet: int):
        choice = choice.lower()
        if choice not in {"odd", "even"}:
            await ctx.send("Use odd or even.")
            return
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        number = random.randint(1, 100)
        actual = "odd" if number % 2 else "even"
        if actual == choice:
            payout, balance = await self._payout(ctx, result, 2)
            text = f"Rolled {number} — {actual}.\n\n🎉 Payout: {payout:,} coins\nBalance: {balance:,}"
            color = discord.Color.green()
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            text = f"Rolled {number} — {actual}.\n\n❌ Lost {result:,} coins.\nBalance: {balance:,}"
            color = discord.Color.red()
        await ctx.send(embed=self._game_embed("☯ ODD OR EVEN", text, color))

    @commands.command(name="war", aliases=["cardwar"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def war(self, ctx, bet: int):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        player = random.randint(2, 14)
        house = random.randint(2, 14)
        names = {11: "J", 12: "Q", 13: "K", 14: "A"}
        p = names.get(player, str(player))
        h = names.get(house, str(house))
        if player > house:
            payout, balance = await self._payout(ctx, result, 2)
            text = f"Your card: {p}\nHouse card: {h}\n\n🎉 You win: {payout:,} coins\nBalance: {balance:,}"
            color = discord.Color.green()
        elif player == house:
            balance = await self._refund(ctx, result)
            text = f"Your card: {p}\nHouse card: {h}\n\n👔 Tie — bet returned.\nBalance: {balance:,}"
            color = COLOR_GOLD
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            text = f"Your card: {p}\nHouse card: {h}\n\n❌ You lose.\nBalance: {balance:,}"
            color = discord.Color.red()
        await ctx.send(embed=self._game_embed("🃏 WAR", text, color))

    @commands.command(name="baccarat", aliases=["bacc"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def baccarat(self, ctx, bet: int):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return

        cog = self

        class BaccaratView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=30)
                view.done = False

            async def resolve(view, interaction, side):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This table is not yours.", ephemeral=True)
                    return
                if view.done:
                    return
                view.done = True
                view.stop()
                player = random.randint(0, 9)
                banker = random.randint(0, 9)
                winner = "tie" if player == banker else ("player" if player > banker else "banker")
                for child in view.children:
                    child.disabled = True
                if winner == side:
                    multiplier = 8 if side == "tie" else 2
                    payout, balance = await cog._payout(ctx, result, multiplier)
                    text = f"Player: {player} · Banker: {banker}\n\n🎉 {winner.upper()} wins.\nPayout: {payout:,} coins\nBalance: {balance:,}"
                    color = discord.Color.green()
                else:
                    balance = (await cog.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
                    text = f"Player: {player} · Banker: {banker}\n\n❌ Winning side: {winner.upper()}\nBalance: {balance:,}"
                    color = discord.Color.red()
                await interaction.response.edit_message(embed=cog._game_embed("🎴 BACCARAT", text, color), view=view)

            @discord.ui.button(label="Player", style=discord.ButtonStyle.primary)
            async def player(view, interaction, button):
                await view.resolve(interaction, "player")

            @discord.ui.button(label="Banker", style=discord.ButtonStyle.secondary)
            async def banker(view, interaction, button):
                await view.resolve(interaction, "banker")

            @discord.ui.button(label="Tie", style=discord.ButtonStyle.success)
            async def tie(view, interaction, button):
                await view.resolve(interaction, "tie")

        await ctx.send(
            embed=self._game_embed("🎴 BACCARAT", f"Bet: {result:,} coins\nChoose your side."),
            view=BaccaratView(),
        )

    @commands.command(name="higherlower", aliases=["hl", "highlow"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def higherlower(self, ctx, bet: int):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        cog = self
        current = random.randint(1, 100)
        multiplier = 1.5

        class HLView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=60)
                view.done = False

            async def choose(view, interaction, direction):
                nonlocal current, multiplier
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This game is not yours.", ephemeral=True)
                    return
                if view.done:
                    return
                nxt = random.randint(1, 100)
                win = nxt == current or (direction == "higher" and nxt > current) or (direction == "lower" and nxt < current)
                if not win:
                    view.done = True
                    view.stop()
                    for child in view.children:
                        child.disabled = True
                    await interaction.response.edit_message(
                        embed=cog._game_embed("🔮 HIGHER / LOWER · LOST", f"{current} → {nxt}\n\n❌ Chain broken. Bet lost.", discord.Color.red()),
                        view=view,
                    )
                    return
                current = nxt
                multiplier = min(5.0, multiplier + 0.75)
                if multiplier >= 5:
                    view.done = True
                    view.stop()
                    for child in view.children:
                        child.disabled = True
                    payout, balance = await cog._payout(ctx, result, multiplier)
                    await interaction.response.edit_message(
                        embed=cog._game_embed("🔮 HIGHER / LOWER · MAX", f"Final: {current}\n\n🎉 5x payout: {payout:,}\nBalance: {balance:,}", discord.Color.gold()),
                        view=view,
                    )
                    return
                await interaction.response.edit_message(
                    embed=cog._game_embed("🔮 HIGHER / LOWER", f"Current number: {current}\nMultiplier: {multiplier:.2f}x\n\nPredict the next number."),
                    view=view,
                )

            @discord.ui.button(label="Higher ↑", style=discord.ButtonStyle.success)
            async def higher(view, interaction, button):
                await view.choose(interaction, "higher")

            @discord.ui.button(label="Lower ↓", style=discord.ButtonStyle.danger)
            async def lower(view, interaction, button):
                await view.choose(interaction, "lower")

            @discord.ui.button(label="Cash Out 💰", style=discord.ButtonStyle.primary)
            async def cash(view, interaction, button):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This game is not yours.", ephemeral=True)
                    return
                if view.done:
                    return
                view.done = True
                view.stop()
                for child in view.children:
                    child.disabled = True
                payout, balance = await cog._payout(ctx, result, multiplier)
                await interaction.response.edit_message(
                    embed=cog._game_embed("🔮 HIGHER / LOWER · CASHED OUT", f"Final: {current}\n\n💰 {multiplier:.2f}x payout: {payout:,}\nBalance: {balance:,}", discord.Color.green()),
                    view=view,
                )

        await ctx.send(
            embed=self._game_embed("🔮 HIGHER / LOWER", f"Starting number: {current}\nMultiplier: 1.50x\nChoose higher, lower, or cash out."),
            view=HLView(),
        )

    @commands.command(name="target")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def target(self, ctx, bet: int = 100):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        target = random.randint(1, 100)
        roll = random.randint(1, 100)
        distance = abs(target - roll)
        multiplier = 10 if distance == 0 else 5 if distance <= 3 else 3 if distance <= 7 else 1.5 if distance <= 15 else 0
        if multiplier:
            payout, balance = await self._payout(ctx, result, multiplier)
            text = f"Target: {target}\nRoll: {roll}\nDistance: {distance}\n\n🎯 {multiplier}x payout: {payout:,}\nBalance: {balance:,}"
            color = discord.Color.green()
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            text = f"Target: {target}\nRoll: {roll}\nDistance: {distance}\n\n❌ Missed.\nBalance: {balance:,}"
            color = discord.Color.red()
        await ctx.send(embed=self._game_embed("🎯 TARGET", text, color))

    @commands.command(name="reaction", aliases=["reflex"])
    async def reaction(self, ctx, bet: int = 0):
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        cog = self

        class ReactionView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=12)
                view.go = False
                view.done = False

            @discord.ui.button(label="WAIT…", style=discord.ButtonStyle.secondary)
            async def press(view, interaction, button):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This reaction test is not yours.", ephemeral=True)
                    return
                if view.done:
                    return
                view.done = True
                view.stop()
                for child in view.children:
                    child.disabled = True
                if not view.go:
                    balance = await cog._balance(ctx)
                    text = f"❌ False start.\nBalance: {balance:,}"
                    color = discord.Color.red()
                else:
                    elapsed = time.monotonic() - view.go_time
                    multiplier = 3 if elapsed <= 0.35 else 2 if elapsed <= 0.65 else 1.5 if elapsed <= 1 else 0
                    if result and multiplier:
                        payout, balance = await cog._payout(ctx, result, multiplier)
                        text = f"Reaction: {elapsed:.3f}s\n\n🎉 {multiplier}x payout: {payout:,}\nBalance: {balance:,}"
                        color = discord.Color.green()
                    elif result:
                        balance = await cog._balance(ctx)
                        text = f"Reaction: {elapsed:.3f}s\n\n❌ Too slow.\nBalance: {balance:,}"
                        color = discord.Color.red()
                    else:
                        text = f"Reaction: {elapsed:.3f}s\n\n✦ Clean run."
                        color = COLOR_PRIMARY
                await interaction.response.edit_message(embed=cog._game_embed("⚡ REACTION", text, color), view=view)

        view = ReactionView()
        msg = await ctx.send(embed=self._game_embed("⚡ REACTION TEST", "Wait for GO. Do not click early."), view=view)
        await asyncio.sleep(random.uniform(1.5, 4))
        if not view.done:
            view.go = True
            view.go_time = time.monotonic()
            view.children[0].label = "GO! ⚡"
            view.children[0].style = discord.ButtonStyle.success
            try:
                await msg.edit(view=view)
            except discord.HTTPException:
                pass

    @commands.command(name="scramble", aliases=["anagram"])
    async def scramble(self, ctx, bet: int = 0):
        words = ["eclipse", "phantom", "velvet", "sovereign", "moonlight", "crystal", "seraph", "midnight", "cathedral", "nebula", "obsidian", "astral", "kingdom", "whisper", "celestial", "starlight"]
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        word = random.choice(words)
        letters = list(word)
        for _ in range(10):
            random.shuffle(letters)
            if "".join(letters) != word:
                break
        scrambled = "".join(letters)

        await ctx.send(embed=self._game_embed("🔤 WORD SCRAMBLE", f"Unscramble: {scrambled}\nYou have 20 seconds."))
        def check(message):
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id
        try:
            answer = await self.bot.wait_for("message", timeout=20, check=check)
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time. The word was {word}.")
            return
        if answer.content.strip().lower() == word:
            if result:
                payout, balance = await self._payout(ctx, result, 3)
                await ctx.send(f"🔤 Correct — {word}.\n🎉 Payout: {payout:,} · Balance: {balance:,}")
            else:
                await ctx.send(f"🔤 Correct — {word}.")
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            await ctx.send(f"❌ Wrong. The word was {word}.\nBalance: {balance:,}")

    @commands.command(name="hangman")
    async def hangman(self, ctx, bet: int = 0):
        words = ["eclipse", "phantom", "velvet", "sovereign", "moonlight", "crystal", "seraph", "midnight", "nebula", "obsidian"]
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        word = random.choice(words)
        guessed = set()
        misses = 0
        while misses < 6:
            masked = " ".join(c if c in guessed else "_" for c in word)
            if all(c in guessed for c in word):
                if result:
                    payout, balance = await self._payout(ctx, result, 4)
                    await ctx.send(f"🕯️ SOLVED — {masked}\n🎉 Payout: {payout:,} · Balance: {balance:,}")
                else:
                    await ctx.send(f"🕯️ SOLVED — {masked}")
                return
            await ctx.send(f"🕯️ HANGMAN: {masked}\nMisses: {misses}/6\nType one letter.")
            def check(message):
                return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id and len(message.content.strip()) == 1 and message.content.isalpha()
            try:
                answer = await self.bot.wait_for("message", timeout=20, check=check)
            except asyncio.TimeoutError:
                await ctx.send(f"⏰ Time. Word was {word}.")
                return
            letter = answer.content.lower()
            if letter in guessed:
                continue
            guessed.add(letter)
            if letter not in word:
                misses += 1
        balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
        await ctx.send(f"🕯️ HANGMAN LOST — word was {word}.\nBalance: {balance:,}")

    @commands.command(name="mastermind", aliases=["codebreaker"])
    async def mastermind(self, ctx, bet: int = 0):
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        code = "".join(random.sample("0123456789", 4))
        await ctx.send(embed=self._game_embed("🧩 MASTERMIND", "Break the 4-digit code. No repeated digits. You have 8 guesses.\nReply with four unique digits."))
        def check(message):
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id and message.content.isdigit() and len(message.content) == 4 and len(set(message.content)) == 4
        for attempt in range(1, 9):
            try:
                answer = await self.bot.wait_for("message", timeout=25, check=check)
            except asyncio.TimeoutError:
                await ctx.send(f"⏰ Time. Code was {code}.")
                return
            guess = answer.content
            exact = sum(a == b for a, b in zip(code, guess))
            misplaced = sum(min(code.count(d), guess.count(d)) for d in set(guess)) - exact
            if exact == 4:
                if result:
                    payout, balance = await self._payout(ctx, result, 6)
                    await ctx.send(f"🧩 CODE BROKEN in {attempt} guesses.\n🎉 Payout: {payout:,} · Balance: {balance:,}")
                else:
                    await ctx.send(f"🧩 CODE BROKEN: {code}")
                return
            await ctx.send(f"Attempt {attempt}/8 · Exact: {exact} · Misplaced: {misplaced}")
        balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
        await ctx.send(f"🧩 LOCKED — code was {code}.\nBalance: {balance:,}")

    @commands.command(name="mines")
    async def mines(self, ctx, bet: int):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        mine_positions = set(random.sample(range(21), 4))
        revealed = set()
        multiplier = 1.0
        cog = self

        class MinesView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=120)
                view.done = False
                for index in range(21):
                    button = discord.ui.Button(label="·", style=discord.ButtonStyle.secondary, row=index // 5)
                    async def reveal(interaction, idx=index, btn=button):
                        nonlocal multiplier
                        if interaction.user.id != ctx.author.id:
                            await interaction.response.send_message("❌ This minefield is not yours.", ephemeral=True)
                            return
                        if view.done or idx in revealed:
                            return
                        revealed.add(idx)
                        if idx in mine_positions:
                            view.done = True
                            view.stop()
                            for child in view.children:
                                child.disabled = True
                            for pos, child in enumerate(view.children[:21]):
                                child.label = "💣" if pos in mine_positions else ("💎" if pos in revealed else "·")
                            balance = await cog._balance(ctx)
                            await interaction.response.edit_message(
                                embed=cog._game_embed("💣 MINES · DETONATED", f"Safe tiles: {len(revealed)-1}\n\n❌ Mine hit.\nBalance: {balance:,}", discord.Color.red()),
                                view=view,
                            )
                            return
                        btn.label = "💎"
                        btn.style = discord.ButtonStyle.success
                        multiplier = min(8.0, multiplier + 0.35)
                        if len(revealed) == 17:
                            view.done = True
                            view.stop()
                            for child in view.children:
                                child.disabled = True
                            payout, balance = await cog._payout(ctx, result, multiplier)
                            text = f"All safe tiles cleared.\n\n🎉 {multiplier:.2f}x payout: {payout:,}\nBalance: {balance:,}"
                            color = discord.Color.gold()
                        else:
                            text = f"Safe tiles: {len(revealed)}/17\nMultiplier: {multiplier:.2f}x\n\nCash out before a mine."
                            color = COLOR_PRIMARY
                        await interaction.response.edit_message(embed=cog._game_embed("💣 MINES", text, color), view=view)

                    button.callback = reveal
                    view.add_item(button)

                cash = discord.ui.Button(label="Cash Out 💰", style=discord.ButtonStyle.primary, row=4)
                async def cashout(interaction):
                    if interaction.user.id != ctx.author.id:
                        await interaction.response.send_message("❌ This minefield is not yours.", ephemeral=True)
                        return
                    if view.done:
                        return
                    view.done = True
                    view.stop()
                    for child in view.children:
                        child.disabled = True
                    if not revealed:
                        balance = await cog._refund(ctx, result)
                        text = f"No tiles opened. Bet returned.\nBalance: {balance:,}"
                        color = COLOR_GOLD
                    else:
                        payout, balance = await cog._payout(ctx, result, multiplier)
                        text = f"Safe tiles: {len(revealed)}\n\n💰 {multiplier:.2f}x payout: {payout:,}\nBalance: {balance:,}"
                        color = discord.Color.green()
                    await interaction.response.edit_message(embed=cog._game_embed("💣 MINES · CASHED OUT", text, color), view=view)
                cash.callback = cashout
                view.add_item(cash)

        await ctx.send(embed=self._game_embed("💣 MINES", f"5×5 field · 4 mines · Bet: {result:,}\nReveal safe tiles to raise the multiplier."), view=MinesView())

    @commands.command(name="gamehall", aliases=["newgames", "games2"])
    async def gamehall(self, ctx):
        embed = self._game_embed(
            "୨୧ ECLIPSE · EXPANDED ARCADE ୨୧",
            "🎰 **Casino** — roulette · mines · war · baccarat · higher/lower\n"
            "🧠 **Mind** — trivia · guess · mastermind · scramble · hangman · 8ball\n"
            "⚡ **Reflex** — reaction · target\n"
            "🎮 **Classics** — rps · roll · coinflip · slots · blackjack\n\n"
            "All betting games cap individual wagers at 1,000,000 coins."
        )
        await ctx.send(embed=footer(embed, ctx))


async def setup(bot):
    await bot.add_cog(Games(bot))