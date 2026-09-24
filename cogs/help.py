"""ECLIPSE command center."""
import discord
from discord.ext import commands
from ui.views import HomeView
from constants import COLOR_PRIMARY

class Help(commands.Cog):
    def __init__(self, bot): self.bot=bot

    @commands.command(name="help", aliases=["commands"])
    async def help_command(self, ctx):
        embed=discord.Embed(title="♡ ECLIPSE · COMMAND CENTER ♡", description="୨୧ your gateway into the system ୨୧\n\nChoose a category below or use a command directly.", color=COLOR_PRIMARY)
        embed.add_field(name="🎀 CORE", value="!rank · !profile · !identity · !titles · !title · !achievements · !gameroom", inline=False)
        embed.add_field(name="💗 ECONOMY", value="!balance · !daily · !work · !pay · !shop · !buy · !inventory · !bank · !deposit · !withdraw · !interest", inline=False)
        embed.add_field(name="🎮 GAMES", value="!games · !arcade · !dailies · !claimdaily · !gamestats · !arcadeprofile · !tournament · !tournament play <match> · !gameleaderboard · !ttt · !connect4 · !dicebattle · !trivia · !rps · !roll · !guess · !coinflip · !slots · !blackjack · !8ball · !chamber", inline=False)
        embed.add_field(name="⚔️ RPG", value="!rpg · !rpg profile · !rpg class · !rpg world · !rpg travel · !rpg explore · !rpg discoveries · !rpg town · !rpg adventure · !rpg battle · !rpg quests", inline=False)
        embed.add_field(name="🌌 WORLD", value="!worldevent · !worldevent contribute <amount>", inline=False)
        embed.add_field(name="🎵 MUSIC", value="!play · !queue · !nowplaying · !pause · !resume · !skip · !stop · !remove · !move · !clear · !shuffle · !loop · !volume · !autoplay · !247 · !musicsettings · !djrole · !download", inline=False)
        embed.add_field(name="🛡️ STAFF", value="!kick · !ban · !mute · !warn · !clear · !config", inline=False)
        embed.add_field(name="🤖 AI", value="!chat · !ask · !ai", inline=False)
        embed.set_footer(text="୨୧ ECLIPSE · beyond the ordinary")
        await ctx.send(embed=embed, view=HomeView())

async def setup(bot): await bot.add_cog(Help(bot))