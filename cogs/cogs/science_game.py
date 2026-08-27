"""
AI-generated science guessing game.

Add "cogs.science_game" to the COGS list in main.py.
Required environment variable: GEMINI_API_KEY
Optional environment variable: GEMINI_MODEL
"""

import asyncio
import json
import os
import random
import re

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, footer


CATEGORIES = [
    "Human Anatomy",
    "Brain Science",
    "Ecology",
    "Biology",
    "Earth Science",
    "Space and Physics",
    "Chemistry",
    "Animal Science",
    "Environmental Science",
    "Ocean Science",
    "Genetics",
    "Microbiology",
]

REWARDS = {
    "easy": 300,
    "medium": 450,
    "hard": 650,
}


def normalize_answer(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class ScienceGameAI(commands.Cog):
    """A fresh AI-generated science clue every round."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.active_channels = set()
        self.recent_answers = {}
        self.last_categories = {}
        self.ai_client = None
        self.genai_types = None

        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

        if api_key:
            try:
                from google import genai
                from google.genai import types

                self.ai_client = genai.Client(api_key=api_key)
                self.genai_types = types

            except Exception as error:
                print(f"Guess It could not start Gemini: {error}")

    async def create_question(self, guild_id):
        if not self.ai_client:
            return None

        previous_category = self.last_categories.get(guild_id)

        possible_categories = [
            category
            for category in CATEGORIES
            if category != previous_category
        ]

        category = random.choice(
            possible_categories or CATEGORIES
        )

        difficulty = random.choice(list(REWARDS))
        recent = self.recent_answers.setdefault(guild_id, [])

        recent_answers = ", ".join(recent[-25:]) or "none"

        prompt = f"""
Create one accurate science guessing-game question.

Category: {category}
Difficulty: {difficulty}

Do not repeat these recent answers:
{recent_answers}

Return valid JSON only:
{{
  "clue": "one or two sentence clue",
  "answer": "best short answer",
  "alternate_answers": ["common alternate answer"]
}}

Rules:
- Do not use multiple choice.
- Do not reveal the answer inside the clue.
- Make the clue fair for the requested difficulty.
- Use real, verifiable science.
- Do not invent facts or terminology.
"""

        try:
            response = await self.bot.loop.run_in_executor(
                None,
                lambda: self.ai_client.models.generate_content(
                    model=os.getenv(
                        "GEMINI_MODEL",
                        "gemini-2.5-flash",
                    ),
                    contents=prompt,
                    config=self.genai_types.GenerateContentConfig(
                        system_instruction=(
                            "You create accurate educational questions. "
                            "Return JSON only, with no markdown."
                        ),
                        temperature=0.9,
                        max_output_tokens=300,
                    ),
                ),
            )

            text = (response.text or "").strip()

            text = re.sub(
                r"^```(?:json)?\s*",
                "",
                text,
            )

            text = re.sub(
                r"\s*```$",
                "",
                text,
            )

            data = json.loads(text)

            clue = data.get("clue")
            answer = data.get("answer")
            alternates = data.get(
                "alternate_answers",
                [],
            )

            if (
                not isinstance(clue, str)
                or not clue.strip()
                or not isinstance(answer, str)
                or not answer.strip()
            ):
                return None

            if not isinstance(alternates, list):
                alternates = []

            answers = [answer.strip()]

            answers.extend(
                item.strip()
                for item in alternates
                if isinstance(item, str)
                and item.strip()
            )

            unique_answers = []
            seen = set()

            for item in answers:
                normalized = normalize_answer(item)

                if normalized and normalized not in seen:
                    seen.add(normalized)
                    unique_answers.append(item)

            fingerprint = normalize_answer(answer)

            if fingerprint in recent:
                return None

            recent.append(fingerprint)

            del recent[:-50]

            self.last_categories[guild_id] = category

            return {
                "category": category,
                "difficulty": difficulty,
                "clue": clue.strip(),
                "answers": unique_answers[:5],
                "display_answer": answer.strip(),
                "reward": REWARDS[difficulty],
            }

        except Exception as error:
            print(
                f"Guess It question generation failed: {error}"
            )
            return None

    @commands.command(
        name="guessit",
        aliases=[
            "scienceguess",
            "challenge",
        ],
    )
    @commands.cooldown(
        1,
        20,
        commands.BucketType.user,
    )
    async def guessit(self, ctx):
        """Start an AI-generated science guessing challenge."""

        if ctx.channel.id in self.active_channels:
            await ctx.send(
                "⏳ A Guess It challenge is already running "
                "in this channel."
            )
            return

        self.active_channels.add(ctx.channel.id)

        try:
            async with ctx.typing():
                question = await self.create_question(
                    ctx.guild.id
                )

            if not question:
                await ctx.send(
                    "❌ I could not create a question right now. "
                    "Please check that `GEMINI_API_KEY` is configured "
                    "and try again."
                )
                return

            embed = discord.Embed(
                title="🔬 Guess It!",
                description=(
                    f"**Category:** {question['category']}\n"
                    f"**Difficulty:** "
                    f"{question['difficulty'].title()}\n\n"
                    f"🧩 **Clue:** {question['clue']}\n\n"
                    "Type your answer in this channel. "
                    "The first correct answer wins!\n"
                    "⏱️ You have **30 seconds**."
                ),
                color=COLOR_PRIMARY,
            )

            await ctx.send(
                embed=footer(embed, ctx)
            )

            valid_answers = {
                normalize_answer(answer)
                for answer in question["answers"]
            }

            def check(message):
                return (
                    message.channel.id == ctx.channel.id
                    and not message.author.bot
                )

            while True:
                try:
                    message = await self.bot.wait_for(
                        "message",
                        timeout=30,
                        check=check,
                    )

                except asyncio.TimeoutError:
                    await ctx.send(
                        f"⌛ Time's up! The answer was "
                        f"**{question['display_answer']}**."
                    )
                    return

                guessed_answer = normalize_answer(
                    message.content
                )

                if guessed_answer not in valid_answers:
                    continue

                balance = await self.db.add_balance(
                    ctx.guild.id,
                    message.author.id,
                    question["reward"],
                )

                winner = discord.Embed(
                    title="🎉 Correct!",
                    description=(
                        f"{message.author.mention} solved it!\n\n"
                        f"✅ Answer: "
                        f"**{question['display_answer']}**\n"
                        f"💰 Reward: "
                        f"**+{question['reward']:,} coins**\n"
                        f"💳 Balance: **{balance:,}**"
                    ),
                    color=discord.Color.green(),
                )

                await ctx.send(embed=winner)
                return

        finally:
            self.active_channels.discard(
                ctx.channel.id
            )


async def setup(bot):
    await bot.add_cog(ScienceGameAI(bot))
