"""ECLIPSE RPG command surface."""
import discord
from discord.ext import commands
from constants import COLOR_GOLD, COLOR_PRIMARY
from rpg.classes import CLASSES, get_class
from rpg.manager import ADVENTURE_COOLDOWN, adventure, choose_class, get_player, rest
from rpg.equipment import grant_starter_gear, inventory
from rpg.skills import get_skills
from rpg.skills_service import ensure_class_skills, unlock_skill
from rpg.combat import start as start_battle, attack as combat_attack, flee as flee_battle
from rpg.quests import ensure_quests, list_quests, claim as claim_quest


def xp_bar(current, maximum, length=14):
    if maximum <= 0: return "█"*length
    filled=int(length*min(current/maximum,1))
    return "█"*filled+"░"*(length-filled)

class RPG(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.db=bot.db

    @commands.group(name="rpg",invoke_without_command=True)
    async def rpg(self,ctx): await ctx.invoke(self.profile)

    @rpg.command(name="profile",aliases=["p","status"])
    async def profile(self,ctx):
        player=await get_player(self.db,ctx.guild.id,ctx.author.id); cls=get_class(player["class_key"]); need=max(1,player['level']*100)
        embed=discord.Embed(title=f"♡ ECLIPSE · {cls['icon']} {cls['name']} ♡",description=f"**{ctx.author.display_name}**\nLevel **{player['level']}** · {cls['description']}\n\n{xp_bar(player['xp'],need)} **{player['xp']}/{need} XP**",color=COLOR_PRIMARY)
        embed.add_field(name="♡ VITALS",value=f"❤️ {player['hp']}/{player['max_hp']} HP\n💠 {player['mp']}/{player['max_mp']} MP\n💰 {player['gold']:,} RPG gold",inline=True)
        embed.add_field(name="♡ STATS",value=f"⚔️ {player['strength']} STR\n🛡️ {player['defense']} DEF\n🔮 {player['magic']} MAG\n🪽 {player['agility']} AGI",inline=True)
        embed.set_thumbnail(url=ctx.author.display_avatar.url); embed.set_footer(text="୨୧ !rpg class · !rpg adventure · !rpg rest"); await ctx.send(embed=embed)

    @rpg.command(name="class",aliases=["choose"])
    async def class_command(self,ctx,key:str=None):
        if not key:
            lines=[f"{d['icon']} **{d['name']}** — {d['description']}" for d in CLASSES.values()]
            await ctx.send(embed=discord.Embed(title="♡ ECLIPSE · CLASSES ♡",description="\n\n".join(lines)+"\n\nUse !rpg class <name> to choose.",color=COLOR_PRIMARY)); return
        chosen,_=await choose_class(self.db,ctx.guild.id,ctx.author.id,key)
        if chosen is None: await ctx.send("❌ Unknown class. Use !rpg class to see the available paths."); return
        await grant_starter_gear(self.db, ctx.guild.id, ctx.author.id, key.lower())
        await ensure_class_skills(self.db, ctx.guild.id, ctx.author.id, key.lower())
        await ctx.send(f"{chosen['icon']} **{ctx.author.display_name}** is now a **{chosen['name']}**.\n{chosen['description']}\n\n🎒 Starter gear and your first skill have been unlocked.")

    @rpg.command(name="adventure",aliases=["explore","hunt"])
    @commands.cooldown(1,ADVENTURE_COOLDOWN,commands.BucketType.user)
    async def adventure_command(self,ctx):
        result=await adventure(self.db,ctx.guild.id,ctx.author.id)
        if not result["ok"]: await ctx.send(f"⏳ The world is still settling. Try again in **{result['remaining']:.0f}s**."); return
        reward=f"+{result['gold']:,} gold" if result['gold']>=0 else f"{result['gold']:,} gold"
        level_text="\n✦ **LEVEL UP**" if result["new_level"]>result["old_level"] else ""
        await ctx.send(embed=discord.Embed(title=f"🌙 {result['event']}",description=f"{result['narrative']}\n\n**Rewards:** {reward} · +{result['xp']} XP{level_text}",color=COLOR_GOLD))

    @rpg.command(name="rest",aliases=["heal"])
    async def rest_command(self,ctx):
        player=await rest(self.db,ctx.guild.id,ctx.author.id); await ctx.send(f"🪽 **{ctx.author.display_name}** rests beneath the ECLIPSE.\n❤️ HP restored to **{player['hp']}/{player['max_hp']}** · 💠 MP restored to **{player['mp']}/{player['max_mp']}**")

    @rpg.command(name="battle", aliases=["fight"])
    async def battle_command(self, ctx):
        result = await start_battle(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            battle = result["battle"]
            await ctx.send(f"⚔️ Already fighting **{battle['enemy_name']}**. Use !rpg attack.")
            return
        battle = result["battle"]
        await ctx.send(f"⚔️ **BATTLE BEGINS**\nEnemy: **{battle['enemy_name']}** · ❤️ {battle['enemy_hp']}/{battle['enemy_max_hp']} HP\nUse !rpg attack, !rpg skill <id>, or !rpg flee.")

    @rpg.command(name="attack", aliases=["atk"])
    async def attack_command(self, ctx):
        result = await combat_attack(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        if result.get("victory"):
            await ctx.send(f"🏆 **VICTORY** · {result['damage']} damage · +{result['xp']} XP · +{result['gold']} gold" + ("\n✦ **LEVEL UP**" if result["level_up"] else ""))
        elif result.get("defeat"):
            await ctx.send(f"☠️ **DEFEATED** · You dealt {result['damage']} damage, but the enemy struck for {result['incoming']}.")
        else:
            await ctx.send(f"⚔️ You dealt **{result['damage']}** damage. Enemy ❤️ {result['enemy_hp']}/{result['enemy_max_hp']} · You took **{result['incoming']}** damage.")

    @rpg.command(name="skill")
    async def skill_command(self, ctx, skill_id: str = None):
        if not skill_id:
            await ctx.send("Use !rpg skills to see your unlocked skills.")
            return
        result = await combat_attack(self.db, ctx.guild.id, ctx.author.id, skill_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        if result.get("victory"):
            await ctx.send(f"✨ **SKILL VICTORY** · {result['damage']} damage · +{result['xp']} XP · +{result['gold']} gold")
        elif result.get("defeat"):
            await ctx.send(f"☠️ **DEFEATED** · Skill dealt {result['damage']} damage.")
        else:
            await ctx.send(f"✨ Skill dealt **{result['damage']}** damage. Enemy ❤️ {result['enemy_hp']}/{result['enemy_max_hp']} · You took **{result['incoming']}** damage.")

    @rpg.command(name="flee", aliases=["escape"])
    async def flee_command(self, ctx):
        if await flee_battle(self.db, ctx.guild.id, ctx.author.id):
            await ctx.send("🏃 You escaped the battle.")
        else:
            await ctx.send("There is no active battle.")

    @rpg.command(name="quests", aliases=["quest"])
    async def quests_command(self, ctx):
        rows = await ensure_quests(self.db, ctx.guild.id, ctx.author.id)
        by_id = {r["quest_id"]: r for r in rows}
        lines = []
        for qid, quest in list_quests():
            row = by_id[qid]
            status = "✓ COMPLETE" if row["completed"] else f"{row['progress']}/{quest['goal']}"
            lines.append(f"**{quest['name']}** · {status}\n{quest['description']} · +{quest['xp']} XP · +{quest['gold']} gold")
        await ctx.send(embed=discord.Embed(title="♡ ECLIPSE · QUESTS ♡", description="\n\n".join(lines), color=COLOR_PRIMARY))

    @rpg.command(name="claim", aliases=["claimquest"])
    async def claim_quest_command(self, ctx, quest_id: str = None):
        if not quest_id:
            await ctx.send("Use !rpg quests to see quest IDs, then !rpg claim <id>.")
            return
        result = await claim_quest(self.db, ctx.guild.id, ctx.author.id, quest_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        q = result["quest"]
        extra = "\n✦ **LEVEL UP**" if result["level_up"] else ""
        item_text = f" · 🎁 `{q['item']}`" if q.get("item") else ""
        await ctx.send(f"🏆 **{q['name']}** reward claimed · +{q['xp']} XP · +{q['gold']} gold{item_text}{extra}")
    @rpg.command(name="inventory", aliases=["inv", "gear"])
    async def inventory_command(self, ctx):
        items = await inventory(self.db, ctx.guild.id, ctx.author.id)
        if not items:
            await ctx.send("🎒 Your RPG inventory is empty.")
            return
        lines = []
        for item in items:
            equipped = " · **EQUIPPED**" if item["equipped"] else ""
            lines.append(f"• `{item['item_id']}` ×{item['amount']}{equipped}")
        await ctx.send(embed=discord.Embed(
            title="♡ ECLIPSE · INVENTORY ♡",
            description="\n".join(lines),
            color=COLOR_PRIMARY
        ))

    @rpg.command(name="skills")
    async def skills_command(self, ctx):
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)
        owned = await ensure_class_skills(self.db, ctx.guild.id, ctx.author.id, player["class_key"])
        available = get_skills(player["class_key"])
        lines = []
        for skill in available:
            state = "✦ UNLOCKED" if skill["id"] in owned else "○ LOCKED"
            lines.append(f"{state} **{skill['name']}** · {skill['cost']} MP\n{skill['description']}")
        await ctx.send(embed=discord.Embed(
            title="♡ ECLIPSE · SKILLS ♡",
            description="\n\n".join(lines),
            color=COLOR_PRIMARY
        ))

    @rpg.command(name="unlock")
    async def unlock_command(self, ctx, skill_id: str = None):
        if not skill_id:
            await ctx.send("Use `!rpg skills` to see available skills.")
            return
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)
        skill, owned = await unlock_skill(
            self.db, ctx.guild.id, ctx.author.id,
            player["class_key"], skill_id
        )
        if skill is None:
            await ctx.send("❌ That skill does not belong to your current class.")
            return
        await ctx.send(f"✦ **{skill['name']}** unlocked. MP cost: **{skill['cost']}**.")

async def setup(bot): await bot.add_cog(RPG(bot))
