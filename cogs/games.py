"""
cogs/games.py
=============
All mini-games. Each game that awards coins/XP goes through the same
`record_game()` helper so stats, coins, and achievements stay
consistent no matter which game was played.
"""

import asyncio
import random

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, COLOR_GOLD, footer, check_achievements


async def record_game(db, ctx, member, *, won, coins=0, xp=0):
    """Increments games/wins/balance/xp for `member` and checks achievements."""

    user = await db.get_user(ctx.guild.id, member.id)

    updates = {
        "games": user["games"] + 1,
        "wins": user["wins"] + (1 if won else 0)
    }

    await db.update_user(ctx.guild.id, member.id, **updates)

    if coins:
        await db.add_balance(ctx.guild.id, member.id, coins)

    if xp:
        await db.add_xp(ctx.guild.id, member.id, xp)

    fresh = await db.get_user(ctx.guild.id, member.id)
    await check_achievements(db, ctx, member, fresh)


class Games(commands.Cog):
    """Mini-games: dice, RPS, guessing, 8-ball, trivia, coinflip, slots, blackjack."""

    TRIVIA = [
        ("What planet is known as the Red Planet?", ["mars"]),
        ("How many bones are in an adult human body?", ["206"]),
        ("What is the largest ocean on Earth?", ["pacific", "pacific ocean"]),
        ("What gas do humans need to breathe?", ["oxygen"]),
        ("What is 12 × 12?", ["144"]),
        ("How many continents are there?", ["7", "seven"]),
        ("What is the capital of Japan?", ["tokyo"]),
    ]

    EIGHTBALL_ANSWERS = [
        "Absolutely.", "Definitely.", "Most likely.", "Yes.", "Probably.",
        "Ask me again later.", "Maybe.", "Probably not.", "No.", "Absolutely not."
    ]

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------
    @commands.command(name="games")
    async def games_menu(self, ctx):
        embed = discord.Embed(
            title="🎮 Game Center",
            description=(
                "🧠 `!trivia`\n"
                "✊ `!rps rock`\n"
                "🎲 `!roll [sides]`\n"
                "🔢 `!guess <1-10>`\n"
                "🪙 `!coinflip <heads/tails> <bet>`\n"
                "🎰 `!slots <bet>`\n"
                "🃏 `!blackjack <bet>`\n"
                "🎱 `!8ball <question>`"
            ),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed, view=GameMenuView(self))

    # ------------------------------------------------------------
    @commands.command(name="rps")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def rps(self, ctx, choice: str):
        choice = choice.lower()
        choices = ["rock", "paper", "scissors"]

        if choice not in choices:
            await ctx.send("Use `rock`, `paper`, or `scissors`.")
            return

        bot_choice = random.choice(choices)

        beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

        if choice == bot_choice:
            won, reward, result = False, 0, "🤝 **Tie!**"
        elif beats[choice] == bot_choice:
            won, reward = True, 50
            result = f"🎉 **You win!**\n💰 +{reward} coins"
        else:
            won, reward, result = False, 0, "💀 **You lose!**"

        await record_game(self.db, ctx, ctx.author, won=won, coins=reward)

        embed = discord.Embed(
            title="✊ Rock Paper Scissors",
            description=f"You: `{choice}`\nBot: `{bot_choice}`\n\n{result}",
            color=COLOR_PRIMARY
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------
    @commands.command(name="roll", aliases=["dice"])
    async def roll(self, ctx, sides: int = 6):
        if sides < 2 or sides > 1000:
            await ctx.send("🎲 Choose between 2 and 1000 sides.")
            return

        result = random.randint(1, sides)
        await ctx.send(f"🎲 {ctx.author.mention} rolled **{result}** (1-{sides})")

    # ------------------------------------------------------------
    @commands.command(name="guess")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def guess(self, ctx, number: int):
        if number < 1 or number > 10:
            await ctx.send("🔢 Choose a number from **1 to 10**.")
            return

        answer = random.randint(1, 10)
        won = number == answer
        reward = 100 if won else 0

        await record_game(self.db, ctx, ctx.author, won=won, coins=reward)

        if won:
            await ctx.send(f"🎉 **Correct!**\n💰 +{reward} coins")
        else:
            await ctx.send(f"❌ Wrong! I picked **{answer}**.")

    # ------------------------------------------------------------
    @commands.command(name="8ball", aliases=["8b"])
    async def eightball(self, ctx, *, question: str):
        embed = discord.Embed(title="🎱 Magic 8-Ball", color=discord.Color.purple())
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(
            name="Answer", value=random.choice(self.EIGHTBALL_ANSWERS), inline=False
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------
    @commands.command(name="trivia")
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def trivia(self, ctx):
        question, answers = random.choice(self.TRIVIA)

        embed = discord.Embed(
            title="🧠 Trivia", description=question, color=discord.Color.orange()
        )
        embed.set_footer(text="You have 20 seconds!")
        await ctx.send(embed=embed)

        def check(message):
            return message.channel == ctx.channel and not message.author.bot

        try:
            answer = await self.bot.wait_for("message", timeout=20, check=check)
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time's up! The answer was **{answers[0].title()}**.")
            return

        if answer.content.lower().strip() in answers:
            await record_game(
                self.db, ctx, answer.author, won=True, coins=100, xp=50
            )
            await ctx.send(
                f"🎉 {answer.author.mention} **CORRECT!**\n💰 +100 coins\n⭐ +50 XP"
            )
        else:
            await ctx.send(f"❌ Wrong! The answer was **{answers[0].title()}**.")

    # ------------------------------------------------------------
    @commands.command(name="coinflip", aliases=["cf"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def coinflip(self, ctx, side: str, bet: int):
        side = side.lower()

        if side not in ("heads", "tails"):
            await ctx.send("🪙 Choose `heads` or `tails`.")
            return

        if bet <= 0:
            await ctx.send("🪙 Bet must be positive.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)

        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        result = random.choice(("heads", "tails"))
        won = result == side
        net = bet if won else -bet

        await record_game(self.db, ctx, ctx.author, won=won, coins=net)

        emoji = "🪙"
        if won:
            await ctx.send(
                f"{emoji} It landed on **{result}** — **you win {bet:,} coins!**"
            )
        else:
            await ctx.send(
                f"{emoji} It landed on **{result}** — you lost **{bet:,} coins**."
            )

    # ------------------------------------------------------------
    SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]
    SLOT_PAYOUTS = {"7️⃣": 10, "💎": 6, "🔔": 4, "🍇": 3, "🍋": 2, "🍒": 2}

    @commands.command(name="slots", aliases=["slot"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def slots(self, ctx, bet: int):
        if bet <= 0:
            await ctx.send("🎰 Bet must be positive.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)

        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        spin = [random.choice(self.SLOT_SYMBOLS) for _ in range(3)]
        display = " | ".join(spin)

        if spin[0] == spin[1] == spin[2]:
            multiplier = self.SLOT_PAYOUTS[spin[0]]
            net = bet * multiplier
            result = f"🎉 **JACKPOT!** All three match — you win **{net:,} coins**!"
            won = True
        elif spin[0] == spin[1] or spin[1] == spin[2] or spin[0] == spin[2]:
            net = bet
            result = f"✨ Two matched — you win **{net:,} coins**!"
            won = True
        else:
            net = -bet
            result = f"💀 No match — you lost **{bet:,} coins**."
            won = False

        await record_game(self.db, ctx, ctx.author, won=won, coins=net)

        embed = discord.Embed(
            title="🎰 Slots",
            description=f"**[ {display} ]**\n\n{result}",
            color=COLOR_GOLD
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------
    @commands.command(name="blackjack", aliases=["bj"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def blackjack(self, ctx, bet: int):
        if bet <= 0:
            await ctx.send("🃏 Bet must be positive.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)

        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        def draw():
            return random.randint(1, 11)

        def hand_value(cards):
            return sum(cards)

        player = [draw(), draw()]
        dealer = [draw(), draw()]

        view = BlackjackView(ctx.author.id)

        embed = discord.Embed(
            title="🃏 Blackjack",
            description=(
                f"Your hand: {player} = **{hand_value(player)}**\n"
                f"Dealer shows: {dealer[0]}\n\n"
                f"Hit or stand? (30s)"
            ),
            color=discord.Color.dark_green()
        )
        msg = await ctx.send(embed=embed, view=view)

        while True:
            await view.wait()

            if view.timed_out or view.choice is None:
                await msg.edit(content="⏰ Timed out.", view=None)
                return

            if view.choice == "hit":
                player.append(draw())

                if hand_value(player) > 21:
                    await record_game(self.db, ctx, ctx.author, won=False, coins=-bet)
                    embed = discord.Embed(
                        title="🃏 Blackjack — Bust!",
                        description=(
                            f"Your hand: {player} = **{hand_value(player)}**\n"
                            f"💀 You busted and lost **{bet:,} coins**."
                        ),
                        color=discord.Color.red()
                    )
                    await msg.edit(embed=embed, view=None)
                    return

                view = BlackjackView(ctx.author.id)
                embed = discord.Embed(
                    title="🃏 Blackjack",
                    description=(
                        f"Your hand: {player} = **{hand_value(player)}**\n"
                        f"Dealer shows: {dealer[0]}\n\nHit or stand? (30s)"
                    ),
                    color=discord.Color.dark_green()
                )
                await msg.edit(embed=embed, view=view)
                continue

            # stand — dealer plays
            while hand_value(dealer) < 17:
                dealer.append(draw())

            player_total = hand_value(player)
            dealer_total = hand_value(dealer)

            if dealer_total > 21 or player_total > dealer_total:
                won, net = True, bet
                outcome = f"🎉 You win **{bet:,} coins**!"
            elif player_total == dealer_total:
                won, net = False, 0
                outcome = "🤝 Push — bet returned."
            else:
                won, net = False, -bet
                outcome = f"💀 You lost **{bet:,} coins**."

            await record_game(self.db, ctx, ctx.author, won=won, coins=net)

            embed = discord.Embed(
                title="🃏 Blackjack — Result",
                description=(
                    f"Your hand: {player} = **{player_total}**\n"
                    f"Dealer hand: {dealer} = **{dealer_total}**\n\n{outcome}"
                ),
                color=discord.Color.dark_green()
            )
            await msg.edit(embed=embed, view=None)
            return

    # ------------------------------------------------------------
    @rps.error
    @guess.error
    @trivia.error
    @coinflip.error
    @slots.error
    @blackjack.error
    async def on_game_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Slow down — try again in {error.retry_after:.1f}s.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ That doesn't look right — check `!help` for usage.")


class BlackjackView(discord.ui.View):
    def __init__(self, player_id):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.choice = None
        self.timed_out = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "This isn't your game!", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        self.timed_out = True
        self.stop()

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.success, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "hit"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "stand"
        await interaction.response.defer()
        self.stop()


class GameMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(label="🎲 Dice", style=discord.ButtonStyle.primary)
    async def dice_button(self, interaction: discord.Interaction, button):
        result = random.randint(1, 6)
        await interaction.response.send_message(
            f"🎲 {interaction.user.mention} rolled **{result}**!"
        )

    @discord.ui.button(label="✊ RPS", style=discord.ButtonStyle.success)
    async def rps_button(self, interaction: discord.Interaction, button):
        choice = random.choice(["rock", "paper", "scissors"])
        await interaction.response.send_message(
            f"✊ Your random opponent chose **{choice}**! "
            f"Use `!rps <choice>` to actually play for coins."
        )

    @discord.ui.button(label="🎱 8-Ball", style=discord.ButtonStyle.secondary)
    async def ball_button(self, interaction: discord.Interaction, button):
        answer = random.choice(Games.EIGHTBALL_ANSWERS)
        await interaction.response.send_message(f"🎱 **{answer}**")


async def setup(bot):
    await bot.add_cog(Games(bot))
