"""
cogs/guilds.py
==============
Persistent server guilds, progression, guild events, bosses, raids,
guild wars, legendary equipment, and server-wide reward events.
"""

import time
import uuid

import discord
from discord.ext import commands
from rpg.equipment import equipment_stats

GUILD_XP_PER_LEVEL = 1000
MAX_GUILD_LEVEL = 20
BOSS_COST = 25000
RAID_COST = 50000
RELIC_COST = 50000

LEGENDARIES = {
    "eclipse_blade": ("⚔️ Eclipse Blade", 10),
    "void_crown": ("👑 Void Crown", 12),
    "celestial_aegis": ("🛡️ Celestial Aegis", 15),
    "sovereign_relic": ("🌌 Sovereign Relic", 20),
}


class Guilds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def _mine(self, ctx):
        return await self.db.get_user_guild(ctx.guild.id, ctx.author.id)

    async def _role(self, ctx, roles=("leader", "officer")):
        mine = await self._mine(ctx)
        if not mine:
            await ctx.send("❌ You are not in a guild.")
            return None
        if mine["role"] not in roles:
            await ctx.send("❌ You need guild officer permissions for that.")
            return None
        return mine

    async def _member(self, ctx):
        mine = await self._mine(ctx)
        if not mine:
            await ctx.send("❌ You are not in a guild. Use `!guild list` and `!guild join <id>`.")
            return None
        return mine

    def _embed(self, title, description, color=discord.Color.blurple()):
        return discord.Embed(title=title, description=description, color=color)

    @commands.group(name="guild", invoke_without_command=True)
    async def guild(self, ctx):
        mine = await self._mine(ctx)
        if not mine:
            await ctx.send(
                "୨୧ **ECLIPSE GUILDS** ୨୧\n"
                "`!guild create <name>` • create\n"
                "`!guild list` • browse guilds\n"
                "`!guild join <id>` • join\n"
                "`!guild info` • your guild\n"
                "`!guild members` • roster\n"
                "`!guild deposit <amount>` • fund treasury"
            )
            return
        await self.guild_info(ctx)

    @guild.command(name="create")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def guild_create(self, ctx, *, name: str):
        if not 3 <= len(name.strip()) <= 32:
            await ctx.send("❌ Guild names must be 3–32 characters.")
            return
        if await self._mine(ctx):
            await ctx.send("❌ You are already in a guild.")
            return
        guild_id = f"{ctx.guild.id}-{uuid.uuid4().hex[:10]}"
        result, reason = await self.db.create_guild(
            ctx.guild.id, guild_id, name.strip(), ctx.author.id
        )
        if not result:
            await ctx.send("❌ A guild with that name already exists here.")
            return
        await ctx.send(
            embed=self._embed(
                "🏰 Guild Founded",
                f"**{name.strip()}** now exists.\n"
                f"Guild ID: `{guild_id}`\n"
                f"Leader: {ctx.author.mention}\n"
                f"Level: **1**",
                discord.Color.gold(),
            )
        )

    @guild.command(name="list")
    async def guild_list(self, ctx):
        rows = await self.db.get_server_guilds(ctx.guild.id)
        if not rows:
            await ctx.send("🏰 No guilds exist in this server yet.")
            return
        lines = []
        for g in rows:
            lines.append(
                f"**{g['name']}** · Lv.{g['level']} · "
                f"💰 {int(g['treasury']):,} · `{g['guild_id']}`"
            )
        await ctx.send(embed=self._embed("🏰 Server Guilds", "\n".join(lines)))

    @guild.command(name="join")
    async def guild_join(self, ctx, guild_id: str):
        ok, reason = await self.db.join_guild(guild_id, ctx.author.id, ctx.guild.id)
        if not ok:
            messages = {
                "missing": "❌ Guild not found.",
                "member": "❌ You are already in a guild.",
            }
            await ctx.send(messages.get(reason, "❌ You cannot join that guild."))
            return
        g = await self.db.get_guild(guild_id)
        await ctx.send(f"⚔️ You joined **{g['name']}**.")

    @guild.command(name="leave")
    async def guild_leave(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        ok, reason = await self.db.leave_guild(mine["guild_id"], ctx.author.id)
        if not ok and reason == "owner":
            await ctx.send("❌ The leader cannot leave. Transfer leadership or disband the guild first.")
            return
        await ctx.send("↩️ You left the guild.")

    @guild.command(name="info")
    async def guild_info(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        g = await self.db.get_guild(mine["guild_id"])
        members = await self.db.get_guild_members(g["guild_id"], 5)
        roster = "\n".join(
            f"{'👑' if m['role']=='leader' else '🛡️' if m['role']=='officer' else '⚔️'} <@{m['user_id']}> · {int(m['contribution']):,}"
            for m in members
        ) or "No members."
        xp_to_next = max(0, int(g["level"]) * GUILD_XP_PER_LEVEL - int(g["xp"]))
        await ctx.send(
            embed=self._embed(
                f"🏰 {g['name']}",
                f"**Level {g['level']}** · XP **{int(g['xp']):,}**\n"
                f"🏦 Treasury: **{int(g['treasury']):,}**\n"
                f"📈 Next level: **{xp_to_next:,} XP**\n"
                f"✨ Guild earning bonus: **+{min(20, max(0, int(g['level'])-1))}%**\n\n"
                f"**Top Contributors**\n{roster}\n\n"
                f"ID: `{g['guild_id']}`"
            )
        )

    @guild.command(name="members")
    async def guild_members(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        rows = await self.db.get_guild_members(mine["guild_id"], 50)
        lines = [
            f"{'👑' if r['role']=='leader' else '🛡️' if r['role']=='officer' else '⚔️'} <@{r['user_id']}> — {r['role']} — {int(r['contribution']):,} contribution"
            for r in rows
        ]
        await ctx.send(embed=self._embed("⚔️ Guild Roster", "\n".join(lines) or "Empty."))

    @guild.command(name="promote")
    async def guild_promote(self, ctx, member: discord.Member, role: str = "officer"):
        mine = await self._role(ctx, ("leader",))
        if not mine:
            return
        role = role.lower()
        if role not in {"officer", "member"}:
            await ctx.send("❌ Role must be `officer` or `member`.")
            return
        if not await self.db.get_user_guild(ctx.guild.id, member.id):
            await ctx.send("❌ That member is not in your guild.")
            return
        await self.db.set_guild_role(mine["guild_id"], member.id, role)
        await ctx.send(f"🛡️ {member.mention} is now a **{role}**.")

    @guild.command(name="deposit")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def guild_deposit(self, ctx, amount: int):
        mine = await self._member(ctx)
        if not mine:
            return
        ok, reason, _ = await self.db.guild_treasury_deposit(mine["guild_id"], ctx.author.id, amount)
        if not ok:
            await ctx.send("❌ You don't have enough coins or the amount is invalid.")
            return
        g = await self.db.get_guild(mine["guild_id"])
        await ctx.send(f"🏦 Deposited **{amount:,}** into **{g['name']}**. Treasury: **{int(g['treasury']):,}**.")

    @guild.command(name="withdraw")
    async def guild_withdraw(self, ctx, amount: int):
        mine = await self._role(ctx)
        if not mine:
            return
        ok, reason, _ = await self.db.guild_treasury_withdraw(mine["guild_id"], ctx.author.id, amount)
        if not ok:
            await ctx.send("❌ Withdrawal failed. Check officer permissions and treasury balance.")
            return
        await ctx.send(f"💰 Withdrew **{amount:,}** from the guild treasury.")

    @guild.group(name="event", invoke_without_command=True)
    async def guild_event(self, ctx):
        event = await self.db.get_guild_event((await self._member(ctx) or {}).get("guild_id", ""))
        if not event:
            await ctx.send("🌍 No active guild event.")
            return
        await ctx.send(embed=self._embed(
            f"🌍 {event['title']}",
            f"{event['description']}\n\nProgress: **{event['progress']:,}/{event['target']:,}**\n"
            f"Reward: **{event['reward_coins']:,} coins + {event['reward_xp']:,} XP**"
        ))

    @guild_event.command(name="start")
    async def guild_event_start(self, ctx):
        mine = await self._role(ctx)
        if not mine:
            return
        if int(mine["level"]) < 2:
            await ctx.send("❌ Guild Level **2** required to start a guild event.")
            return
        event_id = f"event-{int(time.time())}"
        event = await self.db.create_guild_event(
            mine["guild_id"], event_id, "ECLIPSE Ascension",
            "Push the guild forward together.", 100, 2500, 750
        )
        await ctx.send(f"🌍 **{event['title']}** started. Contribute with `!guild event contribute <amount>`.")

    @guild_event.command(name="contribute")
    async def guild_event_contribute(self, ctx, amount: int = 1):
        mine = await self._member(ctx)
        if not mine:
            return
        ok, reason = await self.db.contribute_guild_event(mine["guild_id"], ctx.author.id, amount)
        if not ok:
            await ctx.send("❌ The event is inactive or you are not a guild member.")
            return
        event = await self.db.get_guild_event(mine["guild_id"])
        await ctx.send(f"🌍 Contribution added. **{event['progress']:,}/{event['target']:,}**.")
        if event["completed"]:
            await ctx.send("🎉 Guild event complete! Use `!guild event claim` to collect your contributor reward.")

    @guild_event.command(name="claim")
    async def guild_event_claim(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        reward, reason = await self.db.claim_guild_event_reward(mine["guild_id"], ctx.author.id)
        if reward is None:
            await ctx.send("❌ No claim is available.")
            return
        coins, xp = reward
        await self.db.add_balance(ctx.guild.id, ctx.author.id, coins)
        await self.db.add_xp(ctx.guild.id, ctx.author.id, xp)
        await ctx.send(f"🎁 Claimed **{coins:,} coins + {xp:,} XP**.")

    @guild.group(name="boss", invoke_without_command=True)
    async def guild_boss(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        boss = await self.db.get_guild_boss(mine["guild_id"])
        if not boss:
            await ctx.send("👹 No guild boss is active.")
            return
        await ctx.send(embed=self._embed(
            f"👹 {boss['name']}",
            f"HP: **{boss['hp']:,}/{boss['max_hp']:,}**\n"
            f"Reward: **{boss['reward_coins']:,} coins + {boss['reward_xp']:,} XP**\n"
            f"Ends: <t:{int(boss['ends_at'])}:R>"
        ))

    @guild_boss.command(name="start")
    async def guild_boss_start(self, ctx):
        mine = await self._role(ctx)
        if not mine:
            return
        if int(mine["level"]) < 3:
            await ctx.send("❌ Guild Level **3** required to awaken a guild boss.")
            return
        if not await self.db.spend_guild_treasury(mine["guild_id"], BOSS_COST):
            await ctx.send(f"❌ The treasury needs **{BOSS_COST:,}** coins.")
            return
        boss = await self.db.create_guild_boss(
            mine["guild_id"], f"boss-{int(time.time())}", "The Eclipse Warden",
            10000 + int((await self.db.get_guild(mine["guild_id"]))["level"]) * 1000,
            100, 15000, 1500, 3600
        )
        await ctx.send(f"👹 **{boss['name']}** has awakened! Attack with `!guild boss attack`.")

    @guild_boss.command(name="attack")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def guild_boss_attack(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        player = await self.db.get_rpg_player(ctx.guild.id, ctx.author.id)
        gear = await equipment_stats(self.db, ctx.guild.id, ctx.author.id)
        damage = max(25, int(player["strength"]) * 4 + int(player["level"]) * 5 + int(gear["power"]) * 3)
        ok, reason, hp = await self.db.damage_guild_boss(mine["guild_id"], ctx.author.id, damage)
        if not ok:
            await ctx.send("❌ No active boss or you are not a member.")
            return
        await ctx.send(f"⚔️ You dealt **{damage}** damage. Boss HP: **{hp:,}**.")
        if reason == "defeated":
            await ctx.send("🏆 **GUILD BOSS DEFEATED.** Contributors can claim rewards with `!guild boss claim`.")

    @guild_boss.command(name="claim")
    async def guild_boss_claim(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        reward, reason = await self.db.claim_guild_boss_reward(mine["guild_id"], ctx.author.id)
        if reward is None:
            await ctx.send("❌ No boss reward is available.")
            return
        coins, xp = reward
        await self.db.add_balance(ctx.guild.id, ctx.author.id, coins)
        await self.db.add_xp(ctx.guild.id, ctx.author.id, xp)
        await ctx.send(f"🎁 Boss reward: **{coins:,} coins + {xp:,} XP**.")

    @guild.group(name="raid", invoke_without_command=True)
    async def guild_raid(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        raid = await self.db.get_guild_raid(mine["guild_id"])
        if not raid:
            await ctx.send("⚔️ No raid is active.")
            return
        await ctx.send(embed=self._embed(
            "⚔️ Guild Raid",
            f"Boss HP: **{raid['boss_hp']:,}/{raid['max_hp']:,}**\nPhase: **{ {1:"Awakening",2:"Enraged",3:"Cataclysm"}.get(int(raid.get("phase",1)),"Awakening") }**\n"
            f"Reward: **{raid['reward_coins']:,} coins + {raid['reward_xp']:,} XP**\n"
            f"Ends: <t:{int(raid['ends_at'])}:R>"
        ))

    @guild_raid.command(name="start")
    async def guild_raid_start(self, ctx):
        mine = await self._role(ctx)
        if not mine:
            return
        if int(mine["level"]) < 5:
            await ctx.send("❌ Guild Level **5** required to launch a raid.")
            return
        if not await self.db.spend_guild_treasury(mine["guild_id"], RAID_COST):
            await ctx.send(f"❌ The treasury needs **{RAID_COST:,}** coins.")
            return
        raid_id, reason = await self.db.start_guild_raid(
            mine["guild_id"], f"eclipse_raid_{int(time.time())}",
            25000, 30000, 3000, 7200
        )
        if raid_id is None:
            await ctx.send("❌ A raid is already active.")
            return
        await ctx.send(f"⚔️ Raid **#{raid_id}** started. Attack with `!guild raid attack`.")

    @guild_raid.command(name="attack")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def guild_raid_attack(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        player = await self.db.get_rpg_player(ctx.guild.id, ctx.author.id)
        gear = await equipment_stats(self.db, ctx.guild.id, ctx.author.id)
        raid = await self.db.get_guild_raid(mine["guild_id"])
        if not raid or raid["status"]!="active":
            await ctx.send("❌ No active raid.")
            return
        phase=int(raid.get("phase",1))
        phase_names={1:"Awakening",2:"Enraged",3:"Cataclysm"}
        phase_mult={1:1.0,2:1.20,3:1.45}
        base=max(50, int(player["strength"])*6 + int(player["level"])*10 + int(gear["power"])*5)
        damage=max(50,int(base*phase_mult.get(phase,1.0)))
        ok, reason, hp = await self.db.damage_guild_raid(mine["guild_id"], ctx.author.id, damage)
        if not ok:
            await ctx.send("❌ No active raid or you are not a member.")
            return
        await ctx.send(f"⚔️ Raid **{phase_names.get(phase, 'Awakening')}**: **{damage:,}** damage · Boss HP: **{hp:,}**.")
        if reason == "completed":
            await ctx.send("🏆 **RAID CLEARED.** Contributors can claim with `!guild raid claim`.")

    @guild_raid.command(name="claim")
    async def guild_raid_claim(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        reward, reason = await self.db.claim_guild_raid_reward(mine["guild_id"], ctx.author.id)
        if reward is None:
            await ctx.send("❌ No raid reward is available.")
            return
        coins, xp = reward
        await self.db.add_balance(ctx.guild.id, ctx.author.id, coins)
        await self.db.add_xp(ctx.guild.id, ctx.author.id, xp)
        await ctx.send(f"🎁 Raid reward: **{coins:,} coins + {xp:,} XP**.")

    @guild.group(name="war", invoke_without_command=True)
    async def guild_war(self, ctx):
        await ctx.send("⚔️ `!guild war declare <guild_id>` · `strike <war_id>` · `status <war_id>` · `end <war_id>`")

    @guild_war.command(name="declare")
    async def guild_war_declare(self, ctx, opponent_guild_id: str):
        mine = await self._role(ctx)
        if not mine:
            return
        if int(mine["level"]) < 3:
            await ctx.send("❌ Guild Level **3** required to declare war.")
            return
        war_id, reason = await self.db.declare_guild_war(mine["guild_id"], opponent_guild_id)
        if war_id is None:
            await ctx.send("❌ War could not be declared.")
            return
        await ctx.send(f"⚔️ Guild war **#{war_id}** declared against `{opponent_guild_id}`.")

    @guild_war.command(name="status")
    async def guild_war_status(self, ctx, war_id: int):
        war = await self.db.get_guild_war(war_id)
        if not war:
            await ctx.send("❌ War not found.")
            return
        await ctx.send(embed=self._embed(
            f"⚔️ Guild War #{war_id}",
            f"`{war['guild_id']}`: **{war['guild_score']}**\n"
            f"`{war['opponent_guild_id']}`: **{war['opponent_score']}**\n"
            f"Ends: <t:{int(war['ends_at'])}:R>"
        ))

    @guild_war.command(name="strike")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def guild_war_strike(self, ctx, war_id: int):
        mine = await self._member(ctx)
        if not mine:
            return
        war = await self.db.get_guild_war(war_id)
        if not war or war["status"] != "open" or float(war["ends_at"]) <= time.time():
            await ctx.send("❌ That war is inactive.")
            return
        if mine["guild_id"] not in {str(war["guild_id"]), str(war["opponent_guild_id"])}:
            await ctx.send("❌ That war does not involve your guild.")
            return
        player = await self.db.get_rpg_player(ctx.guild.id, ctx.author.id)
        gear = await equipment_stats(self.db, ctx.guild.id, ctx.author.id)
        companion = await self.db.get_active_rpg_companion(ctx.guild.id, ctx.author.id)
        power = int(player["strength"]) + int(player["magic"]) + int(player["level"]) * 2 + int(gear["power"]) * 2
        if companion:
            power += int(companion["level"])
        points = max(1, min(5, power // 25))
        ok, reason = await self.db.add_guild_war_score(war_id, mine["guild_id"], points)
        if not ok:
            await ctx.send("❌ The war strike could not be recorded.")
            return
        await ctx.send(f"⚔️ RPG war strike landed for **+{points}** war score.")
    
    @guild_war.command(name="end")
    async def guild_war_end(self, ctx, war_id: int):
        war = await self.db.get_guild_war(war_id)
        if not war:
            await ctx.send("❌ War not found.")
            return
        mine = await self._member(ctx)
        if not mine:
            return
        if mine["guild_id"] not in {str(war["guild_id"]), str(war["opponent_guild_id"])}:
            await ctx.send("❌ That war does not involve your guild.")
            return
        result = await self.db.end_guild_war(war_id)
        if not result:
            await ctx.send("⏳ The war has not reached its end time yet.")
            return
        winner = result["winner_guild_id"]
        await ctx.send(
            f"🏁 War **#{war_id}** ended. "
            f"{'Winner: `'+str(winner)+'`' if winner else 'It was a draw.'}"
        )

    @guild_war.command(name="score")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def guild_war_score(self, ctx, war_id: int, points: int = 1):
        mine = await self._member(ctx)
        if not mine:
            return
        ok, reason = await self.db.add_guild_war_score(war_id, mine["guild_id"], min(10, max(1, points)))
        if not ok:
            await ctx.send("❌ That war is inactive or does not involve your guild.")
            return
        await ctx.send(f"⚔️ War score added: **{points}**.")

    @guild.command(name="relic")
    async def guild_relic(self, ctx, action: str, equipment_id: str):
        mine = await self._role(ctx)
        if not mine:
            return
        if action.lower() != "claim":
            await ctx.send("Usage: `!guild relic claim <eclipse_blade|void_crown|celestial_aegis|sovereign_relic>`")
            return
        if equipment_id not in LEGENDARIES:
            await ctx.send("❌ Unknown legendary equipment.")
            return
        label, level = LEGENDARIES[equipment_id]
        if int(mine["level"]) < level:
            await ctx.send(f"❌ Guild Level **{level}** required.")
            return
        ok, reason = await self.db.claim_guild_relic(mine["guild_id"], equipment_id, ctx.author.id, RELIC_COST, level)
        if not ok:
            await ctx.send("❌ Relic unavailable or the guild treasury is too low.")
            return
        await self.db.add_rpg_item(ctx.guild.id, ctx.author.id, f"legendary_{equipment_id}", 1)
        await ctx.send(f"🌌 **{label}** acquired for the guild and bound to {ctx.author.mention}.")

    @guild.command(name="relics")
    async def guild_relics(self, ctx):
        mine = await self._member(ctx)
        if not mine:
            return
        rows = await self.db.get_guild_relics(mine["guild_id"])
        if not rows:
            await ctx.send("🌌 No legendary equipment has been acquired.")
            return
        lines=[f"**{LEGENDARIES.get(r['equipment_id'],(r['equipment_id'],0))[0]}** → <@{r['owner_id']}>" for r in rows]
        await ctx.send(embed=self._embed("🌌 Legendary Arsenal","\n".join(lines),discord.Color.gold()))

    @commands.command(name="worldevent", aliases=["serverevent"])
    @commands.has_guild_permissions(manage_guild=True)
    async def worldevent(self, ctx, action: str = "status"):
        action=action.lower()
        if action=="start":
            await self.db.set_server_event(ctx.guild.id,"eclipse_festival","ECLIPSE Festival",2.0,3600)
            await ctx.send("🌌 **ECLIPSE Festival** is live for **1 hour** — economy earnings are doubled.")
            return
        event=await self.db.get_server_event(ctx.guild.id)
        if not event:
            await ctx.send("🌌 No server-wide event is active.")
            return
        await ctx.send(
            f"🌌 **{event['title']}** · **{float(event['multiplier']):.2f}×** earnings · "
            f"ends <t:{int(event['ends_at'])}:R>"
        )


async def setup(bot):
    await bot.add_cog(Guilds(bot))
