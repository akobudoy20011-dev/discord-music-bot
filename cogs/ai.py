"""
cogs/ai.py
================
AI Chat command powered by Google Gemini API.
Supports asking questions, web search grounding, and smart chat responses.
"""

import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types

from constants import COLOR_PRIMARY, footer

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
            try:
                # Runs the API call in an executor to avoid blocking Discord bot loop
                response = await self.bot.loop.run_in_executor(
                    None,
                    lambda: self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=question,
                        config=types.GenerateContentConfig(
                            system_instruction="You are a friendly, helpful Discord bot assistant. Keep answers clear, concise, and formatted for Discord markdown.",
                            temperature=0.7,
                            max_output_tokens=1000,
                        )
                    )
                )

                reply_text = response.text if response.text else "Sorry, I couldn't generate a response."

                # Discord 2000 character limit check
                if len(reply_text) > 1950:
                    reply_text = reply_text[:1950] + "...\n*(response truncated)*"

                embed = discord.Embed(
                    title="🤖 AI Response",
                    description=reply_text,
                    color=COLOR_PRIMARY
                )
                embed.set_footer(text=f"Asked by {ctx.author.display_name}")
                await ctx.send(embed=embed)

            except Exception as e:
                await ctx.send(f"❌ Error communicating with AI: `{e}`")

    @chat.error
    async def chat_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Please provide a prompt or question! Example: `!chat What is quantum computing?`")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Slow down! Try again in {error.retry_after:.1f}s.")


async def setup(bot):
    await bot.add_cog(AI(bot))
