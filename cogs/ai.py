"""
cogs/ai.py
================
AI Chat command powered by Google Gemini API.
Supports asking questions with automatic model fallback.
"""

import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types

try:
    from constants import COLOR_PRIMARY
except ImportError:
    COLOR_PRIMARY = discord.Color.blue()


class AI(commands.Cog):
    """AI Chat functionality using Google Gemini."""

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self.client = None

        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    @commands.command(name="chat", aliases=["ask", "ai"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def chat(self, ctx, *, question: str):
        """Ask the AI a question. Usage: !chat <your question>"""
        if not self.client:
            await ctx.send(
                "❌ AI isn't configured yet! Please set `GEMINI_API_KEY` in Environment Variables."
            )
            return

        async with ctx.typing():
            # List of model names to attempt in order
            models_to_try = [
                "gemini-2.5-flash",
                "gemini-1.5-flash",
                "gemini-2.0-flash",
                "gemini-flash"
            ]

            response_text = None
            last_error = None

            for model_name in models_to_try:
                try:
                    res = await self.bot.loop.run_in_executor(
                        None,
                        lambda m=model_name: self.client.models.generate_content(
                            model=m,
                            contents=question,
                            config=types.GenerateContentConfig(
                                system_instruction="You are a friendly, helpful Discord bot assistant. Keep answers clear, concise, and formatted for Discord markdown.",
                                temperature=0.7,
                                max_output_tokens=1000,
                            )
                        )
                    )
                    if res and res.text:
                        response_text = res.text
                        break
                except Exception as e:
                    last_error = e
                    continue

            if not response_text:
                await ctx.send(f"❌ Error communicating with AI: `{last_error}`")
                return

            if len(response_text) > 1950:
                response_text = response_text[:1950] + "...\n*(response truncated)*"

            embed = discord.Embed(
                title="🤖 AI Response",
                description=response_text,
                color=COLOR_PRIMARY
            )
            embed.set_footer(text=f"Asked by {ctx.author.display_name}")
            await ctx.send(embed=embed)

    @chat.error
    async def chat_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Please provide a prompt or question! Example: `!chat What is quantum computing?`")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Slow down! Try again in {error.retry_after:.1f}s.")


async def setup(bot):
    await bot.add_cog(AI(bot))
