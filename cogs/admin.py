"""
cogs/admin.py
=============
Per-guild config (level-up channel, toggles) and basic moderation.
Everything here requires real Discord permissions — the bot checks
permissions itself in addition to whatever role setup the server has,
and no command here needs (or should ever be given) Administrator.
"""

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, COLOR_DANGER, footer


class Admin(commands.Cog):
    """Server configuration and moderation commands."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------
    @commands.group(name="config", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def config(self, ctx):
        cfg = await self.db.get_guild_config(ctx.guild.id)

        level_channel = (
            ctx.guild.get_channel(int(cfg["level_channel_id"]))
            if cfg["level_channel_id"] else None
        )

        embed = discord.Embed(title="⚙️ Server Config", color=COLOR_PRIMARY)
        embed.add_field(
            name="XP Enabled", value="✅" if cfg["xp_enabled"] else "❌", inline=True
        )
        embed.add_field(
            name="Level Announcements",
            value="✅" if cfg["level_announce"] else "❌", inline=True
        )
        embed.add_field(
            name="Game Rewards",
            value="✅" if cfg["game_rewards"] else "❌", inline=True
        )
        embed.add_field(
            name="Level-Up Channel",
            value=level_channel.mention if level_channel else "Current channel",
            inline=False
        )
        embed.set_footer(text="Use !config help to see how to change these.")

        await ctx.send(embed=embed)

    @config.command(name="help")
    async def config_help(self, ctx):
        embed = discord.Embed(
            title="⚙️ Config Commands",
            description=(
                "`!config levelchannel #channel` — set where level-ups post\n"
                "`!config xp <on/off>` — toggle chat XP\n"
                "`!config levelannounce <on/off>` — toggle level-up messages\n"
                "`!config gamerewards <on/off>` — toggle coin/XP rewards from games"
            ),
            color=COLOR_PRIMARY
        )
        await ctx.send(embed=embed)

    @config.command(name="levelchannel")
    @commands.has_permissions(manage_guild=True)
    async def config_levelchannel(self, ctx, channel: discord.TextChannel):
        await self.db.set_guild_config(
            ctx.guild.id, level_channel_id=str(channel.id)
        )
        await ctx.send(f"✅ Level-ups will now post in {channel.mention}.")

    @config.command(name="xp")
    @commands.has_permissions(manage_guild=True)
    async def config_xp(self, ctx, state: str):
        enabled = state.lower() in ("on", "true", "yes", "enable", "enabled")
        await self.db.set_guild_config(ctx.guild.id, xp_enabled=int(enabled))
        await ctx.send(f"✅ XP gain is now **{'on' if enabled else 'off'}**.")

    @config.command(name="levelannounce")
    @commands.has_permissions(manage_guild=True)
    async def config_levelannounce(self, ctx, state: str):
        enabled = state.lower() in ("on", "true", "yes", "enable", "enabled")
        await self.db.set_guild_config(ctx.guild.id, level_announce=int(enabled))
        await ctx.send(f"✅ Level-up announcements are now **{'on' if enabled else 'off'}**.")

    @config.command(name="gamerewards")
    @commands.has_permissions(manage_guild=True)
    async def config_gamerewards(self, ctx, state: str):
        enabled = state.lower() in ("on", "true", "yes", "enable", "enabled")
        await self.db.set_guild_config(ctx.guild.id, game_rewards=int(enabled))
        await ctx.send(f"✅ Game rewards are now **{'on' if enabled else 'off'}**.")

    # ------------------------------------------------------------
    # MODERATION
    # ------------------------------------------------------------

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason given"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await ctx.send("❌ You can't kick someone with an equal or higher role.")
            return

        await member.kick(reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(
            title="👢 Member Kicked",
            description=f"{member.mention} was kicked.\n**Reason:** {reason}",
            color=COLOR_DANGER
        )
        await ctx.send(embed=embed)

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason given"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await ctx.send("❌ You can't ban someone with an equal or higher role.")
            return

        await member.ban(reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{member.mention} was banned.\n**Reason:** {reason}",
            color=COLOR_DANGER
        )
        await ctx.send(embed=embed)

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        user = discord.Object(id=user_id)

        try:
            await ctx.guild.unban(user)
            await ctx.send(f"✅ Unbanned user `{user_id}`.")
        except discord.NotFound:
            await ctx.send("❌ That user isn't banned.")

    @commands.command(name="mute", aliases=["timeout"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, minutes: int, *, reason: str = "No reason given"):
        import datetime

        if minutes <= 0 or minutes > 40320:  # Discord's timeout cap is 28 days
            await ctx.send("❌ Choose between 1 and 40320 minutes.")
            return

        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")

        embed = discord.Embed(
            title="🔇 Member Muted",
            description=(
                f"{member.mention} is muted for **{minutes} minutes**.\n"
                f"**Reason:** {reason}"
            ),
            color=COLOR_DANGER
        )
        await ctx.send(embed=embed)

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason given"):
        await self.db.add_warning(ctx.guild.id, member.id, ctx.author.id, reason)
        count = len(await self.db.get_warnings(ctx.guild.id, member.id))

        embed = discord.Embed(
            title="⚠️ Member Warned",
            description=(
                f"{member.mention} has been warned (**{count}** total).\n"
                f"**Reason:** {reason}"
            ),
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)

    @commands.command(name="warnings")
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: discord.Member):
        rows = await self.db.get_warnings(ctx.guild.id, member.id)

        if not rows:
            await ctx.send(f"{member.display_name} has no warnings.")
            return

        lines = [
            f"**{i}.** {w['reason']} — <@{w['moderator_id']}>"
            for i, w in enumerate(rows[:10], start=1)
        ]

        embed = discord.Embed(
            title=f"⚠️ Warnings for {member.display_name} ({len(rows)})",
            description="\n".join(lines),
            color=discord.Color.orange()
        )
        await ctx.send(embed=footer(embed, ctx))

    @commands.command(name="clearwarnings")
    @commands.has_permissions(manage_guild=True)
    async def clearwarnings(self, ctx, member: discord.Member):
        await self.db.clear_warnings(ctx.guild.id, member.id)
        await ctx.send(f"✅ Cleared warnings for {member.display_name}.")

    @commands.command(name="clear", aliases=["purge"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int):
        if amount < 1 or amount > 100:
            await ctx.send("❌ Choose a number between 1 and 100.")
            return

        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to include the command itself
        msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.")
        await msg.delete(delay=3)

    # ------------------------------------------------------------
    @kick.error
    @ban.error
    @unban.error
    @mute.error
    @warn.error
    @warnings.error
    @clearwarnings.error
    @clear.error
    async def on_mod_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to do that.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ I don't have permission to do that here.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("❌ I couldn't find that member.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Check your arguments — see `!help`.")


async def setup(bot):
    await bot.add_cog(Admin(bot))
