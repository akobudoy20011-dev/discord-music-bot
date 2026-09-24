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
    "cookie": {"name": "🍪 Cookie", "price": 100, "min_tier": 1, "description": "Use for an instant 150-coin treat."},
    "crown": {"name": "👑 Crown", "price": 1000, "min_tier": 1, "description": "Use for an instant 1,250-coin royal payout."},
    "diamond": {"name": "💎 Diamond", "price": 2500, "min_tier": 2, "description": "Use for an instant 3,500-coin gem payout."},
    "mystery_box": {"name": "🎁 Mystery Box", "price": 2500, "min_tier": 2, "description": "Use for a random 1,000-12,000 coin reward."},
    "trophy": {"name": "🏆 Trophy", "price": 5000, "min_tier": 3, "description": "Use for 2× your next work payout."},
    "emerald": {"name": "🟢 Emerald", "price": 10000, "min_tier": 4, "description": "Use for 1.5× your next daily payout."},
    "sapphire": {"name": "🔷 Sapphire", "price": 20000, "min_tier": 5, "description": "Use for 1.75× your next work payout."},
    "royal_seal": {"name": "🔱 Royal Seal", "price": 35000, "min_tier": 6, "description": "Use for +15% earnings for 24 hours."},
    "void_relic": {"name": "🌑 Void Relic", "price": 60000, "min_tier": 7, "description": "Use for +25% earnings for 24 hours."},
    "eclipse_core": {"name": "🌌 Eclipse Core", "price": 100000, "min_tier": 8, "description": "Use for +50% earnings for 12 hours."},
    "sovereign_crown": {"name": "👑 Sovereign Crown", "price": 175000, "min_tier": 9, "description": "Use for 2× your next daily and next work payout."},
    "eternal_treasure": {"name": "✨ Eternal Treasure", "price": 300000, "min_tier": 10, "description": "Use for a massive 25,000-100,000 coin payout."},
}

COLLECTIBLES = {
    "moon_shard": {"name": "🌙 Moon Shard", "rarity": "Rare", "value": 5000},
    "void_eye": {"name": "👁️ Void Eye", "rarity": "Epic", "value": 15000},
    "eclipse_relic": {"name": "🌌 Eclipse Relic", "rarity": "Legendary", "value": 50000},
    "sovereign_sigil": {"name": "👑 Sovereign Sigil", "rarity": "Mythic", "value": 150000},
}

ECONOMY_TIER_BONUS = 0.02

def economy_multiplier(tier):
    return 1.0 + max(0, min(9, int(tier) - 1)) * ECONOMY_TIER_BONUS


def effect_multiplier(effects, scope):
    multiplier = 1.0
    for effect in effects:
        if effect["effect_id"] in (scope, "earning_boost"):
            multiplier *= max(1.0, float(effect["multiplier"]))
    return multiplier


def effect_summary(effects):
    if not effects:
        return "None"
    labels = []
    for effect in effects:
        multiplier = float(effect["multiplier"])
        uses = int(effect["uses"])
        expires_at = effect["expires_at"]
        if uses > 0:
            labels.append(f"{effect['effect_id']} ×{uses} ({multiplier:.2f}×)")
        elif expires_at:
            remaining = max(0, int(float(expires_at) - time.time()))
            labels.append(f"{effect['effect_id']} {fmt_time(remaining)} ({multiplier:.2f}×)")
    return ", ".join(labels) if labels else "None"


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
        progression = await self.db.get_economy_progression(ctx.guild.id, ctx.author.id)
        tier = int(progression["tier"])
        tier_multiplier = economy_multiplier(tier)
        effects = await self.db.get_economy_effects(ctx.guild.id, ctx.author.id)
        boost = effect_multiplier(effects, "daily_boost")
        multiplier = tier_multiplier * boost
        result = await self.db.claim_daily(
            ctx.guild.id, ctx.author.id, time.time(),
            round(DAILY_AMOUNT * multiplier),
            round(DAILY_STREAK_BONUS * multiplier),
            DAILY_STREAK_CAP, DAILY_COOLDOWN, DAILY_GRACE
        )
        if not result["ok"]:
            embed = discord.Embed(title="⏳ Already Claimed", description=f"Come back in **{fmt_time(result['remaining'])}**.", color=COLOR_PRIMARY)
            await ctx.send(embed=embed)
            return
        reward, streak, new_balance = result["reward"], result["streak"], result["balance"]
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=reward)
        for effect in effects:
            if effect["effect_id"] in ("daily_boost", "earning_boost") and int(effect["uses"]) > 0:
                await self.db.consume_economy_effect(ctx.guild.id, ctx.author.id, effect["effect_id"])

        embed = discord.Embed(
            title="🎁 Daily Reward",
            description=(
                f"You claimed **{reward:,} coins**!\n"
                f"🔥 Streak: **{streak} day{'s' if streak != 1 else ''}**\n"
                f"💰 Balance: **{new_balance:,}**\n"
                f"💎 Economy Tier: **{tier}** ({tier_multiplier:.0%} base rate)\n"
                f"⚡ Active item boost: **{boost:.2f}×**"
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
        progression = await self.db.get_economy_progression(ctx.guild.id, ctx.author.id)
        tier = int(progression["tier"])
        tier_multiplier = economy_multiplier(tier)
        effects = await self.db.get_economy_effects(ctx.guild.id, ctx.author.id)
        boost = effect_multiplier(effects, "work_boost")
        multiplier = tier_multiplier * boost
        result = await self.db.claim_work(
            ctx.guild.id, ctx.author.id, time.time(),
            round(WORK_MIN * multiplier),
            round(WORK_MAX * multiplier), WORK_COOLDOWN
        )
        if not result["ok"]:
            embed = discord.Embed(title="😴 You're Tired", description=f"Try again in **{fmt_time(result['remaining'])}**.", color=COLOR_PRIMARY)
            await ctx.send(embed=embed)
            return
        earned, new_balance = result["earned"], result["balance"]
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=earned)
        for effect in effects:
            if effect["effect_id"] in ("work_boost", "earning_boost") and int(effect["uses"]) > 0:
                await self.db.consume_economy_effect(ctx.guild.id, ctx.author.id, effect["effect_id"])

        embed = discord.Embed(
            title="🛠️ Work Complete",
            description=(
                f"You earned **{earned} coins**!\n"
                f"💰 Balance: **{new_balance:,}**\n"
                f"💎 Economy Tier: **{tier}** ({tier_multiplier:.0%} base rate)\n"
                f"⚡ Active item boost: **{boost:.2f}×**"
            ),
            color=COLOR_GOLD
        )
        await ctx.send(embed=footer(embed, ctx))

        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        await check_achievements(self.db, ctx, ctx.author, user)

    # ------------------------------------------------------------
    @commands.command(name="bank", aliases=["vault"])
    async def bank(self, ctx):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        interest, bank = await self.db.apply_bank_interest(ctx.guild.id, ctx.author.id)
        if interest:
            await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=interest)
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        embed = discord.Embed(
            title="🏦 Economy Vault",
            description=(
                f"💰 Wallet: **{int(user['balance']):,}**\n"
                f"🏦 Vault: **{int(user['bank_balance']):,}**\n"
                f"📦 Total liquid wealth: **{int(user['balance']) + int(user['bank_balance']):,}**\n"
                f"📈 Interest: **1% every 24h**"
                + (f"\n✨ Interest credited: **+{interest:,}**" if interest else "")
            ),
            color=COLOR_GOLD
        )
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="deposit", aliases=["dep"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def deposit(self, ctx, amount: int):
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        ok, reason, _ = await self.db.bank_deposit(ctx.guild.id, ctx.author.id, amount)
        if not ok:
            user = await self.db.get_user(ctx.guild.id, ctx.author.id)
            await ctx.send(f"💸 You only have **{int(user['balance']):,}** coins available.")
            return
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, spent=amount)
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        await ctx.send(f"🏦 Deposited **{amount:,} coins**. Vault balance: **{int(user['bank_balance']):,}**.")

    @commands.command(name="withdraw", aliases=["wd"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def withdraw(self, ctx, amount: int):
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        ok, reason, _ = await self.db.bank_withdraw(ctx.guild.id, ctx.author.id, amount)
        if not ok:
            user = await self.db.get_user(ctx.guild.id, ctx.author.id)
            await ctx.send(f"🏦 Your vault only contains **{int(user['bank_balance']):,}** coins.")
            return
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=amount)
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        await ctx.send(f"💰 Withdrew **{amount:,} coins**. Wallet balance: **{int(user['balance']):,}**.")

    @commands.command(name="invest", aliases=["investment"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def invest(self, ctx, amount: int, plan: str = "stable"):
        plans = {
            "stable": (1.08, 24 * 3600, "8% after 24h"),
            "growth": (1.20, 3 * 24 * 3600, "20% after 3 days"),
            "eclipse": (1.50, 7 * 24 * 3600, "50% after 7 days"),
        }
        plan = plan.lower()
        if plan not in plans:
            await ctx.send("❌ Plans: stable, growth, eclipse.")
            return
        if amount < 1000:
            await ctx.send("❌ Minimum investment is **1,000 coins**.")
            return
        multiplier, duration, label = plans[plan]
        investment_id, reason = await self.db.create_investment(ctx.guild.id, ctx.author.id, amount, multiplier, duration)
        if investment_id is None:
            await ctx.send("💸 You don't have enough coins for that investment.")
            return
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, spent=amount)
        await ctx.send(
            f"📈 **{plan.title()} Investment #{investment_id}** created.\n"
            f"💰 Principal: **{amount:,}**\n"
            f"✨ Return: **{int(amount * multiplier):,}**\n"
            f"⏳ {label}.\n"
            f"Use !investments to track it."
        )

    @commands.command(name="investments", aliases=["portfolio"])
    async def investments(self, ctx):
        rows = await self.db.get_investments(ctx.guild.id, ctx.author.id, active_only=True)
        if not rows:
            await ctx.send("📈 You have no active investments.")
            return
        lines = []
        now = time.time()
        for row in rows[:10]:
            remaining = max(0, int(float(row["matures_at"]) - now))
            lines.append(
                f"**#{row['investment_id']}** — {int(row['principal']):,} → "
                f"**{int(int(row['principal']) * float(row['multiplier'])):,}** "
                f"({fmt_time(remaining)} remaining)"
            )
        embed = discord.Embed(title="📈 Investment Portfolio", description="\n".join(lines), color=COLOR_GOLD)
        embed.set_footer(text="Use !redeem <id> after maturity.")
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="redeem")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def redeem(self, ctx, investment_id: int):
        payout, reason = await self.db.redeem_investment(ctx.guild.id, ctx.author.id, investment_id)
        if payout is None:
            if reason == "missing":
                await ctx.send("❌ Investment not found or already redeemed.")
            else:
                await ctx.send(f"⏳ Investment matures in **{fmt_time(reason)}**.")
            return
        await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=payout)
        await ctx.send(f"✨ Investment **#{investment_id}** matured. You received **{payout:,} coins**.")

    @commands.command(name="market", aliases=["listings", "bazaar"])
    async def market(self, ctx):
        rows = await self.db.get_open_trades(ctx.guild.id, 15)
        if not rows:
            await ctx.send("🏪 The marketplace is empty.")
            return
        lines=[]
        for r in rows:
            seller=ctx.guild.get_member(int(r["seller_id"]))
            name=seller.display_name if seller else f"User {r['seller_id']}"
            lines.append(f"**#{r['trade_id']}** • {r['item_id']} ×{r['amount']} • 💰 **{int(r['price']):,}** • {name}")
        embed=discord.Embed(title="🏪 Server Marketplace",description="\n".join(lines),color=COLOR_GOLD)
        embed.set_footer(text="Buy with !marketbuy <listing id> • Sell with !sell <item> <amount> <price>")
        await ctx.send(embed=footer(embed,ctx))

    @commands.command(name="sell")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def sell(self, ctx, item_id: str, amount: int, price: int):
        item_id=item_id.lower()
        if item_id not in SHOP_ITEMS:
            await ctx.send("❌ That item cannot be traded.")
            return
        if amount <= 0 or price <= 0:
            await ctx.send("❌ Amount and price must be positive.")
            return
        trade_id, reason=await self.db.create_trade(ctx.guild.id,ctx.author.id,item_id,amount,price)
        if trade_id is None:
            await ctx.send("❌ You don't have enough of that item.")
            return
        await ctx.send(f"🏪 Listing **#{trade_id}** created: **{item_id} ×{amount}** for **{price:,} coins**.")

    @commands.command(name="marketbuy", aliases=["buylisting"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def marketbuy(self, ctx, trade_id: int):
        row, reason=await self.db.buy_trade(ctx.guild.id,ctx.author.id,trade_id)
        if row is None:
            messages={"missing":"❌ Listing unavailable or expired.","self":"❌ You can't buy your own listing.","balance":"💸 You don't have enough coins."}
            await ctx.send(messages.get(reason,"❌ Purchase failed."))
            return
        await self.db.record_economy_activity(ctx.guild.id,ctx.author.id,spent=int(row["price"]))
        await self.db.record_economy_activity(ctx.guild.id,row["seller_id"],earned=int(row["price"]))
        await ctx.send(f"🛍️ Purchased **{row['item_id']} ×{row['amount']}** for **{int(row['price']):,} coins**.")
    
    @commands.command(name="cancelmarket", aliases=["cancelsell"])
    async def cancelmarket(self, ctx, trade_id: int):
        row=await self.db.cancel_trade(ctx.guild.id,ctx.author.id,trade_id)
        if row is None:
            await ctx.send("❌ Listing not found or you don't own it.")
            return
        await ctx.send(f"↩️ Listing **#{trade_id}** cancelled. Your items were returned.")

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
        progression = await self.db.get_economy_progression(ctx.guild.id, ctx.author.id)
        tier = int(progression["tier"])
        lines = []

        for item_id, item in SHOP_ITEMS.items():
            minimum = int(item.get("min_tier", 1))
            if tier >= minimum:
                lines.append(
                    f"**{item['name']}** — 💰 {item['price']:,}\n"
                    f"{item['description']}\n"
                    f"`!buy {item_id}` • 🔓 Tier {minimum}+"
                )
            else:
                lines.append(
                    f"**{item['name']}** — 🔒 Tier {minimum}\n"
                    f"{item['description']}\n"
                    f"Unlock this item through economy progression."
                )

        embed = discord.Embed(
            title=f"🛒 Economy Shop • Tier {tier}",
            description="\n\n".join(lines),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Tier earning bonus: +{(economy_multiplier(tier) - 1):.0%}")
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="buy")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def buy(self, ctx, item_id: str):
        item_id = item_id.lower()
        item = SHOP_ITEMS.get(item_id)

        if item is None:
            await ctx.send("❌ That item doesn't exist. Use `!shop`.")
            return

        progression = await self.db.get_economy_progression(ctx.guild.id, ctx.author.id)
        tier = int(progression["tier"])
        minimum_tier = int(item.get("min_tier", 1))
        if tier < minimum_tier:
            await ctx.send(
                f"🔒 **{item['name']}** requires **Economy Tier {minimum_tier}**. "
                f"You are currently Tier **{tier}**."
            )
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
    @commands.command(name="use", aliases=["consume", "useitem"])
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def use_item(self, ctx, item_id: str):
        item_id = item_id.lower()
        item = SHOP_ITEMS.get(item_id)
        if item is None:
            await ctx.send("❌ That item doesn't exist. Use !shop.")
            return

        progression = await self.db.get_economy_progression(ctx.guild.id, ctx.author.id)
        tier = int(progression["tier"])
        minimum_tier = int(item.get("min_tier", 1))
        if tier < minimum_tier:
            await ctx.send(f"🔒 **{item['name']}** requires **Economy Tier {minimum_tier}**. You are currently Tier **{tier}**.")
            return

        remaining = await self.db.consume_item(ctx.guild.id, ctx.author.id, item_id, 1)
        if remaining is None:
            await ctx.send(f"❌ You don't have a **{item['name']}**. Check !inventory.")
            return

        now = time.time()
        reward = 0
        collectible_drop = None
        if item_id == "cookie":
            reward, message = 150, "🍪 Sweet. You received **150 coins**."
        elif item_id == "crown":
            reward, message = 1250, "👑 Royal payout: **+1,250 coins**."
        elif item_id == "diamond":
            reward, message = 3500, "💎 The diamond converts into **+3,500 coins**."
        elif item_id == "mystery_box":
            reward = random.randint(1000, 12000)
            if random.random() < 0.08:
                reward = random.randint(15000, 30000)
                message = f"🎁 **JACKPOT!** The mystery box contained **{reward:,} coins**."
            else:
                message = f"🎁 The mystery box contained **{reward:,} coins**."
            if random.random() < 0.05:
                collectible_drop = random.choices(list(COLLECTIBLES), weights=[60,25,12,3], k=1)[0]
        elif item_id == "trophy":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "work_boost", multiplier=2.0, uses=1)
            message = "🏆 Your next !work payout is now **2×**."
        elif item_id == "emerald":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "daily_boost", multiplier=1.5, uses=1)
            message = "🟢 Your next !daily payout is now **1.5×**."
        elif item_id == "sapphire":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "work_boost", multiplier=1.75, uses=1)
            message = "🔷 Your next !work payout is now **1.75×**."
        elif item_id == "royal_seal":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "earning_boost", multiplier=1.15, expires_at=now + 24 * 3600)
            message = "🔱 **Royal Seal activated:** +15% to daily/work earnings for **24 hours**."
        elif item_id == "void_relic":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "earning_boost", multiplier=1.25, expires_at=now + 24 * 3600)
            message = "🌑 **Void Relic activated:** +25% to daily/work earnings for **24 hours**."
        elif item_id == "eclipse_core":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "earning_boost", multiplier=1.50, expires_at=now + 12 * 3600)
            message = "🌌 **Eclipse Core activated:** +50% to daily/work earnings for **12 hours**."
        elif item_id == "sovereign_crown":
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "daily_boost", multiplier=2.0, uses=1)
            await self.db.add_economy_effect(ctx.guild.id, ctx.author.id, "work_boost", multiplier=2.0, uses=1)
            message = "👑 **Sovereign Crown activated:** your next !daily and next !work are both **2×**."
        else:
            reward = random.randint(25000, 100000)
            message = f"✨ Eternal Treasure opened for **+{reward:,} coins**."
            if random.random() < 0.20:
                collectible_drop = random.choices(list(COLLECTIBLES), weights=[60,25,12,3], k=1)[0]

        if collectible_drop:
            await self.db.add_item(ctx.guild.id, ctx.author.id, collectible_drop, 1)
            message += f"\n✨ **COLLECTIBLE DROP:** {COLLECTIBLES[collectible_drop]['name']} ({COLLECTIBLES[collectible_drop]['rarity']})"
        if reward:
            balance = await self.db.add_balance(ctx.guild.id, ctx.author.id, reward)
            await self.db.record_economy_activity(ctx.guild.id, ctx.author.id, earned=reward)
        else:
            balance = int((await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"])

        embed = discord.Embed(title="✨ Item Used", description=f"{message}\n💰 Balance: **{balance:,}**\n🎒 Remaining: **{remaining}**", color=COLOR_GOLD)
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="collectibles", aliases=["collection", "relics"])
    async def collectibles(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        items = await self.db.get_inventory(ctx.guild.id, member.id)
        rows = [(item_id, amount) for item_id, amount in items.items() if item_id in COLLECTIBLES]
        if not rows:
            await ctx.send(f"✨ {member.display_name}'s collection is empty.")
            return
        lines = []
        for item_id, amount in rows:
            data = COLLECTIBLES[item_id]
            lines.append(f"{data['name']} × **{amount}** • {data['rarity']} • 💰 {data['value']:,} each")
        embed = discord.Embed(title=f"✨ {member.display_name}'s Collection", description="\n".join(lines), color=COLOR_GOLD)
        embed.set_footer(text="Rare relics can be found in Mystery Boxes and Eternal Treasures.")
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="effects", aliases=["boosts"])
    async def effects(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        effects = await self.db.get_economy_effects(ctx.guild.id, member.id)
        embed = discord.Embed(title=f"⚡ {member.display_name}'s Economy Effects", description=effect_summary(effects), color=COLOR_PRIMARY)
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
        activity_score = earned // 10000 + spent // 25000
        next_activity = max(0, tier - activity_score)

        embed = discord.Embed(
            title=f"💎 {member.display_name}'s Economy Progression",
            description=(
                f"**Tier {tier}**\n"
                f"Your economic activity unlocks higher tiers and permanent earning bonuses over time."
            ),
            color=COLOR_GOLD
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💰 Balance", value=f"{int(user['balance']):,}", inline=True)
        embed.add_field(name="📈 Lifetime Earned", value=f"{earned:,}", inline=True)
        embed.add_field(name="🛍️ Lifetime Spent", value=f"{spent:,}", inline=True)
        embed.add_field(name="⚡ Earning Bonus", value=f"+{(economy_multiplier(tier) - 1):.0%}", inline=True)
        embed.add_field(name="📊 Activity Score", value=f"{activity_score:,}", inline=True)
        embed.add_field(
            name="🔓 Next Tier",
            value=(
                "**Max tier reached**"
                if tier >= 10
                else (
                    f"**{next_activity} activity point(s)** to the next tier"
                    f"\nEvery 10,000 earned or 25,000 spent grants 1 activity point."
                )
            ),
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
