"""Premium music entitlements and administration."""
import time
import discord
from discord.ext import commands


class Premium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _premium(self, guild_id):
        return await self.bot.db.get_music_premium(guild_id)

    @commands.command(name="premium", aliases=["premiumstatus", "musicpremium"])
    @commands.guild_only()
    async def premium(self, ctx):
        premium = await self._premium(ctx.guild.id)
        embed = discord.Embed(title="💎 ECLIPSE PREMIUM MUSIC", color=discord.Color.purple())
        if not premium:
            embed.description = (
                "This server is currently on **ECLIPSE Music Free**.\n\n"
                "Premium unlocks larger queues, 24/7 playback, premium downloads, "
                "and expanded music limits."
            )
            embed.add_field(name="Queue", value="50 tracks", inline=True)
            embed.add_field(name="24/7", value="🔒 Premium", inline=True)
            embed.add_field(name="Downloads", value="🔒 Premium", inline=True)
        else:
            remaining = max(0, int(premium["expires_at"] - time.time()))
            days, rem = divmod(remaining, 86400)
            hours = rem // 3600
            embed.description = (
                f"💎 **Premium active**\n"
                f"Expires <t:{int(premium['expires_at'])}:R>\n"
                f"Time remaining: **{days}d {hours}h**"
            )
            embed.add_field(name="Queue", value="500 tracks", inline=True)
            embed.add_field(name="24/7", value="✅", inline=True)
            embed.add_field(name="Downloads", value="✅", inline=True)
        embed.add_field(
            name="Premium features",
            value="• 500-track queues\n• 24/7 playback\n• Premium downloads\n• Expanded music limits",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="premiumgrant")
    @commands.is_owner()
    async def premium_grant(self, ctx, guild_id: int, days: int = 30):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            await ctx.send("❌ I am not currently in that server.")
            return
        if days < 1 or days > 3650:
            await ctx.send("❌ Days must be between 1 and 3650.")
            return
        premium = await self.bot.db.grant_music_premium(
            guild_id, days, granted_by=ctx.author.id
        )
        await ctx.send(
            f"💎 Premium granted to **{guild.name}** for **{days} days**. "
            f"Expires <t:{int(premium['expires_at'])}:F>."
        )

    @commands.command(name="premiumrevoke")
    @commands.is_owner()
    async def premium_revoke(self, ctx, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        await self.bot.db.revoke_music_premium(guild_id)
        await ctx.send(
            f"💎 Premium revoked for **{guild.name if guild else guild_id}**."
        )


async def setup(bot):
    await bot.add_cog(Premium(bot))
