"""ECLIPSE RPG command surface."""
import discord
from discord.ext import commands
from constants import COLOR_GOLD, COLOR_PRIMARY
from rpg.classes import CLASSES, get_class
from rpg.manager import ADVENTURE_COOLDOWN, adventure, choose_class, get_player, rest
from rpg.equipment import grant_starter_gear, inventory, get_equipment, equip, unequip, upgrade, equipment_stats
from rpg.skills import get_skills
from rpg.skills_service import ensure_class_skills, unlock_skill
from rpg.combat import start as start_battle, attack as combat_attack, flee as flee_battle
from rpg.quests import ensure_quests, list_quests, claim as claim_quest
from rpg.world import list_regions, get_region, list_events, get_event
from rpg.exploration import world_status, travel, explore
from rpg.towns import town_status, inn, shrine, alchemist, buy
from rpg.items import get_item
from rpg.crafting import MATERIALS, list_recipes, craft, salvage


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
        player=await get_player(self.db,ctx.guild.id,ctx.author.id); cls=get_class(player["class_key"]); need=max(1,player['level']*100); gear=await equipment_stats(self.db,ctx.guild.id,ctx.author.id)
        embed=discord.Embed(title=f"♡ ECLIPSE · {cls['icon']} {cls['name']} ♡",description=f"**{ctx.author.display_name}**\nLevel **{player['level']}** · {cls['description']}\n\n{xp_bar(player['xp'],need)} **{player['xp']}/{need} XP**",color=COLOR_PRIMARY)
        embed.add_field(name="♡ REALM",value=f"{get_region(player.get('region'))['icon']} {get_region(player.get('region'))['name']}" if get_region(player.get("region")) else "Unknown",inline=False)
        embed.add_field(name="♡ VITALS",value=f"❤️ {player['hp']}/{player['max_hp'] + gear['max_hp']} HP\n💠 {player['mp']}/{player['max_mp'] + gear['max_mp']} MP\n💰 {player['gold']:,} RPG gold",inline=True)
        embed.add_field(name="♡ STATS",value=f"⚔️ {player['strength'] + gear['strength']} STR\n🛡️ {player['defense'] + gear['defense']} DEF\n🔮 {player['magic'] + gear['magic']} MAG\n🪽 {player['agility'] + gear['agility']} AGI\n⚔️ +{gear['power']} weapon power",inline=True)
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

    @rpg.command(name="adventure",aliases=["hunt"])
    @commands.cooldown(1,ADVENTURE_COOLDOWN,commands.BucketType.user)
    async def adventure_command(self,ctx):
        result=await adventure(self.db,ctx.guild.id,ctx.author.id)
        if not result["ok"]: await ctx.send(f"⏳ The world is still settling. Try again in **{result['remaining']:.0f}s**."); return
        reward=f"+{result['gold']:,} gold" if result['gold']>=0 else f"{result['gold']:,} gold"
        level_text="\n✦ **LEVEL UP**" if result["new_level"]>result["old_level"] else ""
        await ctx.send(embed=discord.Embed(title=f"🌙 {result['event']}",description=f"{result['narrative']}\n\n**Rewards:** {reward} · +{result['xp']} XP{level_text}",color=COLOR_GOLD))

    @rpg.command(name="world", aliases=["map", "realm"])
    async def world_command(self, ctx):
        world = await world_status(self.db, ctx.guild.id)
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)
        current = get_region(player.get("region"))
        lines = []
        for rid, region in list_regions():
            state = "📍 HERE" if rid == player.get("region") else f"Danger {region['danger']}/4"
            lines.append(f"{region['icon']} **{region['name']}** · {state}\\n{region['description']}")
        active = get_event(world["active_event"]) if world.get("active_event") else None
        event_line = f"\\n{active['icon']} **{active['name']}** · active" if active else ""
        embed = discord.Embed(title="♡ ECLIPSE · THE VEILED REALMS ♡", description=f"**World Day {world['day']}** · {world['weather'].title()} · Instability {world['instability']}/10{event_line}\\n\\n" + "\\n\\n".join(lines), color=COLOR_PRIMARY)
        embed.set_footer(text=f"୨୧ Current realm: {current['name'] if current else 'Unknown'} · !rpg travel <region>")
        await ctx.send(embed=embed)

    @rpg.command(name="travel", aliases=["go", "journey"])
    async def travel_command(self, ctx, region_id: str = None):
        if not region_id:
            lines = [f"{r['icon']} {rid} — **{r['name']}** · danger {r['danger']}/4" for rid, r in list_regions()]
            await ctx.send("🗺️ **Choose a realm:**\\n" + "\\n".join(lines))
            return
        result = await travel(self.db, ctx.guild.id, ctx.author.id, region_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        region = result["region"]
        await ctx.send(f"🪽 **THE ROAD OPENS**\\n\\n{region['icon']} **{region['name']}**\\n{region['description']}\\n\\nTravel time: **{result['duration']:.0f}s**. Your journey has begun.")

    @rpg.command(name="explore", aliases=["scout", "search"])
    async def explore_command(self, ctx):
        result = await explore(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        region = result["region"]
        if result["kind"] == "world_event":
            event = result["event"]
            await ctx.send(f"{event['icon']} **WORLD EVENT · {event['name']}**\\n\\n{event['description']}\\n\\nThe realm itself has changed.")
            return

        if result["kind"] == "guardian":
            enemy = result["enemy"]
            battle = await start_battle(self.db, ctx.guild.id, ctx.author.id, enemy_override=enemy)
            if not battle["ok"]:
                await ctx.send(f"⚔️ **{enemy['name']}** is already confronting you. Use !rpg attack.")
                return
            await ctx.send(f"{region['icon']} **{region['name']}**\\n\\n👑 **REALM GUARDIAN**\\n**{enemy['name']}** · ❤️ {enemy['hp']}/{enemy['hp']} HP\\nDefeat it to change the history of this realm.")
            return

        if result["kind"] == "discovery":
            discovery = result["discovery"]
            level_text = "\\n✦ **LEVEL UP**" if result["new_level"] > result["old_level"] else ""
            await ctx.send(f"{discovery['icon']} **DISCOVERY · {discovery['name']}**\\n\\n{discovery['description']}\\n\\n**Found:** +{discovery['gold']:,} gold · +{discovery['xp']} XP{level_text}")
            return

        if result["kind"] == "enemy":
            enemy = result["enemy"]
            battle = await start_battle(self.db, ctx.guild.id, ctx.author.id, enemy_override=enemy)
            if not battle["ok"]:
                await ctx.send(f"⚔️ **{enemy['name']}** finds you before you can prepare. Use !rpg attack.")
                return
            await ctx.send(f"{region['icon']} **{region['name']}**\\n\\n⚔️ **AN ENCOUNTER**\\n**{enemy['name']}** · ❤️ {enemy['hp']}/{enemy['hp']} HP\\nThe realm has noticed you. Use !rpg attack, !rpg skill <id>, or !rpg flee.")
            return
        event = result["event"]
        level_text = "\\n✦ **LEVEL UP**" if result["new_level"] > result["old_level"] else ""
        await ctx.send(f"{region['icon']} **{region['name']}**\\n\\n{event['text']}\\n\\n**Found:** +{event['gold']:,} gold · +{event['xp']} XP{level_text}")
    @rpg.command(name="discoveries", aliases=["codex", "lore"])
    async def discoveries_command(self, ctx):
        rows = await self.db.get_rpg_discoveries(ctx.guild.id, ctx.author.id)
        found = {row["discovery_id"] for row in rows}
        lines = []
        from rpg.world import DISCOVERIES
        for did, data in DISCOVERIES.items():
            state = "✦ DISCOVERED" if did in found else "○ UNKNOWN"
            lines.append(f"{state} {data['icon']} **{data['name']}** · {data['region']}")
        await ctx.send(embed=discord.Embed(
            title="♡ ECLIPSE · CODEX ♡",
            description="\\n".join(lines),
            color=COLOR_PRIMARY
        ))

    @rpg.command(name="town", aliases=["towns", "settlement"])
    async def town_command(self, ctx, action: str = None, item_id: str = None):
        if not action:
            s = await town_status(self.db, ctx.guild.id, ctx.author.id)
            if not s["ok"]:
                await ctx.send(f"❌ {s['message']}")
                return
            t = s["town"]
            services = "\n".join(f"• `{x}`" for x in t["services"])
            await ctx.send(embed=discord.Embed(title=f"{t['icon']} ECLIPSE · {t['name']}", description=f"{t['description']}\n\n**Services**\n{services}\n\n`!rpg town shop` to browse the local merchant.", color=COLOR_PRIMARY))
            return
        action = action.lower()
        if action in {"shop", "merchant", "buy"} and not item_id:
            s = await town_status(self.db, ctx.guild.id, ctx.author.id)
            if not s["ok"]:
                await ctx.send(f"❌ {s['message']}")
                return
            lines = []
            for iid, offer in s["town"]["merchant"].items():
                item = get_item(iid)
                lines.append(f"`{iid}` — **{item['name']}** · 💰 {offer['price']:,}")
            await ctx.send(f"🛒 **{s['town']['name']} MERCHANT**\n\n" + "\n".join(lines) + "\n\nBuy with `!rpg town buy <item>`.")
            return
        if action in {"shop", "merchant", "buy"}:
            result = await buy(self.db, ctx.guild.id, ctx.author.id, item_id)
            if not result["ok"]:
                await ctx.send(f"❌ {result['message']}")
                return
            await ctx.send(f"🛒 **PURCHASED** · {result['item']['icon']} **{result['item']['name']}**\nPaid **{result['price']:,} RPG gold**.")
            return
        handlers = {"inn": inn, "shrine": shrine, "alchemist": alchemist}
        handler = handlers.get(action)
        if handler is None:
            await ctx.send("Use `!rpg town`, `!rpg town shop`, `!rpg town buy <item>`, `!rpg town inn`, `!rpg town shrine`, or `!rpg town alchemist`.")
            return
        result = await handler(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        if action == "inn":
            await ctx.send(f"🛏️ **{result['town']['name']} INN**\nYou wake restored to full HP and MP. · **-{result['cost']} gold**")
        elif action == "shrine":
            level = "\n✦ **LEVEL UP**" if result["new_level"] > result["old_level"] else ""
            await ctx.send(f"🕯️ **{result['town']['name']} SHRINE**\nA blessing settles over you. · **+{result['xp']} XP** · **-{result['cost']} gold**{level}")
        else:
            await ctx.send(f"⚗️ **{result['town']['name']} ALCHEMIST**\nYour MP has been restored. · **-{result['cost']} gold**")
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
            data = item.get("item") or {}
            equipped = " · **EQUIPPED**" if item["equipped"] else ""
            level = f" · +{item['equipped_level']}" if item.get("equipped_level") else ""
            rarity = f" · {data.get('rarity', 'common').title()}" if data else ""
            label = data.get("name", item["item_id"])
            icon = data.get("icon", "🎒")
            lines.append(f"• {icon} **{label}** ×{item['amount']}{rarity}{level}{equipped}")
        await ctx.send(embed=discord.Embed(
            title="♡ ECLIPSE · INVENTORY ♡",
            description="\n".join(lines),
            color=COLOR_PRIMARY
        ))

    @rpg.command(name="equipment", aliases=["equipments", "loadout"])
    async def equipment_command(self, ctx):
        rows = await get_equipment(self.db, ctx.guild.id, ctx.author.id)
        stats = await equipment_stats(self.db, ctx.guild.id, ctx.author.id)
        lines = []
        for slot in ("weapon", "armor", "accessory", "relic"):
            row = next((x for x in rows if x["slot"] == slot), None)
            if not row:
                lines.append(f"**{slot.title()}** · ○ empty")
                continue
            item = get_item(row["item_id"])
            rarity = item.get("rarity", "common").upper() if item else "UNKNOWN"
            lines.append(f"**{slot.title()}** · {item['icon']} **{item['name']}** · {rarity} · +{row['level']}")
        lines.append("")
        lines.append(
            f"**Gear bonuses:** ⚔️ +{stats['power']} power · 🛡️ +{stats['defense']} DEF · "
            f"🔮 +{stats['magic']} MAG · 🪽 +{stats['agility']} AGI · "
            f"❤️ +{stats['max_hp']} HP · 💠 +{stats['max_mp']} MP"
        )
        embed = discord.Embed(title="♡ ECLIPSE · EQUIPMENT ♡", description="\n".join(lines), color=COLOR_PRIMARY)
        embed.set_footer(text="୨୧ !rpg equip <item> · !rpg unequip <slot> · !rpg upgrade <item>")
        await ctx.send(embed=embed)

    @rpg.command(name="equip")
    async def equip_command(self, ctx, item_id: str = None):
        if not item_id:
            await ctx.send("Use `!rpg inventory` or `!rpg equipment` to choose an item.")
            return
        result = await equip(self.db, ctx.guild.id, ctx.author.id, item_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        item = result["item"]
        await ctx.send(f"୨୧ **EQUIPPED** · {item['icon']} **{item['name']}** ({item.get('rarity','common').title()}) in the **{result['slot']}** slot.")

    @rpg.command(name="unequip")
    async def unequip_command(self, ctx, slot: str = None):
        if not slot:
            await ctx.send("Choose a slot: `weapon`, `armor`, `accessory`, or `relic`.")
            return
        result = await unequip(self.db, ctx.guild.id, ctx.author.id, slot)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        item = get_item(result["item_id"])
        await ctx.send(f"○ **UNEQUIPPED** · {item['icon']} **{item['name']}** from the **{result['slot']}** slot.")

    @rpg.command(name="upgrade")
    async def upgrade_command(self, ctx, item_id: str = None):
        if not item_id:
            await ctx.send("Use `!rpg equipment` to see your equipped gear.")
            return
        result = await upgrade(self.db, ctx.guild.id, ctx.author.id, item_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        item = result["item"]
        await ctx.send(f"✦ **UPGRADED** · {item['icon']} **{item['name']}** **+{result['old_level']} → +{result['new_level']}** · Paid **{result['cost']:,} RPG gold**.")

    @rpg.command(name="materials", aliases=["mats", "resources"])
    async def materials_command(self, ctx):
        rows = await self.db.get_rpg_materials(ctx.guild.id, ctx.author.id)
        if not rows:
            await ctx.send("⛏️ You have no crafting materials yet. Defeat enemies or salvage equipment.")
            return
        lines = []
        for row in rows:
            data = MATERIALS.get(row["material_id"], {})
            lines.append(f"{data.get('icon', '✦')} **{data.get('name', row['material_id'])}** ×{row['amount']}\n{data.get('description', '')}")
        await ctx.send(embed=discord.Embed(
            title="♡ ECLIPSE · MATERIALS ♡",
            description="\n\n".join(lines),
            color=COLOR_PRIMARY
        ))

    @rpg.command(name="recipes", aliases=["recipe", "forge"])
    async def recipes_command(self, ctx):
        lines = []
        for item_id, recipe in list_recipes():
            item = get_item(item_id)
            mats = " · ".join(
                f"{MATERIALS[mid]['icon']} {MATERIALS[mid]['name']} ×{amount}"
                for mid, amount in recipe["materials"].items()
            )
            gates = []
            if recipe.get("requires_discovery"):
                gates.append(f"discover {recipe['requires_discovery']}")
            if recipe.get("requires_guardian"):
                gates.append(f"defeat {recipe['requires_guardian']}")
            gate_text = f" · 🔒 {', '.join(gates)}" if gates else ""
            lines.append(f"{item['icon']} **{item['name']}** · 💰 {recipe['gold']:,}\n{mats}{gate_text}")
        await ctx.send(embed=discord.Embed(
            title="♡ ECLIPSE · FORGE RECIPES ♡",
            description="\n\n".join(lines) + "\n\nUse \`!rpg craft <item>\`.",
            color=COLOR_PRIMARY
        ))

    @rpg.command(name="craft")
    async def craft_command(self, ctx, item_id: str = None):
        if not item_id:
            await ctx.send("Use \`!rpg recipes\` to see what the forge can create.")
            return
        result = await craft(self.db, ctx.guild.id, ctx.author.id, item_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        item = result["item"]
        await ctx.send(
            f"🔥 **FORGED** · {item['icon']} **{item['name']}** "
            f"({item.get('rarity', 'common').title()})\n"
            f"The forge consumes the materials and **{result['recipe']['gold']:,} RPG gold**."
        )

    @rpg.command(name="salvage", aliases=["dismantle", "break"])
    async def salvage_command(self, ctx, item_id: str = None):
        if not item_id:
            await ctx.send("Use \`!rpg inventory\` and choose an unequipped item to salvage.")
            return
        result = await salvage(self.db, ctx.guild.id, ctx.author.id, item_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        item = result["item"]
        yields = " · ".join(
            f"{MATERIALS[mid]['icon']} {MATERIALS[mid]['name']} ×{amount}"
            for mid, amount in result["yields"].items()
        )
        await ctx.send(f"♻️ **SALVAGED** · {item['icon']} **{item['name']}**\nRecovered: {yields}")

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
