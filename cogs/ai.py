"""
cogs/ai.py
==========
!chat — talks to Claude, with a tool the model can call to actually
post a song as an mp3 in the channel (reuses the Music cog's downloader).
"""

import logging
import os

import aiohttp
import discord
from discord.ext import commands

from cogs.music import send_song_as_file

logger = logging.getLogger("music_bot")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

MAX_HISTORY = 6

CLAUDE_TOOLS = [
    {
        "name": "send_song",
        "description": (
            "Search YouTube for a song and post it in this Discord channel "
            "as a downloadable mp3 file attachment. Use this any time the "
            "user asks you to send, play, download, or share a specific "
            "song, track, or piece of music — don't just describe it, "
            "actually call this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Song title and/or artist to search for, e.g. "
                        "'Never Gonna Give You Up Rick Astley'."
                    )
                }
            },
            "required": ["query"]
        }
    }
]

CHAT_SYSTEM_PROMPT = (
    "You are a friendly, concise Discord bot assistant. Keep replies "
    "short and casual. If the user asks you to send, play, or download "
    "a song, use the send_song tool rather than just talking about it."
)


class AIChat(commands.Cog):
    """Conversational AI chat, with the ability to send songs on request."""

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.history: dict[str, list] = {}

        if not self.api_key:
            logger.warning(
                "ANTHROPIC_API_KEY is not set — !chat will reply "
                "'AI isn't configured' until it is."
            )

    async def call_claude(self, session, messages, tools=None):
        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 500,
            "system": CHAT_SYSTEM_PROMPT,
            "messages": messages
        }

        if tools:
            payload["tools"] = tools

        async with session.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json=payload
        ) as resp:
            data = await resp.json()
            return resp.status, data

    async def send_claude_error(self, ctx, status, data):
        logger.error(f"Claude error ({status}): {data}")
        error_type = data.get("error", {}).get("type", "")

        if status == 401:
            await ctx.send(
                "❌ AI couldn't respond — the `ANTHROPIC_API_KEY` is "
                "invalid or expired."
            )
        elif status == 429:
            await ctx.send(
                "❌ AI couldn't respond — rate limit or credit balance "
                "hit. Check the Anthropic Console."
            )
        elif error_type:
            await ctx.send(f"❌ AI couldn't respond (`{error_type}`).")
        else:
            await ctx.send("❌ AI couldn't respond.")

    # ------------------------------------------------------------
    @commands.command(name="chat", aliases=["ask", "ai"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def chat(self, ctx, *, message):
        if not self.api_key:
            await ctx.send(
                "🤖 AI isn't configured — the bot's host is missing the "
                "`ANTHROPIC_API_KEY` environment variable."
            )
            return

        channel_id = str(ctx.channel.id)
        history = self.history.setdefault(channel_id, [])

        history.append({"role": "user", "content": message})
        history[:] = history[-MAX_HISTORY:]

        reply = None

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    status, data = await self.call_claude(
                        session, history, tools=CLAUDE_TOOLS
                    )

                    if status != 200:
                        await self.send_claude_error(ctx, status, data)
                        return

                    content_blocks = data.get("content") or []
                    tool_uses = [
                        b for b in content_blocks if b.get("type") == "tool_use"
                    ]

                    if tool_uses:
                        tool_results = []

                        for tool in tool_uses:
                            if tool.get("name") == "send_song":
                                query = tool.get("input", {}).get("query", "")
                                ok, result_text = await send_song_as_file(
                                    ctx.channel, query, ctx.guild
                                )
                            else:
                                ok, result_text = False, f"Unknown tool: {tool.get('name')}"

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool.get("id"),
                                "content": result_text,
                                "is_error": not ok
                            })

                        followup = history + [
                            {"role": "assistant", "content": content_blocks},
                            {"role": "user", "content": tool_results}
                        ]

                        status2, data2 = await self.call_claude(session, followup)

                        if status2 == 200:
                            final_blocks = data2.get("content") or []
                            reply = "\n".join(
                                b.get("text", "") for b in final_blocks
                                if b.get("type") == "text"
                            ).strip()

                        if not reply:
                            reply = "🎵 Done!"

                    else:
                        reply = "\n".join(
                            b.get("text", "") for b in content_blocks
                            if b.get("type") == "text"
                        ).strip()

                        if not reply:
                            await ctx.send("❌ AI returned an empty response.")
                            return

            except aiohttp.ClientError:
                logger.exception("Claude API network error")
                await ctx.send("❌ Couldn't reach the AI API — network error.")
                return
            except Exception:
                logger.exception("Claude API failed")
                await ctx.send("❌ Something went wrong.")
                return

        history.append({"role": "assistant", "content": reply})
        history[:] = history[-MAX_HISTORY:]

        for i in range(0, len(reply), 2000):
            await ctx.send(reply[i:i + 2000])

    @chat.error
    async def on_chat_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Slow down — try again in {error.retry_after:.1f}s.")


async def setup(bot):
    await bot.add_cog(AIChat(bot))
