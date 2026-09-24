"""
cogs/economy.py
================
Per-guild coin economy: balance, daily (with streaks), work, paying
other members, a shop, coin leaderboard, and inventory management.
"""

import asyncio
import random
import time
from typing import Union

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, COLOR_GOLD, footer, check_achievements

DAILY_AMOUNT = 200
DAILY_STREAK_BONUS = 25       # extra coins per streak day
DAILY_STREAK_CAP = 20         # streak days limit for bonus
DAILY_COOLDOWN = 24 * 3600
DAILY_GRACE = 48 * 3600       # miss daily by more than this -> streak resets

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
    """Coins, daily rewards, work, shop, and the coin leaderboard."""

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
        result = await self.db.claim_daily(ctx.guild.id, ctx.author.id, time.time(), DAILY_AMOUNT, DAILY_STREAK_BONUS, DAILY_STREAK_CAP, DAILY_COOLDOWN, DAILY_GRACE)
        if not result["ok"]:
            embed = discord.Embed(title="⏳ Already Claimed", description=f"Come back in **{fmt_time(result['remaining'])}**.", color=COLOR_PRIMARY)
            await ctx.send(embed=embed)
            return
        reward, streak, new_balance = result["reward"], result["streak"], result["balance"]
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=reward)

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
        result = await self.db.claim_work(ctx.guild.id, ctx.author.id, time.time(), WORK_MIN, WORK_MAX, WORK_COOLDOWN)
        if not result["ok"]:
            embed = discord.Embed(title="😴 You're Tired", description=f"Try again in **{fmt_time(result['remaining'])}**.", color=COLOR_PRIMARY)
            await ctx.send(embed=embed)
            return
        earned, new_balance = result["earned"], result["balance"]
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=earned)

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

        ok, reason, balance = await self.db.transfer_balance(ctx.guild.id, ctx.author.id, member.id, amount)
        if not ok:
            if reason == "balance":
                await ctx.send(f"💸 You only have **{balance:,} coins**.")
            else:
                await ctx.send("❌ Payment could not be completed.")
            return

        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, spent=amount)

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

        ok, reason, new_balance = await self.db.purchase_item(ctx.guild.id, ctx.author.id, item_id, item["price"], 1)
        if not ok:
            if reason == "balance":
                await ctx.send(f"💸 You need **{item['price']:,} coins**.")
            else:
                await ctx.send("❌ Purchase could not be completed.")
            return

        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, spent=item["price"])

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
    @commands.command(name="economyprogress", aliases=["econprogress", "wealth"])
    async def economyprogress(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, member.id)
        state = await self.db.get_economy_progression(ctx.guild.id, member.id)

        tier = int(state["tier"])
        earned = int(state["lifetime_earned"])
        spent = int(state["lifetime_spent"])
        threshold = tier * 10000
        next_tier = max(0, threshold - earned)

        embed = discord.Embed(
            title=f"💎 {member.display_name}'s Economy Progression",
            description=(
                f"**Tier {tier}**\n"
                f"Your economic activity unlocks higher progression tiers over time."
            ),
            color=COLOR_GOLD
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💰 Balance", value=f"{int(user['balance']):,}", inline=True)
        embed.add_field(name="📈 Lifetime Earned", value=f"{earned:,}", inline=True)
        embed.add_field(name="🛍️ Lifetime Spent", value=f"{spent:,}", inline=True)
        embed.add_field(
            name="🔓 Next Tier",
            value="**Max tier reached**" if tier >= 10 else f"**{next_tier:,} earned** remaining",
            inline=False
        )
        await ctx.send(embed=footer(embed, ctx))

    # ------------------------------------------------------------
    @commands.command(name="setbalance")
    @commands.is_owner()
    async def setbalance(self, ctx, member_or_amount: Union[discord.Member, int], amount: int = None):
        """Owner-only: directly set a user's balance.
        Usage: !setbalance 500000  OR  !setbalance @User 500000
        """
        if isinstance(member_or_amount, int):
            amount = member_or_amount
            member = ctx.author
        else:
            member = member_or_amount
            if amount is None:
                await ctx.send("❌ Please specify an amount: `!setbalance @User <amount>` or `!setbalance <amount>`")
                return

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
    @setbalance.error
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
