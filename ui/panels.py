"""Discord-native ECLIPSE panels."""
import discord
from constants import COLOR_PRIMARY

def game_room_embed():
    embed = discord.Embed(title="♡ ECLIPSE · GAME ROOM ♡", description="୨୧ choose something ୨୧", color=COLOR_PRIMARY)
    embed.add_field(name="♡ LUCK", value="!roll · !coinflip · !slots · !guess", inline=False)
    embed.add_field(name="♡ PLAY", value="!rps · !blackjack · !chamber", inline=False)
    embed.add_field(name="♡ MIND", value="!trivia · !riddle · !math · !exam · !investigator", inline=False)
    embed.add_field(name="♡ ECLIPSE", value="!8ball · !debate · !simulation", inline=False)
    embed.set_footer(text="♡ have fun · ECLIPSE")
    return embed
