"""Reusable Discord-native ECLIPSE views."""
import discord

class CloseView(discord.ui.View):
    def __init__(self, *, timeout=120): super().__init__(timeout=timeout)
    @discord.ui.button(label="Close", emoji="♡", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done(): await interaction.response.defer()
        if interaction.message:
            try: await interaction.message.delete()
            except discord.HTTPException: pass

class HomeView(discord.ui.View):
    def __init__(self, *, timeout=180): super().__init__(timeout=timeout)
    @discord.ui.button(label="Commands", emoji="୨୧", style=discord.ButtonStyle.primary)
    async def commands(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed=discord.Embed(title="♡ ECLIPSE · COMMANDS ♡", description="Use !help to return to the command center.", color=0xC8A2C8)
        embed.add_field(name="🎀 Core", value="!rank · !profile · !stats · !achievements", inline=False)
        embed.add_field(name="💗 Economy", value="!balance · !daily · !work · !pay · !shop · !inventory", inline=False)
        embed.add_field(name="🎮 Games", value="!games · !trivia · !rps · !roll · !guess · !coinflip · !slots · !blackjack · !8ball", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)
    @discord.ui.button(label="Close", emoji="×", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None); self.stop()