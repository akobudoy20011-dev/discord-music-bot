"""
cogs/ai.py
================
AI Chat command powered by OpenRouter API (supports multiple models).
Falls back to Google Gemini if configured.
"""

import os
import discord
from discord.ext import commands

try:
    from constants import COLOR_PRIMARY
except ImportError:
    COLOR_PRIMARY = discord.Color.blue()


class AI(commands.Cog):
    """AI Chat functionality using OpenRouter or Google Gemini."""

    def __init__(self, bot):
        self.bot = bot
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        
        # Initialize OpenRouter client if key is available
        if self.openrouter_key:
            try:
                import httpx
                self.http_client = httpx.AsyncClient(
                    base_url="https://openrouter.ai/api/v1",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "HTTP-Referer": "https://github.com/akobudoy20011-dev/discord-music-bot",
                    }
                )
            except Exception as e:
                print(f"Warning: Could not initialize OpenRouter client: {e}")
                self.http_client = None
        else:
            self.http_client = None
        
        # Fallback to Gemini if available
        if self.gemini_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.gemini_key)
            except Exception as e:
                print(f"Warning: Could not initialize Gemini client: {e}")
                self.gemini_client = None
        else:
            self.gemini_client = None

    async def _use_openrouter(self, question: str) -> str | None:
        """Try to get a response from OpenRouter."""
        if not self.http_client:
            return None
        
        try:
            import json
            response = await self.http_client.post(
                "/chat/completions",
                json={
                    "model": "openrouter/auto",  # Uses best available model
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a friendly, helpful Discord bot assistant. Keep answers clear, concise, and formatted for Discord markdown."
                        },
                        {
                            "role": "user",
                            "content": question
                        }
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000,
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("choices") and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"OpenRouter error: {e}")
        
        return None

    async def _use_gemini(self, question: str) -> str | None:
        """Try to get a response from Google Gemini (fallback)."""
        if not self.gemini_client:
            return None
        
        try:
            from google.genai import types
            
            models_to_try = [
                "models/gemini-2.0-flash",
                "models/gemini-1.5-flash",
            ]
            
            for model_name in models_to_try:
                try:
                    res = await self.bot.loop.run_in_executor(
                        None,
                        lambda m=model_name: self.gemini_client.models.generate_content(
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
                        return res.text
                except Exception as e:
                    continue
        except Exception as e:
            print(f"Gemini error: {e}")
        
        return None

    @commands.command(name="chat", aliases=["ask", "ai"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def chat(self, ctx, *, question: str):
        """Ask the AI a question. Usage: !chat <your question>"""
        if not self.http_client and not self.gemini_client:
            await ctx.send(
                "❌ AI isn't configured yet! Please set `OPENROUTER_API_KEY` or `GEMINI_API_KEY` in Environment Variables."
            )
            return

        async with ctx.typing():
            response_text = None
            
            # Try OpenRouter first (primary)
            if self.http_client:
                response_text = await self._use_openrouter(question)
            
            # Fall back to Gemini if OpenRouter didn't work
            if not response_text and self.gemini_client:
                response_text = await self._use_gemini(question)
            
            if not response_text:
                await ctx.send("❌ Error communicating with AI services. Please try again later.")
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
