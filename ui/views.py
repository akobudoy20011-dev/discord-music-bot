"""Reusable Discord-native interactive views."""
import discord

class CloseView(discord.ui.View):
    def __init__(self, *, timeout=120): super().__init__(timeout=timeout)
    @discord.ui.button(label="Close", emoji="♡", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done(): await interaction.response.defer()
        if interaction.message:
            try: await interaction.message.delete()
            except discord.HTTPException: pass
