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
        """Displays available mini-games and rules."""
        embed = discord.Embed(
            title="🎮 Mini-Games Hub",
            description=(
                "Test your luck and skills to earn coins!\n\n"
                "🧠 `!trivia` — Answer questions for bonus coins.\n"
                "🪨 `!rps [choice] [bet]` — Play Rock, Paper, Scissors.\n"
                "🎲 `!roll <bet>` — Roll a die (55+ wins 2x).\n"
                "🔢 `!guess <1-10> <bet>` — Guess secret number (5x payout!).\n"
                "🪙 `!coinflip <heads/tails> <bet>` — Flip a coin (2x payout).\n"
                "🎰 `!slots <bet>` — Spin the slot machine reels.\n"
                "🃏 `!blackjack <bet>` — Interactive card table.\n"
                "🎱 `!8ball <question>` — Ask the mysterious magic 8-ball."
            ),
            color=COLOR_PRIMARY
        )
        await ctx.send(embed=footer(embed, ctx))

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

        if bet > 0:
            user = await self.db.get_user(ctx.guild.id, ctx.author.id)
            if user["balance"] < bet:
                await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
                return
            await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

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

        if bet <= 0:
            await ctx.send("❌ Bet/Sides must be positive.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

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

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

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

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

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

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        symbols = ["🍋", "🍒", "🍇", "🔔", "💎", "7️⃣"]

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

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

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

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


async def setup(bot):
    await bot.add_cog(Games(bot))
