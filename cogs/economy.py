"""
cogs/economy.py
================
Per-guild coin economy: balance, daily (with streaks), work, paying
other members, a shop, coin leaderboard, and animated mini-games (slots, coinflip, rob).
"""

import asyncio
import random
import time

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, COLOR_GOLD, footer, check_achievements

DAILY_AMOUNT = 200
DAILY_STREAK_BONUS = 25       # extra coins per streak day, capped below
DAILY_STREAK_CAP = 20         # streak days after which bonus stops growing
DAILY_COOLDOWN = 24 * 3600
DAILY_GRACE = 48 * 3600       # miss the daily by more than this -> streak resets

WORK_MIN = 50
WORK_MAX = 150
WORK_COOLDOWN = 3600

SHOP_ITEMS = {
    "cookie": {"name": "🍪 Cookie", "price": 100},
    "crown": {"name": "👑 Crown", "price": 1000},
    "diamond": {"name": "💎 Diamond", "price": 2500},
    "trophy": {"name": "🏆 Trophy", "price": 5000},
    "mystery_box": {"name": "🎁 Mystery Box", "price": 2500},
}


def fmt_time(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class Economy(commands.Cog):
    """Coins, daily rewards, work, shop, games, and the coin leaderboard."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------
    @commands.command(name="balance", aliases=["bal"])
    async def balance(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)

        embed = discord.Embed(
            title="💰 Balance",
            description=f"{member.mention} has **{user['balance']:,} coins**.",
            color=COLOR_GOLD
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    @commands.command(name="daily")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def daily(self, ctx):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        now = time.time()
        last = user["last_daily"]

        if last is not None and now - last < DAILY_COOLDOWN:
            remaining = DAILY_COOLDOWN - (now - last)

            embed = discord.Embed(
                title="⏳ Already Claimed",
                description=f"Come back in **{fmt_time(remaining)}**.",
                color=COLOR_PRIMARY
            )
            await ctx.send(embed=embed)
            return

        # streak logic: keep the streak if claimed within the grace
        # window, otherwise it resets to 1.
        if last is not None and now - last <= DAILY_GRACE:
            streak = min(user["daily_streak"] + 1, 9999)
        else:
            streak = 1

        bonus = min(streak, DAILY_STREAK_CAP) * DAILY_STREAK_BONUS
        reward = DAILY_AMOUNT + bonus

        new_balance = await self.db.add_balance(ctx.guild.id, ctx.author.id, reward)
        await self.db.update_user(
            ctx.guild.id, ctx.author.id,
            last_daily=now, daily_streak=streak
        )

        embed = discord.Embed(
            title="🎁 Daily Reward",
            description=(
                f"You claimed **{reward:,} coins**!\n"
                f"🔥 Streak: **{streak} day{'s' if streak != 1 else ''}**\n"
                f"💰 Balance: **{new_balance:,}**"
            ),
            color=COLOR_GOLD
        )
        await ctx.send(embed=footer(embed, ctx))

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        await check_achievements(self.db, ctx, ctx.author, user)

    # ------------------------------------------------------------
    @commands.command(name="work")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def work(self, ctx):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        now = time.time()
        last = user["last_work"]

        if last is not None and now - last < WORK_COOLDOWN:
            remaining = WORK_COOLDOWN - (now - last)

            embed = discord.Embed(
                title="😴 You're Tired",
                description=f"Try again in **{fmt_time(remaining)}**.",
                color=COLOR_PRIMARY
            )
            await ctx.send(embed=embed)
            return

        earned = random.randint(WORK_MIN, WORK_MAX)
        new_balance = await self.db.add_balance(ctx.guild.id, ctx.author.id, earned)
        await self.db.update_user(ctx.guild.id, ctx.author.id, last_work=now)

        embed = discord.Embed(
            title="🛠️ Work Complete",
            description=(
                f"You earned **{earned} coins**!\n"
                f"💰 Balance: **{new_balance:,}**"
            ),
            color=COLOR_GOLD
        )
        await ctx.send(embed=footer(embed, ctx))

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        await check_achievements(self.db, ctx, ctx.author, user)

    # ------------------------------------------------------------
    @commands.command(name="pay", aliases=["give"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pay(self, ctx, member: discord.Member, amount: int):
        if member.bot:
            await ctx.send("❌ You can't pay a bot.")
            return

        if member.id == ctx.author.id:
            await ctx.send("❌ You can't pay yourself.")
            return

        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return

        sender = await self.db.get_user(ctx.guild.id, ctx.author.id)

        if sender["balance"] < amount:
            await ctx.send(
                f"💸 You only have **{sender['balance']:,} coins**."
            )
            return

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -amount)
        await self.db.add_balance(ctx.guild.id, member.id, amount)

        embed = discord.Embed(
            title="💸 Payment Sent",
            description=(
                f"{ctx.author.mention} paid {member.mention} "
                f"**{amount:,} coins**."
            ),
            color=COLOR_GOLD
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------
    @commands.command(name="leaderboard", aliases=["lb", "rich"])
    async def leaderboard(self, ctx):
        top = await self.db.leaderboard(ctx.guild.id, order_by="balance", limit=10)

        if not top:
            await ctx.send("No economy data yet.")
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []

        for i, data in enumerate(top, start=1):
            member = ctx.guild.get_member(int(data["user_id"]))
            name = member.display_name if member else f"User {data['user_id']}"
            prefix = medals[i - 1] if i <= 3 else f"**{i}.**"
            lines.append(f"{prefix} {name} — 💰 `{data['balance']:,}`")

        embed = discord.Embed(
            title="🏆 Coin Leaderboard",
            description="\n".join(lines),
            color=COLOR_GOLD
        )
        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    @commands.command(name="shop")
    async def shop(self, ctx):
        lines = [
            f"**{item['name']}**\n`!buy {item_id}` — 💰 {item['price']:,}"
            for item_id, item in SHOP_ITEMS.items()
        ]

        embed = discord.Embed(
            title="🛒 Shop",
            description="\n\n".join(lines),
            color=discord.Color.green()
        )
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="buy")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def buy(self, ctx, item_id: str):
        item_id = item_id.lower()
        item = SHOP_ITEMS.get(item_id)

        if item is None:
            await ctx.send("❌ That item doesn't exist. Use `!shop`.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)

        if user["balance"] < item["price"]:
            await ctx.send(f"💸 You need **{item['price']:,} coins**.")
            return

        await self.db.add_balance(ctx.guild.id, ctx.author.id, -item["price"])
        await self.db.add_item(ctx.guild.id, ctx.author.id, item_id, 1)

        new_balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]

        embed = discord.Embed(
            title="🛒 Purchase Complete",
            description=(
                f"You bought **{item['name']}**!\n"
                f"💰 Balance: **{new_balance:,}**"
            ),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        items = await self.db.get_inventory(ctx.guild.id, member.id)

        if not items:
            await ctx.send(f"🎒 {member.display_name}'s inventory is empty.")
            return

        lines = [
            f"{SHOP_ITEMS[item_id]['name']} × **{amount}**"
            for item_id, amount in items.items()
            if item_id in SHOP_ITEMS
        ]

        embed = discord.Embed(
            title=f"🎒 {member.display_name}'s Inventory",
            description="\n".join(lines),
            color=COLOR_PRIMARY
        )
        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    # 🎰 ANIMATED MINI-GAMES
    # ------------------------------------------------------------

    @commands.command(name="slots")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def slots(self, ctx, bet: int):
        """Play animated slot machine with your coins!"""
        if bet <= 0:
            await ctx.send("❌ Bet must be a positive integer.")
            return

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)

        if user["balance"] < bet:
            await ctx.send(f"💸 You only have **{user['balance']:,} coins**.")
            return

        symbols = ["🍋", "🍒", "🍇", "🔔", "💎", "7️⃣"]

        # Deduct bet initial
        await self.db.add_balance(ctx.guild.id, ctx.author.id, -bet)

        embed = discord.Embed(
            title="🎰 Slot Machine",
            description=f"**[ 🎰 | 🎰 | 🎰 ]**\n\n*Spinning the reels...*",
            color=COLOR_PRIMARY
        )
        msg = await ctx.send(embed=embed)

        # Animated reel spinning sequence
        for _ in range(3):
            await asyncio.sleep(0.7)
            r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
            embed.description = f"**[ {r1} | {r2} | {r3} ]**\n\n*Reels spinning...*"
            await msg.edit(embed=embed)

        # Final Outcome
        r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        await asyncio.sleep(0.8)

        if r1 == r2 == r3:
            multiplier = 5 if r1 == "💎" or r1 == "7️⃣" else 3
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

    @commands.command(name="coinflip", aliases=["cf"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def coinflip(self, ctx, bet: int, choice: str):
        """Flip a coin! Usage: !coinflip <bet> <heads/tails>"""
        choice = choice.lower()
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

        # Animation sequence
        await asyncio.sleep(0.6)
        embed.description = "Flipping coin... 🪙"
        await msg.edit(embed=embed)

        await asyncio.sleep(0.6)
        embed.description = "Flipping coin... 🟡"
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

    @commands.command(name="rob")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def rob(self, ctx, member: discord.Member):
        """Attempt to rob coins from another user (30s cooldown)."""
        if member.bot:
            await ctx.send("❌ You can't rob a bot.")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ You can't rob yourself!")
            return

        robber = await self.db.get_user(ctx.guild.id, ctx.author.id)
        victim = await self.db.get_user(ctx.guild.id, member.id)

        if robber["balance"] < 100:
            await ctx.send("❌ You need at least **100 coins** to risk robbing someone.")
            return

        if victim["balance"] < 100:
            await ctx.send(f"❌ {member.display_name} doesn't have enough coins to rob.")
            return

        embed = discord.Embed(
            title="🥷 Attempting Heist...",
            description=f"Sneaking up on {member.mention}...",
            color=COLOR_PRIMARY
        )
        msg = await ctx.send(embed=embed)

        await asyncio.sleep(1.5)

        # 45% chance of success
        if random.random() <= 0.45:
            stolen = random.randint(int(victim["balance"] * 0.1), int(victim["balance"] * 0.35))
            await self.db.add_balance(ctx.guild.id, member.id, -stolen)
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, stolen)

            embed.color = discord.Color.green()
            embed.title = "🥷 Successful Robbery!"
            embed.description = (
                f"You snuck away with **{stolen:,} coins** from {member.mention}!\n"
                f"💰 Your Balance: **{new_bal:,}**"
            )
        else:
            fine = random.randint(50, min(200, robber["balance"]))
            new_bal = await self.db.add_balance(ctx.guild.id, ctx.author.id, -fine)

            embed.color = discord.Color.red()
            embed.title = "🚨 Caught by Police!"
            embed.description = (
                f"You were caught trying to rob {member.mention} and fined **{fine:,} coins**!\n"
                f"💰 Your Balance: **{new_bal:,}**"
            )

        await msg.edit(embed=embed)

    # ------------------------------------------------------------
    @commands.command(name="setbalance")
    @commands.is_owner()
    async def setbalance(self, ctx, member: discord.Member, amount: int):
        """Owner-only: directly set a user's balance."""

        if amount < 0:
            await ctx.send("❌ Balance cannot be negative.")
            return

        await self.db.update_user(
            ctx.guild.id,
            member.id,
            balance=amount
        )

        await ctx.send(
            f"💰 Set {member.mention}'s balance to **{amount:,} coins**."
        )

    # ------------------------------------------------------------
    @daily.error
    @work.error
    @pay.error
    @buy.error
    @slots.error
    @coinflip.error
    @rob.error
    async def on_cooldown_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Slow down — try again in {error.retry_after:.1f}s."
            )
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("❌ I couldn't find that member.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Invalid argument provided. Check numbers and inputs.")


async def setup(bot):
    await bot.add_cog(Economy(bot))
