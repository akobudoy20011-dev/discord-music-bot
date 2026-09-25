"""ECLIPSE RPG command surface."""
import discord
from discord.ext import commands
from constants import COLOR_GOLD, COLOR_PRIMARY
from rpg.classes import CLASSES, get_class
from rpg.manager import ADVENTURE_COOLDOWN, adventure, choose_class, get_player, rest
from rpg.equipment import grant_starter_gear, inventory, get_equipment, equip, unequip, upgrade, equipment_stats
from rpg.skills import get_skills
from rpg.specials import SPECIALS, get_special, get_specials_for_class
from rpg.skills_service import ensure_class_skills, unlock_skill
from rpg.combat import start as start_battle, attack as combat_attack, special as combat_special, flee as flee_battle
from rpg.hunting import board as hunting_board, start_hunt, recent_kills, get_profile as get_hunt_profile
from rpg.quests import ensure_quests, list_quests, claim as claim_quest, NPCS, npc_view
from rpg.world import list_regions, get_region, list_events, get_event
from rpg.exploration import world_status, travel, explore
from rpg.towns import town_status, inn, shrine, alchemist, buy
from rpg.items import get_item
from rpg.crafting import MATERIALS, list_recipes, craft, salvage
from rpg.dungeons import list_dungeons, start as start_dungeon, status as dungeon_status, advance as advance_dungeon, retreat as retreat_dungeon
from rpg.gathering import RESOURCE_NODES, profile as gathering_profile, gather as gather_resource, collections as gathering_collections
from rpg.achievements import ACHIEVEMENTS, check as check_achievements, list_unlocked as unlocked_achievements
from rpg.expansion import FACTIONS, SUBCLASSES, HOUSING, CONSUMABLES, DAILY_POOL, faction_rows, rep_rank, choose_subclass, get_subclass, buy_house, get_house, pvp_rating, create_pvp, resolve_pvp, daily_quest, claim_daily, buy_consumable, use_consumable, enchant, RELATIONSHIPS, relationship_rows, affinity_rank, gift_npc


def xp_bar(current, maximum, length=14):
    if maximum <= 0: return "█"*length
    filled=int(length*min(current/maximum,1))
    return "█"*filled+"░"*(length-filled)

class RPGHelpView(discord.ui.View):
    """Interactive RPG command codex so players do not need to memorize commands."""

    def __init__(self, *, author_id=None, timeout=300):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.select = discord.ui.Select(
            placeholder="୨୧ Choose an RPG section",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Getting Started", value="start", emoji="🌙", description="Profile, class, core loop"),
                discord.SelectOption(label="Adventure & World", value="world", emoji="🗺️", description="Travel, explore, towns, discoveries"),
                discord.SelectOption(label="Combat", value="combat", emoji="⚔️", description="Battle, attacks, skills, specials"),
                discord.SelectOption(label="Quests & Progression", value="progress", emoji="📜", description="Quests, rewards, skills, codex"),
                discord.SelectOption(label="Gear & Crafting", value="gear", emoji="🎒", description="Inventory, equipment, forge, materials"),
                discord.SelectOption(label="Everything", value="all", emoji="📖", description="Full RPG command reference"),
            ],
        )
        self.select.callback = self._select
        self.add_item(self.select)

    async def _guard(self, interaction):
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This RPG codex is locked to its creator.", ephemeral=True)
            return False
        return True

    async def _select(self, interaction):
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(
            embed=build_rpg_help_embed(self.select.values[0]),
            view=self,
        )

    @discord.ui.button(label="Home", emoji="🏠", style=discord.ButtonStyle.primary)
    async def home(self, interaction, button):
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(embed=build_rpg_help_embed("start"), view=self)

    @discord.ui.button(label="Full List", emoji="📖", style=discord.ButtonStyle.secondary)
    async def full_list(self, interaction, button):
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(embed=build_rpg_help_embed("all"), view=self)


RPG_HELP_PAGES = {
    "start": {
        "title": "🌙 ECLIPSE RPG · BEGIN HERE",
        "description": (
            "**THE BASIC LOOP**\n"
            "\`!rpg profile\` → check your character\n"
            "\`!rpg class\` → view/choose a class\n"
            "\`!rpg adventure\` → earn XP and RPG gold\n"
            "\`!rpg explore\` → discover the realm or enter encounters\n"
            "\`!rpg hunt\` → hunt scaled monsters for Hunt XP and loot\n"            "\`!rpg battle\` → start a random encounter\n"
            "\`!rpg rest\` → restore HP and MP\n\n"
            "**FIRST STEPS**\n"
            "① Run \`!rpg class\` and choose a path.\n"
            "② Run \`!rpg adventure\` for your first rewards.\n"
            "③ Run \`!rpg explore\` to find events, enemies and discoveries.\n"
            "④ Use \`!rpg inventory\` and \`!rpg equipment\` to manage gear.\n"
            "⑤ Use \`!rpg skills\` and \`!rpg special\` to learn your combat kit.\n\n"
            "**CONNECTED SYSTEMS**\n"
            "\`!companion\` · companions and training\n"
            "\`!guild\` · guilds, raids, wars and relics\n"
            "\`!worldboss\` · server world bosses"
        ),
    },
    "world": {
        "title": "🗺️ ECLIPSE RPG · ADVENTURE & WORLD",
        "description": (
            "**WORLD**\n"
            "\`!rpg world\` — view realms, weather and active world events\n"
            "\`!rpg travel <region>\` — travel to a realm\n"
            "\`!rpg explore\` — search your current realm\n"
            "\`!rpg discoveries\` — open your discovered codex\n\n"
            "**TOWNS**\n"
            "\`!rpg town\` — view the current settlement\n"
            "\`!rpg town shop\` — browse the merchant\n"
            "\`!rpg town buy <item>\` — buy an item\n"
            "\`!rpg town inn\` — restore HP/MP for gold\n"
            "\`!rpg town shrine\` — gain XP through the shrine\n"
            "\`!rpg town alchemist\` — restore MP\n\n"
            "**JOURNEY**\n"
            "\`!rpg adventure\` — take a timed adventure\n"
            "\`!rpg rest\` — recover without entering town"
        ),
    },
    "combat": {
        "title": "⚔️ ECLIPSE RPG · COMBAT",
        "description": (
            "**START & ACT**\n"
            "\`!rpg hunt\` — open the hunting board\n"            "\`!rpg hunt <target>\` — start a scaled monster hunt\n"            "\`!rpg battle\` — start a random battle\n"
            "\`!rpg attack\` — basic attack\n"
            "\`!rpg skill <id>\` — use an unlocked active skill\n"
            "\`!rpg special <id>\` — cast a class special\n"
            "\`!rpg flee\` — attempt to escape\n\n"
            "**DISCOVER YOUR KIT**\n"
            "\`!rpg skills\` — show your class skills\n"
            "\`!rpg unlock <skill>\` — unlock an available skill\n"
            "\`!rpg special\` — show your class specials\n"
            "\`!rpg special all\` — full special codex\n\n"
            "**COMBAT FLOW**\n"
            "Start with \`!rpg battle\` or trigger an encounter with \`!rpg explore\`. "
            "Then use attacks, skills or specials until the enemy is defeated."
        ),
    },
    "progress": {
        "title": "📜 ECLIPSE RPG · QUESTS & PROGRESSION",
        "description": (
            "**QUESTS**\n"
            "\`!rpg quests\` — see active quests and progress\n"
            "\`!rpg claim <quest_id>\` — claim a completed quest\n\n"
            "**CHARACTER**\n"
            "\`!rpg profile\` — stats, level, realm and vitals\n"
            "\`!rpg class\` — class list / choose a class\n"
            "\`!rpg skills\` — active skill list and unlock state\n"
            "\`!rpg special\` — class special list\n"
            "\`!rpg discoveries\` — lore and discovery progress\n\n"
            "**GROWTH**\n"
            "Adventure, exploration, combat and quests provide XP. "
            "Use your rewards to improve gear and keep pushing into higher-danger realms."
        ),
    },
    "gear": {
        "title": "🎒 ECLIPSE RPG · GEAR & CRAFTING",
        "description": (
            "**EQUIPMENT**\n"
            "\`!rpg inventory\` — all owned items\n"
            "\`!rpg equipment\` — current loadout and bonuses\n"
            "\`!rpg equip <item>\` — equip an item\n"
            "\`!rpg unequip <slot>\` — remove weapon/armor/accessory/relic\n"
            "\`!rpg upgrade <item>\` — upgrade equipped gear\n\n"
            "**CRAFTING**\n"
            "\`!rpg materials\` — view crafting materials\n"
            "\`!rpg recipes\` — view forge recipes\n"
            "\`!rpg craft <item>\` — craft an item\n"
            "\`!rpg salvage <item>\` — dismantle an item for materials\n\n"
            "**TIP**\n"
            "Check \`!rpg recipes\` before selling or salvaging materials. "
            "Some recipes require discoveries or realm guardians."
        ),
    },
    "all": {
        "title": "📖 ECLIPSE RPG · COMPLETE COMMAND CODEX",
        "description": (
            "**CHARACTER**\n"
            "\`!rpg profile\` · \`!rpg class\` · \`!rpg skills\` · \`!rpg unlock <skill>\`\n"
            "\`!rpg special\` · \`!rpg special all\` · \`!rpg discoveries\`\n\n"
            "**WORLD**\n"
            "\`!rpg world\` · \`!rpg travel <region>\` · \`!rpg explore\`\n"
            "\`!rpg adventure\` · \`!rpg rest\` · \`!rpg town\`\n"
            "\`!rpg dungeon\` · \`!rpg gather\` · \`!rpg collection\`\n"
            "\`!rpg achievements\`\n"
            "\`!rpg town shop\` · \`!rpg town buy <item>\` · \`!rpg town inn\`\n"
            "\`!rpg town shrine\` · \`!rpg town alchemist\`\n\n"
            "**COMBAT**\n"
            "\`!rpg battle\` · \`!rpg attack\` · \`!rpg skill <id>\` · \`!rpg special <id>\` · \`!rpg flee\`\n\n"
            "**QUESTS**\n"
            "\`!rpg quests\` · \`!rpg claim <quest_id>\`\n\n"
            "**GEAR**\n"
            "\`!rpg inventory\` · \`!rpg equipment\` · \`!rpg equip <item>\`\n"
            "\`!rpg unequip <slot>\` · \`!rpg upgrade <item>\`\n\n"
            "**FORGE**\n"
            "\`!rpg materials\` · \`!rpg recipes\` · \`!rpg craft <item>\` · \`!rpg salvage <item>\`\n\n"
            "**OUTSIDE THE RPG GROUP**\n"
            "\`!companion\` · \`!guild\` · \`!worldboss\`\n"
            "These are separate RPG-related systems with their own command menus."
        ),
    },
}


def build_rpg_help_embed(page="start"):
    data = RPG_HELP_PAGES.get(page, RPG_HELP_PAGES["start"])
    embed = discord.Embed(
        title=f"╭─── {data['title']} ───╮",
        description=data["description"],
        color=COLOR_PRIMARY if page != "combat" else COLOR_GOLD,
    )
    embed.add_field(
        name="୨୧ QUICK START",
        value="\`!rpg class\` → \`!rpg adventure\` → \`!rpg explore\`",
        inline=False,
    )
    embed.set_footer(text="ECLIPSE RPG · Select a section above or use !rpg help")
    return embed


class RPG(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.db=bot.db

    @commands.group(name="rpg",invoke_without_command=True)
    async def rpg(self,ctx):
        await ctx.send(embed=build_rpg_help_embed("start"), view=RPGHelpView(author_id=ctx.author.id))

    @rpg.command(name="help", aliases=["h", "commands"])
    async def help_command(self, ctx):
        await ctx.send(embed=build_rpg_help_embed("start"), view=RPGHelpView(author_id=ctx.author.id))

    @rpg.command(name="profile",aliases=["p","status"])
    async def profile(self,ctx):
        player=await get_player(self.db,ctx.guild.id,ctx.author.id); cls=get_class(player["class_key"]); need=max(1,player['level']*100); gear=await equipment_stats(self.db,ctx.guild.id,ctx.author.id)
        embed=discord.Embed(title=f"♡ ECLIPSE · {cls['icon']} {cls['name']} ♡",description=f"**{ctx.author.display_name}**\nLevel **{player['level']}** · {cls['description']}\n\n{xp_bar(player['xp'],need)} **{player['xp']}/{need} XP**",color=COLOR_PRIMARY)
        embed.add_field(name="♡ REALM",value=f"{get_region(player.get('region'))['icon']} {get_region(player.get('region'))['name']}" if get_region(player.get("region")) else "Unknown",inline=False)
        embed.add_field(name="♡ VITALS",value=f"❤️ {player['hp']}/{player['max_hp'] + gear['max_hp']} HP\n💠 {player['mp']}/{player['max_mp'] + gear['max_mp']} MP\n💰 {player['gold']:,} RPG gold",inline=True)
        embed.add_field(name="♡ STATS",value=f"⚔️ {player['strength'] + gear['strength']} STR\n🛡️ {player['defense'] + gear['defense']} DEF\n🔮 {player['magic'] + gear['magic']} MAG\n🪽 {player['agility'] + gear['agility']} AGI\n⚔️ +{gear['power']} weapon power",inline=True)
        hunt = await get_hunt_profile(self.db, ctx.guild.id, ctx.author.id)
        embed.add_field(name="🏹 HUNTING",value=f"Lv. **{hunt['hunt_level']}** · {hunt['hunt_xp']}/{hunt['hunt_level']*500} Hunt XP\n🔥 Streak **{hunt['streak']}** · Best **{hunt['best_streak']}**\n☠️ {hunt['total_kills']:,} kills",inline=False)
        embed.set_thumbnail(url=ctx.author.display_avatar.url); embed.set_footer(text="୨୧ !rpg class · !rpg adventure · !rpg rest"); await ctx.send(embed=embed)

    @rpg.command(name="class",aliases=["choose"])
    async def class_command(self,ctx,key:str=None):
        if not key:
            lines=[f"{d['icon']} **{d['name']}** — {d['description']}" for d in CLASSES.values()]
            await ctx.send(embed=discord.Embed(title="♡ ECLIPSE · CLASSES ♡",description="\n\n".join(lines)+"\n\nUse !rpg class <name> to choose.",color=COLOR_PRIMARY)); return
        existing_subclass = await get_subclass(self.db, ctx.guild.id, ctx.author.id)
        if existing_subclass:
            await ctx.send("❌ Your class is locked after choosing a subclass. Subclasses are permanent and cannot be transferred between classes.")
            return
        chosen,_=await choose_class(self.db,ctx.guild.id,ctx.author.id,key)
        if chosen is None: await ctx.send("❌ Unknown class. Use !rpg class to see the available paths."); return
        await grant_starter_gear(self.db, ctx.guild.id, ctx.author.id, key.lower())
        await ensure_class_skills(self.db, ctx.guild.id, ctx.author.id, key.lower())
        await ctx.send(f"{chosen['icon']} **{ctx.author.display_name}** is now a **{chosen['name']}**.\n{chosen['description']}\n\n🎒 Starter gear and your first skill have been unlocked.")

    @rpg.command(name="adventure")
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
            lines.append(f"{region['icon']} **{region['name']}** · {state}\n{region['description']}")
        active = get_event(world["active_event"]) if world.get("active_event") else None
        event_line = f"\n{active['icon']} **{active['name']}** · active" if active else ""
        embed = discord.Embed(title="♡ ECLIPSE · THE VEILED REALMS ♡", description=f"**World Day {world['day']}** · {world['weather'].title()} · Instability {world['instability']}/10{event_line}\n\n" + "\n\n".join(lines), color=COLOR_PRIMARY)
        embed.set_footer(text=f"୨୧ Current realm: {current['name'] if current else 'Unknown'} · !rpg travel <region>")
        await ctx.send(embed=embed)

    @rpg.command(name="travel", aliases=["go", "journey"])
    async def travel_command(self, ctx, region_id: str = None):
        if not region_id:
            lines = [f"{r['icon']} {rid} — **{r['name']}** · danger {r['danger']}/4" for rid, r in list_regions()]
            await ctx.send("🗺️ **Choose a realm:**\n" + "\n".join(lines))
            return
        result = await travel(self.db, ctx.guild.id, ctx.author.id, region_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        region = result["region"]
        await ctx.send(f"🪽 **THE ROAD OPENS**\n\n{region['icon']} **{region['name']}**\n{region['description']}\n\nTravel time: **{result['duration']:.0f}s**. Your journey has begun.")

    @rpg.command(name="explore", aliases=["scout", "search"])
    async def explore_command(self, ctx):
        result = await explore(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        region = result["region"]
        if result["kind"] == "world_event":
            event = result["event"]
            await ctx.send(f"{event['icon']} **WORLD EVENT · {event['name']}**\n\n{event['description']}\n\nThe realm itself has changed.")
            return

        if result["kind"] == "guardian":
            enemy = result["enemy"]
            battle = await start_battle(self.db, ctx.guild.id, ctx.author.id, enemy_override=enemy)
            if not battle["ok"]:
                if battle.get("battle"):
                    await ctx.send(f"⚔️ **{enemy['name']}** is already confronting you. Use !rpg attack.")
                else:
                    await ctx.send(f"❌ {battle.get('message', 'You cannot start this encounter right now.')}")
                return
            await ctx.send(f"{region['icon']} **{region['name']}**\n\n👑 **REALM GUARDIAN**\n**{enemy['name']}** · ❤️ {enemy['hp']}/{enemy['hp']} HP\nDefeat it to change the history of this realm.")
            return

        if result["kind"] == "discovery":
            discovery = result["discovery"]
            level_text = "\n✦ **LEVEL UP**" if result["new_level"] > result["old_level"] else ""
            await ctx.send(f"{discovery['icon']} **DISCOVERY · {discovery['name']}**\n\n{discovery['description']}\n\n**Found:** +{discovery['gold']:,} gold · +{discovery['xp']} XP{level_text}")
            return

        if result["kind"] == "enemy":
            enemy = result["enemy"]
            battle = await start_battle(self.db, ctx.guild.id, ctx.author.id, enemy_override=enemy)
            if not battle["ok"]:
                if battle.get("battle"):
                    await ctx.send(f"⚔️ **{enemy['name']}** finds you before you can prepare. Use !rpg attack.")
                else:
                    await ctx.send(f"❌ {battle.get('message', 'You cannot start this encounter right now.')}")
                return
            await ctx.send(f"{region['icon']} **{region['name']}**\n\n⚔️ **AN ENCOUNTER**\n**{enemy['name']}** · ❤️ {enemy['hp']}/{enemy['hp']} HP\nThe realm has noticed you. Use !rpg attack, !rpg skill <id>, !rpg special <id>, or !rpg flee.")
            return
        event = result["event"]
        level_text = "\n✦ **LEVEL UP**" if result["new_level"] > result["old_level"] else ""
        await ctx.send(f"{region['icon']} **{region['name']}**\n\n{event['text']}\n\n**Found:** +{event['gold']:,} gold · +{event['xp']} XP{level_text}")
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
            description="\n".join(lines),
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
        result=await rest(self.db,ctx.guild.id,ctx.author.id)
        if not result.get("hp"):
            if result.get("message"):
                await ctx.send(f"❌ {result['message']}")
                return
        await ctx.send(f"🪽 **{ctx.author.display_name}** rests beneath the ECLIPSE.\n❤️ HP restored to **{result['hp']}** · 💠 MP restored to **{result['mp']}**")

    @rpg.group(name="hunt", aliases=["monster", "hunting"], invoke_without_command=True)
    async def hunt_command(self, ctx, target_id: str = None):
        if target_id:
            prepared = await start_hunt(self.db, ctx.guild.id, ctx.author.id, target_id)
            if not prepared["ok"]:
                if prepared.get("battle"):
                    battle = prepared["battle"]
                    await ctx.send(f"⚔️ **HUNT IN PROGRESS** · {battle['enemy_name']} · ❤️ {battle['enemy_hp']}/{battle['enemy_max_hp']}")
                else:
                    await ctx.send(f"❌ {prepared.get('message', 'You cannot hunt right now.')}")
                return
            result = await start_battle(
                self.db, ctx.guild.id, ctx.author.id,
                enemy_override=prepared["target"], hunt_mode=True
            )
            if not result["ok"]:
                await self.db.delete_rpg_hunt_active(ctx.guild.id, ctx.author.id)
                await ctx.send(f"❌ {result.get('message', 'The hunt could not begin.')}")
                return
            target = prepared["target"]
            await ctx.send(
                f"{target['icon']} **HUNT STARTED** · **{target['name']}**\n"
                f"Lv.{target['monster_level']} · ❤️ {target['hp']}/{target['hp']} HP · ⚔️ {target['attack']} ATK\n"
                "Use !rpg attack, !rpg skill <id>, or !rpg special <id> to finish the hunt."
            )
            return

        result = await hunting_board(self.db, ctx.guild.id, ctx.author.id)
        contracts = result["contracts"]
        profile = result["profile"]
        if not contracts:
            await ctx.send("🏹 No hunt targets are available in this realm.")
            return
        lines = [
            f"{t['icon']} `{t['contract_id']}` · **{t['name']}** · Lv.{t['monster_level']} · "
            f"❤️ {t['hp']} · ✦ {t['xp']} XP · 💰 {t['gold']} gold"
            for t in contracts
        ]
        need = profile["hunt_level"] * 500
        await ctx.send(
            f"🏹 **MONSTER HUNTING BOARD**\n"
            f"Hunt Level **{profile['hunt_level']}** · {profile['hunt_xp']}/{need} Hunt XP · "
            f"🔥 Streak **{profile['streak']}** · Best **{profile['best_streak']}**\n\n"
            + "\n".join(lines)
            + "\n\nStart with `!rpg hunt <contract_id>` or hunt a base monster ID."
        )

    @hunt_command.command(name="history", aliases=["log", "kills"])
    async def hunt_history_command(self, ctx):
        rows = await recent_kills(self.db, ctx.guild.id, ctx.author.id)
        if not rows:
            await ctx.send("🏹 No completed hunts yet.")
            return
        lines = [
            f"{row['tier'].title()} · **{row['enemy_name']}** Lv.{row['monster_level']} · "
            f"+{row['xp']} Hunt XP · +{row['gold']} Hunt gold"
            for row in rows
        ]
        await ctx.send("🏹 **HUNT HISTORY**\n\n" + "\n".join(lines))

    @rpg.command(name="battle", aliases=["fight"])
    async def battle_command(self, ctx):
        result = await start_battle(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            if result.get("battle"):
                battle = result["battle"]
                await ctx.send(f"⚔️ Already fighting **{battle['enemy_name']}**. Use !rpg attack.")
            else:
                await ctx.send(f"❌ {result.get('message', 'You cannot start a battle right now.')}")
            return
        battle = result["battle"]
        await ctx.send(f"⚔️ **BATTLE BEGINS**\nEnemy: **{battle['enemy_name']}** · ❤️ {battle['enemy_hp']}/{battle['enemy_max_hp']} HP\nUse !rpg attack, !rpg skill <id>, or !rpg flee.")

    @rpg.command(name="skills", aliases=["skillbook", "abilities"])
    async def skills_command(self, ctx):
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)
        owned = set(await self.db.get_rpg_skills(ctx.guild.id, ctx.author.id))
        lines = []
        for skill in get_skills(player["class_key"]):
            if skill["id"] in owned:
                state = "✦ READY"
            elif player["level"] >= int(skill.get("level", 1)):
                state = "○ AVAILABLE"
            else:
                state = f"🔒 Lv.{skill.get('level', 1)}"
            cd = f" · {skill.get('cooldown', 0)}t CD" if skill.get("cooldown", 0) else ""
            lines.append(
                f"{state} · **{skill['name']}** · `{skill['id']}` · "
                f"{skill['cost']} MP{cd}\n{skill['description']}"
            )
        await ctx.send(embed=discord.Embed(
            title=f"⚔️ ECLIPSE · {player['class_key'].upper()} SKILLS",
            description="\n\n".join(lines) or "No skills are defined for this class.",
            color=COLOR_PRIMARY,
        ))

    @rpg.command(name="unlock", aliases=["learn", "learnskill"])
    async def unlock_skill_command(self, ctx, skill_id: str = None):
        if not skill_id:
            await ctx.send("Use !rpg skills to see available skills, then !rpg unlock <skill_id>.")
            return
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)
        result = await unlock_skill(self.db, ctx.guild.id, ctx.author.id, player["class_key"], skill_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        skill = result["skill"]
        await ctx.send(
            f"✦ **SKILL UNLOCKED** · {skill['name']}\n"
            f"{skill['description']} · {skill['cost']} MP · "
            f"Cooldown: {skill.get('cooldown', 0)} turns"
        )

    @rpg.command(name="attack", aliases=["atk"])
    async def attack_command(self, ctx):
        result = await combat_attack(self.db, ctx.guild.id, ctx.author.id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        if result.get("victory"):
            level_text = ""
            if result.get("level_up"):
                level_text = f"\n✦ **LEVEL UP** · Lv.{result['old_level']} → **Lv.{result['new_level']}**\n❤️ +{result['hp_gain']} Max HP · 💠 +{result['mp_gain']} Max MP"
            loot_text = f"\n🎁 **Loot:** {result['loot_name']}" if result.get("loot_name") else ""
            await ctx.send(
                f"☠️ **MONSTER DEFEATED** · **{result['enemy_name']}**\n"
                f"💥 {result['damage']} damage · ✦ +{result['xp']} XP · 💰 +{result['gold']} gold"
                f"{loot_text}{level_text}\n"
                "🏁 **HUNT COMPLETE** — the monster has been defeated." + (f"\n🏹 Hunt Lv.{result['hunt']['hunt_level']} · +{result['hunt']['hunt_xp']} Hunt XP · 🔥 Streak {result['hunt']['streak']}" if result.get("hunt", {}).get("active") else "") + (f" · ✦ Hunt level reward +{result['hunt']['level_reward_gold']:,} gold" if result.get("hunt", {}).get("level_reward_gold") else "") + (f"\n🏅 Achievements: {len(result.get('achievements', []))} unlocked" if result.get("achievements") else "")
            )
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
            level_text = ""
            if result.get("level_up"):
                level_text = f"\n✦ **LEVEL UP** · Lv.{result['old_level']} → **Lv.{result['new_level']}**\n❤️ +{result['hp_gain']} Max HP · 💠 +{result['mp_gain']} Max MP"
            loot_text = f"\n🎁 **Loot:** {result['loot_name']}" if result.get("loot_name") else ""
            await ctx.send(
                f"☠️ **MONSTER DEFEATED** · **{result['enemy_name']}**\n"
                f"✨ Skill dealt {result['damage']} damage · ✦ +{result['xp']} XP · 💰 +{result['gold']} gold"
                f"{loot_text}{level_text}\n"
                "🏁 **HUNT COMPLETE** — the monster has been defeated." + (f"\n🏹 Hunt Lv.{result['hunt']['hunt_level']} · +{result['hunt']['hunt_xp']} Hunt XP · 🔥 Streak {result['hunt']['streak']}" if result.get("hunt", {}).get("active") else "") + (f" · ✦ Hunt level reward +{result['hunt']['level_reward_gold']:,} gold" if result.get("hunt", {}).get("level_reward_gold") else "") + (f"\n🏅 Achievements: {len(result.get('achievements', []))} unlocked" if result.get("achievements") else "")
            )
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

    @rpg.command(name="special", aliases=["specials", "ultimate"])
    async def special_command(self, ctx, special_id: str = None):
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)

        if special_id and special_id.lower() == "all":
            lines = []
            for sid, data in SPECIALS.items():
                classes = ", ".join(data["class_keys"])
                lines.append(f"{data['icon']} **{data['name']}** - {sid}\nLv. **{data['level']}** · {data['cost']} MP · {data['cooldown']}t CD · {classes}\n{data['description']}")
            await ctx.send(embed=discord.Embed(title="♡ ECLIPSE · SPECIAL CODEX ♡", description="\n\n".join(lines), color=COLOR_PRIMARY))
            return

        available = get_specials_for_class(player["class_key"])
        if not special_id:
            unlocked = set(await self.db.get_rpg_specials(ctx.guild.id, ctx.author.id))
            lines = []
            shown = set()
            for sid, data in available:
                shown.add(sid)
                record = await self.db.get_rpg_special(ctx.guild.id, ctx.author.id, sid)
                if record and int(record.get("unlocked", 1)) == 0 and record.get("source") == "admin_revoke":
                    state = "⛔ REVOKED"
                elif sid in unlocked:
                    source = record.get("source", "unlock") if record else "unlock"
                    state = "✦ GRANTED" if source.startswith(("admin:", "quest:")) else "✦ READY"
                elif player["level"] >= data["level"]:
                    await self.db.unlock_rpg_special(ctx.guild.id, ctx.author.id, sid, source="level")
                    state = "✦ READY"
                else:
                    state = f"○ LOCKED · Lv.{data['level']}"
                lines.append(f"{state} {data['icon']} **{data['name']}** · {sid} · {data['cost']} MP · {data['cooldown']}t CD")
            for sid in sorted(unlocked - shown):
                data = get_special(sid)
                if not data:
                    continue
                record = await self.db.get_rpg_special(ctx.guild.id, ctx.author.id, sid)
                source = record.get("source", "grant") if record else "grant"
                lines.append(f"✦ GRANTED {data['icon']} **{data['name']}** · {sid} · {data['cost']} MP · {data['cooldown']}t CD · {source}")
            await ctx.send(embed=discord.Embed(title=f"♡ ECLIPSE · {player['class_key'].upper()} SPECIALS ♡", description="\n".join(lines) if lines else "No specials are assigned to this class.", color=COLOR_PRIMARY))
            return

        data = get_special(special_id)
        if not data:
            await ctx.send("❌ Unknown special. Use !rpg special all to open the full codex.")
            return
        owned_special = await self.db.has_rpg_special(ctx.guild.id, ctx.author.id, special_id)
        if player["class_key"] not in data["class_keys"] and not owned_special:
            await ctx.send("❌ That special is not part of your class path and has not been granted to you.")
            return
        battle = await self.db.get_rpg_battle(ctx.guild.id, ctx.author.id)
        if not battle:
            await ctx.send(f"{data['icon']} **{data['name']}**\n{data['description']}\nUnlock: **Lv.{data['level']}** · Cost: **{data['cost']} MP** · Cooldown: **{data['cooldown']} turns**\n\nStart a battle with !rpg battle, then cast it with !rpg special <id>.")
            return
        result = await combat_special(self.db, ctx.guild.id, ctx.author.id, special_id)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        if result.get("victory"):
            level_text = ""
            if result.get("level_up"):
                level_text = f"\n✦ **LEVEL UP** · Lv.{result['old_level']} → **Lv.{result['new_level']}**\n❤️ +{result['hp_gain']} Max HP · 💠 +{result['mp_gain']} Max MP"
            loot_text = f"\n🎁 **Loot:** {result['loot_name']}" if result.get("loot_name") else ""
            await ctx.send(
                f"{result['special_icon']} **{result['special_name'].upper()}**\n"
                f"{result['special_message']}\n\n"
                f"☠️ **MONSTER DEFEATED** · **{result['enemy_name']}**\n"
                f"💥 **{result['damage']} damage** · ✦ +{result['xp']} XP · 💰 +{result['gold']} gold"
                f"{loot_text}{level_text}\n"
                "🏁 **HUNT COMPLETE** — the monster has been defeated." + (f"\n🏹 Hunt Lv.{result['hunt']['hunt_level']} · +{result['hunt']['hunt_xp']} Hunt XP · 🔥 Streak {result['hunt']['streak']}" if result.get("hunt", {}).get("active") else "") + (f" · ✦ Hunt level reward +{result['hunt']['level_reward_gold']:,} gold" if result.get("hunt", {}).get("level_reward_gold") else "") + (f"\n🏅 Achievements: {len(result.get('achievements', []))} unlocked" if result.get("achievements") else "")
            )
            return
        if result.get("defeat"):
            await ctx.send(f"{result['special_icon']} **{result['special_name'].upper()}**\n{result['special_message']}\n\n☠️ The enemy survives the cast and defeats you.")
            return
        incoming = result.get("incoming", 0)
        enemy_state = " · enemy turn skipped" if result.get("enemy_skipped") else ""
        status = f"\n**Status:** {result['status']}" if result.get("status") else ""
        await ctx.send(f"{result['special_icon']} **{result['special_name'].upper()}**\n{result['special_message']}\n\n💥 **{result['damage']} damage** · Enemy ❤️ {result['enemy_hp']}/{result['enemy_max_hp']}\n💢 Incoming damage: **{incoming}**{enemy_state}{status}")

    @rpg.command(name="specialgrant", aliases=["grantspecial", "givespecial", "grant-special", "grant_special"])
    @commands.has_permissions(manage_guild=True)
    async def special_grant_command(self, ctx, member: discord.Member = None, special_id: str = None):
        if not member or not special_id:
            await ctx.send("Use !rpg specialgrant @user <special_id>.")
            return
        data = get_special(special_id)
        if not data:
            await ctx.send("❌ Unknown special. Use !rpg special all to see valid IDs.")
            return
        sid = str(special_id).strip().lower()
        await self.db.unlock_rpg_special(ctx.guild.id, member.id, sid, source=f"admin:{ctx.author.id}")
        await ctx.send(
            f"✦ **SPECIAL ACCESS GRANTED**\n"
            f"{member.mention} now has **{data['icon']} {data['name']}**.\n"
            "Class restrictions and level requirements are bypassed for this grant."
        )

    @rpg.command(name="specialrevoke", aliases=["revokespecial", "removespecial", "revoke-special", "revoke_special"])
    @commands.has_permissions(manage_guild=True)
    async def special_revoke_command(self, ctx, member: discord.Member = None, special_id: str = None):
        if not member or not special_id:
            await ctx.send("Use !rpg specialrevoke @user <special_id>.")
            return
        data = get_special(special_id)
        if not data:
            await ctx.send("❌ Unknown special. Use !rpg special all to see valid IDs.")
            return
        sid = str(special_id).strip().lower()
        await self.db.revoke_rpg_special(ctx.guild.id, member.id, sid)
        await ctx.send(
            f"✦ **SPECIAL ACCESS REVOKED**\n"
            f"{member.mention} can no longer use **{data['icon']} {data['name']}**.\n"
            "Normal class/level unlocks are also blocked until access is granted again."
        )

    @rpg.command(name="specialaccess", aliases=["specialgrants", "specialowners", "special-access", "special_access"])
    @commands.has_permissions(manage_guild=True)
    async def special_access_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        lines = []
        for sid in SPECIALS:
            record = await self.db.get_rpg_special(ctx.guild.id, target.id, sid)
            if not record:
                continue
            data = get_special(sid)
            if not data:
                continue
            if int(record.get("unlocked", 1)) == 0 and record.get("source") == "admin_revoke":
                lines.append(f"⛔ **REVOKED** · {data['icon']} **{data['name']}** · `{sid}`")
            elif int(record.get("unlocked", 1)) == 1:
                source = record.get("source", "unlock")
                lines.append(f"✦ **GRANTED** · {data['icon']} **{data['name']}** · `{sid}` · `{source}`")
        if not lines:
            await ctx.send(f"✦ **{target.display_name}** has no explicit special grants or revocations.")
            return
        await ctx.send(embed=discord.Embed(
            title=f"✦ SPECIAL ACCESS · {target.display_name}",
            description="\n".join(lines),
            color=COLOR_PRIMARY,
        ))

    @rpg.group(name="faction", aliases=["factions", "rep"], invoke_without_command=True)
    async def faction_command(self, ctx):
        rows = await faction_rows(self.db, ctx.guild.id, ctx.author.id)
        lines = []
        for row in rows:
            f = FACTIONS[row["faction_id"]]
            lines.append(f"{f['icon']} **{f['name']}** · {rep_rank(row['reputation'])} · {row['reputation']:,} REP")
        await ctx.send(embed=discord.Embed(title="🌙 ECLIPSE · FACTIONS", description="\n".join(lines), color=COLOR_PRIMARY))

    @faction_command.command(name="info")
    async def faction_info_command(self, ctx, faction_id: str = None):
        if not faction_id or faction_id.lower() not in FACTIONS:
            await ctx.send("Use !rpg faction or !rpg faction info <id>.")
            return
        f = FACTIONS[faction_id.lower()]
        regions = ", ".join(f["regions"])
        await ctx.send(
            embed=discord.Embed(
                title=f"{f['icon']} {f['name']}",
                description=(
                    f"{f['description']}\n\n"
                    f"Regions: {regions}\n"
                    f"Reward track: {f['rewards'][0][0]}"
                ),
                color=COLOR_PRIMARY,
            )
        )

    @rpg.group(name="subclass", aliases=["subclasses"], invoke_without_command=True)
    async def subclass_command(self, ctx):
        player = await get_player(self.db, ctx.guild.id, ctx.author.id)
        chosen = await get_subclass(self.db, ctx.guild.id, ctx.author.id)
        if chosen:
            data = SUBCLASSES[player["class_key"]][chosen["subclass_id"]]
            await ctx.send(f"{data['icon']} **{data['name']}**\n{data['description']}\n\nBonuses: " + ", ".join(f"+{v} {k.upper()}" for k,v in data["bonus"].items()))
            return
        options = SUBCLASSES.get(player["class_key"], {})
        lines = [f"{sid} · {d['icon']} **{d['name']}** · " + ", ".join(f"+{v} {k.upper()}" for k,v in d["bonus"].items()) for sid,d in options.items()]
        await ctx.send(f"🧬 **{player['class_key'].title()} SUBCLASSES**\n\n" + "\n".join(lines) + "\n\nUnlocks at RPG level 20. Choose with !rpg subclass choose <id>.")

    @subclass_command.command(name="choose")
    async def subclass_choose_command(self, ctx, subclass_id: str = None):
        result = await choose_subclass(self.db, ctx.guild.id, ctx.author.id, subclass_id or "")
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return
        d=result["subclass"]
        await ctx.send(f"{d['icon']} **SUBCLASS ASCENSION**\nYou are now a **{d['name']}**.\n{d['description']}")

    @rpg.group(name="housing", aliases=["house", "home"], invoke_without_command=True)
    async def housing_command(self, ctx):
        h=await get_house(self.db,ctx.guild.id,ctx.author.id)
        await ctx.send(f"{h['icon']} **{h['name']}**\n{h['description']}\n\nBonuses: " + ", ".join(f"+{v} {k.upper()}" for k,v in h["bonus"].items()))

    @housing_command.command(name="list")
    async def housing_list_command(self, ctx):
        lines=[f"{hid} · {h['icon']} **{h['name']}** · Lv.{h['level']} · {h['cost']:,} gold · " + ", ".join(f"+{v} {k.upper()}" for k,v in h["bonus"].items()) for hid,h in HOUSING.items()]
        await ctx.send("🏠 **HOUSING CODEX**\n\n" + "\n".join(lines))

    @housing_command.command(name="buy")
    async def housing_buy_command(self, ctx, house_id: str = None):
        result=await buy_house(self.db,ctx.guild.id,ctx.author.id,house_id or "")
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}"); return
        h=result["house"]
        await ctx.send(f"{h['icon']} **HOME ACQUIRED** · {h['name']}")

    @rpg.group(name="pvp", aliases=["arena"], invoke_without_command=True)
    async def pvp_command(self, ctx):
        r=await pvp_rating(self.db,ctx.guild.id,ctx.author.id)
        await ctx.send(f"⚔️ **PVP ARENA**\nRating: **{r['rating']}** · Wins: **{r['wins']}** · Losses: **{r['losses']}**\nUse !rpg pvp challenge @user.")

    @pvp_command.command(name="challenge")
    async def pvp_challenge_command(self, ctx, member: discord.Member = None):
        if not member: await ctx.send("Use !rpg pvp challenge @user."); return
        result=await create_pvp(self.db,ctx.guild.id,ctx.author.id,member.id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        await ctx.send(f"⚔️ {member.mention}, {ctx.author.display_name} challenged you. Use !rpg pvp accept @challenger.")

    @pvp_command.command(name="accept")
    async def pvp_accept_command(self, ctx, member: discord.Member = None):
        if not member: await ctx.send("Use !rpg pvp accept @challenger."); return
        result=await resolve_pvp(self.db,ctx.guild.id,member.id,ctx.author.id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        winner=ctx.guild.get_member(int(result["winner"])); loser=ctx.guild.get_member(int(result["loser"]))
        await ctx.send(f"⚔️ **ARENA RESOLVED**\n🏆 Winner: {winner.mention if winner else result['winner']}\nDefeated: {loser.mention if loser else result['loser']}\n📈 +{result['gain']} / -{result['loss']} rating")

    @pvp_command.command(name="rating")
    async def pvp_rating_command(self, ctx, member: discord.Member = None):
        target=member or ctx.author; r=await pvp_rating(self.db,ctx.guild.id,target.id)
        await ctx.send(f"⚔️ **{target.display_name}** · {r['rating']} rating · {r['wins']}W/{r['losses']}L")

    @rpg.group(name="daily", aliases=["dailyquest"], invoke_without_command=True)
    async def daily_command(self, ctx):
        row=await daily_quest(self.db,ctx.guild.id,ctx.author.id); q=next(x for x in DAILY_POOL if x[0]==row["quest_id"])
        await ctx.send(f"📜 **DAILY QUEST**\n{q[1]} · **{row['progress']}/{row['goal']}**\nReward: +{q[4]} XP · +{q[5]} gold · +50 {FACTIONS[q[6]]['name']} REP\nUse !rpg daily claim when complete.")

    @daily_command.command(name="claim")
    async def daily_claim_command(self, ctx):
        result=await claim_daily(self.db,ctx.guild.id,ctx.author.id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        q=result["quest"]; await ctx.send(f"🏆 **DAILY COMPLETE** · +{q[4]} XP · +{q[5]} gold · +50 {FACTIONS[q[6]]['name']} REP")

    @rpg.group(name="consumable", aliases=["consumables", "potion"], invoke_without_command=True)
    async def consumable_command(self, ctx):
        lines=[f"{i} · {x['icon']} **{x['name']}** · {x['cost']} gold · {x['description']}" for i,x in CONSUMABLES.items()]
        await ctx.send("🧪 **CONSUMABLES**\n\n" + "\n".join(lines) + "\n\nBuy: !rpg consumable buy <id> · Use: !rpg consumable use <id>")

    @consumable_command.command(name="buy")
    async def consumable_buy_command(self, ctx, item_id: str = None):
        result=await buy_consumable(self.db,ctx.guild.id,ctx.author.id,item_id or "")
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        await ctx.send(f"🧪 Bought **{result['item']['name']}** for **{result['item']['cost']:,}** RPG gold.")

    @consumable_command.command(name="use")
    async def consumable_use_command(self, ctx, item_id: str = None):
        result=await use_consumable(self.db,ctx.guild.id,ctx.author.id,item_id or "")
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        await ctx.send(f"{result['item']['icon']} **{result['item']['name']}** used. New {result['item']['kind'].upper()}: **{result['new']}**.")

    @rpg.command(name="enchant")
    async def enchant_command(self, ctx, item_id: str = None, enchant_id: str = None):
        if not item_id or not enchant_id: await ctx.send("Use !rpg enchant <equipped_item> <flame|ward|arcane|swift>."); return
        result=await enchant(self.db,ctx.guild.id,ctx.author.id,item_id,enchant_id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        await ctx.send(f"✨ **ENCHANTED** · {result['enchant']['name']} enchant applied to {item_id}.")

    @rpg.group(name="relationship", aliases=["relationships", "affinity"], invoke_without_command=True)
    async def relationship_command(self, ctx):
        rows=await relationship_rows(self.db,ctx.guild.id,ctx.author.id)
        lines=[f"{RELATIONSHIPS[r['npc_id']]['icon']} **{RELATIONSHIPS[r['npc_id']]['name']}** · {affinity_rank(r['affinity'])} · {r['affinity']}/1000" for r in rows]
        await ctx.send(embed=discord.Embed(title="♡ ECLIPSE · NPC RELATIONSHIPS ♡",description="\n".join(lines),color=COLOR_PRIMARY))

    @relationship_command.command(name="gift")
    async def relationship_gift_command(self, ctx, npc_id: str = None, item_id: str = None):
        if not npc_id or not item_id:
            await ctx.send("Use !rpg relationship gift <npc_id> <item_id>."); return
        result=await gift_npc(self.db,ctx.guild.id,ctx.author.id,npc_id,item_id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        await ctx.send(f"{result['npc']['icon']} **{result['npc']['name']}** appreciated the gift. Affinity: **{result['affinity']}/1000** · {affinity_rank(result['affinity'])}")

    @rpg.group(name="endgame", aliases=["end", "mythic"], invoke_without_command=True)
    async def endgame_command(self, ctx):
        a=await ascension(self.db,ctx.guild.id,ctx.author.id)
        s=await season_status(self.db,ctx.guild.id,ctx.author.id)
        await ctx.send(f"🌌 **ECLIPSE ENDGAME**\nAscension: **{a['ascension']}/10** · Ascension Points: **{a['points']}**\nSeason: **{s['season']}** · Ends <t:{int(s['ends_at'])}:R>\n\nRaids: **Mythic Lv.20** · **Celestial Lv.30**\nAscend at level 50 with \`!rpg endgame ascend\`.")

    @endgame_command.command(name="raid")
    async def endgame_raid_command(self, ctx, action: str = "status", raid_id: str = "mythic"):
        action=str(action).lower(); raid_id=str(raid_id).lower()
        if action=="start": result=await raid_start(self.db,ctx.guild.id,ctx.author.id,raid_id)
        elif action in ("advance","attack"): result=await raid_advance(self.db,ctx.guild.id,ctx.author.id,raid_id)
        else: result=await raid_status(self.db,ctx.guild.id,ctx.author.id,raid_id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        if action=="status":
            run=result["run"]; await ctx.send(f"🌌 **{raid_id.upper()} RAID**\n{run['status'] if run else 'No active run'}" + (f" · Phase {run['phase']} · {run['hp']:,} HP" if run else "")); return
        if action=="start": await ctx.send(f"🌌 **{raid_id.upper()} RAID STARTED** · {result['raid']['phases']} phases."); return
        await ctx.send(f"⚔️ Raid strike dealt **{result['damage']:,}** damage. Phase **{result['phase']}** · Boss HP **{result['hp']:,}**." + ("\n🏆 **RAID CLEARED** · Rewards granted." if result["status"]=="cleared" else ""))

    @endgame_command.command(name="ascend")
    async def endgame_ascend_command(self, ctx):
        result=await ascend(self.db,ctx.guild.id,ctx.author.id)
        if not result["ok"]: await ctx.send(f"❌ {result['message']}"); return
        await ctx.send(f"🌌 **ASCENSION {result['ascension']}** unlocked. +{result['points']} Ascension Points.")

    @endgame_command.command(name="season")
    async def endgame_season_command(self, ctx):
        s=await season_status(self.db,ctx.guild.id,ctx.author.id)
        lines=[f"<@{x['user_id']}> · **{x['points']:,}** pts" for x in s["leaderboard"]]
        await ctx.send(f"🏆 **RPG SEASON {s['season']}** · Ends <t:{int(s['ends_at'])}:R>\n" + ("\n".join(lines) if lines else "No points yet."))

    @rpg.command(name="npc", aliases=["npcs", "talk"])
    async def npc_command(self, ctx, npc_id: str = None):
        if not npc_id:
            lines = [f"{n['icon']} **{n['name']}** · {n['region'].replace('_', ' ').title()}\n{n['description']}" for n in NPCS.values()]
            await ctx.send(embed=discord.Embed(title="🌙 ECLIPSE · NPCs", description="\n\n".join(lines), color=COLOR_PRIMARY))
            return
        view = await npc_view(self.db, ctx.guild.id, ctx.author.id, npc_id)
        if not view:
            await ctx.send("Unknown NPC. Use !rpg npc to see the known characters.")
            return
        npc = view["npc"]
        lines = [f"{npc['icon']} **{npc['name']}**\n{npc['dialogue']}"]
        if view["quests"]:
            lines.append("\n**Available chapters:**")
            for qid, q, row in view["quests"]:
                lines.append(f"- {qid} · Chapter {q['chapter']} · {q['name']} · {row['progress']}/{q['goal']}")
            lines.append("\nUse !rpg claim <quest_id> after completing the objective.")
        else:
            lines.append("\nNo new chapter is waiting here yet.")
        await ctx.send(embed=discord.Embed(title=f"{npc['icon']} {npc['name']}", description="\n".join(lines), color=COLOR_PRIMARY))

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
        message = f"🏆 **{q['name']}** reward claimed · +{q['xp']} XP · +{q['gold']} gold{item_text}{extra}"
        if result.get("special_unlocked"):
            special = get_special(result["special_unlocked"])
            if special:
                message += f"\n🌟 **SPECIAL ACCESS UNLOCKED** · {special['icon']} **{special['name']}**"
        await ctx.send(message)
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
