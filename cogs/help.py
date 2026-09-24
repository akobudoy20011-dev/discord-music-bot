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
        embed.add_field(name="🎮 GAMES", value="!games · !arcade\n୨୧ The Game Center contains the full solo + multiplayer catalog, rules, commands and how-to-play cards.\n!trivia · !rps · !roll · !guess · !coinflip · !slots · !blackjack · !8ball · !ttt · !connect4 · !dicebattle", inline=False)
        embed.add_field(name="⚔️ RPG", value="!rpg · !rpg help\n୨୧ The RPG Codex contains every RPG command, grouped by world, combat, quests, gear and progression.\n!companion · !guild · !worldboss are connected RPG systems.", inline=False)
        embed.add_field(name="🌌 WORLD", value="!worldevent · !worldevent contribute <amount>", inline=False)
        embed.add_field(name="🎵 MUSIC", value="!play · !queue · !nowplaying · !pause · !resume · !skip · !stop · !remove · !move · !queueclear · !qclear · !shuffle · !loop · !volume · !autoplay · !247 · !musicsettings · !djrole · !download", inline=False)
        embed.add_field(name="🛡️ STAFF", value="!kick · !ban · !mute · !warn · !clear · !config", inline=False)
        embed.add_field(name="🤖 AI", value="!chat · !ask · !ai", inline=False)
        embed.set_footer(text="୨୧ ECLIPSE · beyond the ordinary")
        await ctx.send(embed=embed, view=HomeView())

async def setup(bot): await bot.add_cog(Help(bot))