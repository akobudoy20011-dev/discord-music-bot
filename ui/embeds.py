"""Consistent Discord embeds for the ECLIPSE design language."""
import discord
from constants import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, COLOR_MUSIC

def eclipse_embed(title, description=None, *, color=COLOR_PRIMARY):
    return discord.Embed(title=f"♡ {title}", description=description, color=color)

def success(title, description=None): return eclipse_embed(title, description, color=COLOR_SUCCESS)
def warning(title, description=None): return eclipse_embed(title, description, color=COLOR_WARNING)
def danger(title, description=None): return eclipse_embed(title, description, color=COLOR_DANGER)
def music(title, description=None): return eclipse_embed(title, description, color=COLOR_MUSIC)

def footer(embed, ctx):
    embed.set_footer(text=f"୨୧ {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    return embed
