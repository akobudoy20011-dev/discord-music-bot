"""
cogs/ai.py
================
AI Chat command powered by OpenRouter API (supports multiple models).
Falls back to Google Gemini if configured.
"""

import os
import logging
import discord
from discord.ext import commands
from typing import Optional

logger = logging.getLogger("music_bot")

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
        self.http_client = None
        self.gemini_client = None
        
        # Initialize OpenRouter client if key is available
        if self.openrouter_key:
            try:
                import httpx
                self.http_client = httpx.AsyncClient(
                    timeout=30.0
                )
                logger.info("✅ OpenRouter client initialized successfully")
            except Exception as e:
                logger.error(f"❌ Could not initialize OpenRouter client: {e}")
                self.http_client = None
        else:
            logger.warning("⚠️ OPENROUTER_API_KEY not set")
        
        # Fallback to Gemini if available
        if self.gemini_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.gemini_key)
                logger.info("✅ Gemini client initialized successfully")
            except Exception as e:
                logger.error(f"❌ Could not initialize Gemini client: {e}")
                self.gemini_client = None
        else:
            logger.warning("⚠️ GEMINI_API_KEY not set")

    async def _use_openrouter(self, question: str) -> Optional[str]:
        """Try to get a response from OpenRouter."""
        if not self.http_client or not self.openrouter_key:
            logger.warning("OpenRouter client not available")
            return None
        
        try:
            logger.info(f"Calling OpenRouter API...")
            response = await self.http_client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "HTTP-Referer": "https://github.com/akobudoy20011-dev/discord-music-bot",
                    "X-Title": "Discord Music Bot",
                },
                json={
                    "model": "openrouter/auto",  # Uses best available free model
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
            
            logger.info(f"OpenRouter response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("choices") and len(data["choices"]) > 0:
                    result = data["choices"][0]["message"]["content"]
                    logger.info("✅ OpenRouter returned a response")
                    return result
            else:
                logger.error(f"OpenRouter error: Status {response.status_code}")
                logger.error(f"Response: {response.text}")
        except Exception as e:
            logger.exception(f"❌ OpenRouter error: {e}")
        
        return None

    async def _use_gemini(self, question: str) -> Optional[str]:
        """Try to get a response from Google Gemini (fallback) using Chat API (recommended)."""
        if not self.gemini_client:
            logger.warning("Gemini client not available")
            return None
        
        try:
            models_to_try = [
                "models/gemini-2.0-flash",
                "models/gemini-1.5-flash",
            ]
            
            for model_name in models_to_try:
                try:
                    logger.info(f"Trying Gemini model: {model_name}")
                    # Use Chat API (recommended by Google instead of generate_content)
                    chat = await self.bot.loop.run_in_executor(
                        None,
                        lambda m=model_name: self.gemini_client.chats.create(model=m)
                    )
                    
                    response = await self.bot.loop.run_in_executor(
                        None,
                        lambda: chat.send_message(
                            question,
                            system_instruction="You are a friendly, helpful Discord bot assistant. Keep answers clear, concise, and formatted for Discord markdown.",
                        )
                    )
                    
                    if response and response.text:
                        logger.info(f"✅ Gemini returned a response from {model_name}")
                        return response.text
                except Exception as e:
                    logger.warning(f"Model {model_name} failed: {e}")
                    continue
        except Exception as e:
            logger.exception(f"❌ Gemini error: {e}")
        
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
                logger.info("Attempting OpenRouter...")
                response_text = await self._use_openrouter(question)
            
            # Fall back to Gemini if OpenRouter didn't work
            if not response_text and self.gemini_client:
                logger.info("Attempting Gemini fallback...")
                response_text = await self._use_gemini(question)
            
            if not response_text:
                logger.error("❌ Both AI services failed to return a response")
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
