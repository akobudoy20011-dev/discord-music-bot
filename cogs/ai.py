"""
cogs/ai.py
================
AI Chat command powered by OpenRouter.
Falls back to Google Gemini if configured.

Environment variables:
    OPENROUTER_API_KEY  Primary provider key
    OPENROUTER_MODEL    Optional model ID
    GEMINI_API_KEY      Optional fallback provider key
    GEMINI_MODEL        Optional Gemini model ID
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

        self.openrouter_key = (
            os.getenv("OPENROUTER_API_KEY") or ""
        ).strip()

        self.openrouter_model = (
            os.getenv("OPENROUTER_MODEL") or "openrouter/auto"
        ).strip()

        # Do not use ANTHROPIC_API_KEY here.
        self.gemini_key = (
            os.getenv("GEMINI_API_KEY") or ""
        ).strip()

        self.gemini_model = (
            os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
        ).strip()

        self.http_client = None
        self.gemini_client = None

        if self.openrouter_key:
            try:
                import httpx

                self.http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=10.0)
                )

                logger.info(
                    "OpenRouter client initialized successfully"
                )
            except Exception as error:
                logger.error(
                    "Could not initialize OpenRouter client: %s",
                    error,
                )
                self.http_client = None
        else:
            logger.warning("OPENROUTER_API_KEY not set")

        if self.gemini_key:
            try:
                from google import genai

                self.gemini_client = genai.Client(
                    api_key=self.gemini_key
                )

                logger.info(
                    "Gemini client initialized successfully"
                )
            except Exception as error:
                logger.error(
                    "Could not initialize Gemini client: %s",
                    error,
                )
                self.gemini_client = None
        else:
            logger.warning("GEMINI_API_KEY not set")

    async def _use_openrouter(
        self,
        question: str,
    ) -> Optional[str]:
        """Try to get a response from OpenRouter."""

        if not self.http_client or not self.openrouter_key:
            logger.warning("OpenRouter client is not available")
            return None

        try:
            response = await self.http_client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": (
                        f"Bearer {self.openrouter_key}"
                    ),
                    "Content-Type": "application/json",
                    "HTTP-Referer": (
                        "https://github.com/"
                        "akobudoy20011-dev/discord-music-bot"
                    ),
                    "X-Title": "Discord Music Bot",
                },
                json={
                    "model": self.openrouter_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a friendly, helpful Discord "
                                "bot assistant. Keep answers clear, "
                                "concise, and formatted for Discord "
                                "markdown."
                            ),
                        },
                        {
                            "role": "user",
                            "content": question,
                        },
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000,
                },
            )

            logger.info(
                "OpenRouter response status: %s",
                response.status_code,
            )

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices") or []

                if choices:
                    message = choices[0].get("message") or {}
                    result = message.get("content")

                    if (
                        isinstance(result, str)
                        and result.strip()
                    ):
                        return result

                    logger.error(
                        "OpenRouter returned no text content: %r",
                        data,
                    )
            else:
                logger.error(
                    "OpenRouter error: status %s",
                    response.status_code,
                )
                logger.error(
                    "OpenRouter response: %s",
                    response.text[:2000],
                )

        except Exception as error:
            logger.exception(
                "OpenRouter request failed: %s",
                error,
            )

        return None

    async def _use_gemini(
        self,
        question: str,
    ) -> Optional[str]:
        """Try to get a response from Google Gemini."""

        if not self.gemini_client:
            logger.warning("Gemini client is not available")
            return None

        try:
            models_to_try = [self.gemini_model]

            if self.gemini_model != "gemini-2.5-flash":
                models_to_try.append("gemini-2.5-flash")

            if "gemini-2.0-flash" not in models_to_try:
                models_to_try.append("gemini-2.0-flash")

            from google.genai import types

            for model_name in models_to_try:
                try:
                    logger.info(
                        "Trying Gemini model: %s",
                        model_name,
                    )

                    chat = await self.bot.loop.run_in_executor(
                        None,
                        lambda model=model_name:
                        self.gemini_client.chats.create(
                            model=model,
                            config=types.GenerateContentConfig(
                                system_instruction=(
                                    "You are a friendly, helpful "
                                    "Discord bot assistant. Keep "
                                    "answers clear, concise, and "
                                    "formatted for Discord markdown."
                                )
                            ),
                        ),
                    )

                    response = await self.bot.loop.run_in_executor(
                        None,
                        lambda: chat.send_message(question),
                    )

                    if response and response.text:
                        logger.info(
                            "Gemini returned a response from %s",
                            model_name,
                        )
                        return response.text

                except Exception as error:
                    logger.warning(
                        "Gemini model %s failed: %s",
                        model_name,
                        error,
                        exc_info=True,
                    )

        except Exception as error:
            logger.exception(
                "Gemini request failed: %s",
                error,
            )

        return None

    @commands.command(
        name="chat",
        aliases=["ask", "ai"],
    )
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user,
    )
    async def chat(
        self,
        ctx,
        *,
        question: str,
    ):
        """Ask the AI a question. Usage: !chat <question>"""

        if not self.http_client and not self.gemini_client:
            await ctx.send(
                "❌ AI is not configured. Set "
                "`OPENROUTER_API_KEY` or `GEMINI_API_KEY` "
                "in your environment variables."
            )
            return

        async with ctx.typing():
            response_text = None

            if self.http_client:
                logger.info("Attempting OpenRouter")
                response_text = await self._use_openrouter(
                    question
                )

            if not response_text and self.gemini_client:
                logger.info("Attempting Gemini fallback")
                response_text = await self._use_gemini(
                    question
                )

            if not response_text:
                logger.error(
                    "Both AI services failed to return a response"
                )

                await ctx.send(
                    "❌ Error communicating with AI services. "
                    "Please try again later."
                )
                return

            if len(response_text) > 1950:
                response_text = (
                    response_text[:1950]
                    + "...\n*(response truncated)*"
                )

            embed = discord.Embed(
                title="🤖 AI Response",
                description=response_text,
                color=COLOR_PRIMARY,
            )

            embed.set_footer(
                text=f"Asked by {ctx.author.display_name}"
            )

            await ctx.send(embed=embed)

    @chat.error
    async def chat_error(self, ctx, error):
        if isinstance(
            error,
            commands.MissingRequiredArgument,
        ):
            await ctx.send(
                "❌ Please provide a question. Example: "
                "`!chat What is quantum computing?`"
            )

        elif isinstance(
            error,
            commands.CommandOnCooldown,
        ):
            await ctx.send(
                f"⏳ Slow down! Try again in "
                f"{error.retry_after:.1f}s."
            )

        else:
            logger.error(
                "Unexpected !chat error: %r",
                error,
            )

            await ctx.send(
                "❌ The AI command failed unexpectedly. "
                "Please try again later."
            )

    def cog_unload(self):
        """Close the HTTP client when the cog unloads."""

        if self.http_client:
            self.bot.loop.create_task(
                self.http_client.aclose()
            )


async def setup(bot):
    await bot.add_cog(AI(bot))
