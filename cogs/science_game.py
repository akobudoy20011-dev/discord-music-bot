"""
Standalone science guessing game for the Discord bot.

Add "cogs.science_game" to the COGS list in main.py.
Command: !guessit
Aliases: !scienceguess, !challenge
"""

import asyncio
import random
import re

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, footer


QUESTIONS = [
    {
        "category": "Human Anatomy",
        "clue": "I pump blood through the human body. What am I?",
        "answers": ["heart", "the heart"],
        "display_answer": "the heart",
        "reward": 350,
    },
    {
        "category": "Human Anatomy",
        "clue": "I am the largest organ of the human body and protect what is underneath me. What am I?",
        "answers": ["skin", "the skin"],
        "display_answer": "the skin",
        "reward": 350,
    },
    {
        "category": "Human Anatomy",
        "clue": "I am the bone that protects the brain. What am I?",
        "answers": ["skull", "the skull", "cranium", "the cranium"],
        "display_answer": "the skull",
        "reward": 400,
    },
    {
        "category": "Brain Science",
        "clue": "I coordinate balance, posture, and precise movement. Which brain part am I?",
        "answers": ["cerebellum", "the cerebellum"],
        "display_answer": "the cerebellum",
        "reward": 450,
    },
    {
        "category": "Brain Science",
        "clue": "I am strongly involved in forming and recalling memories. Which brain structure am I?",
        "answers": ["hippocampus", "the hippocampus"],
        "display_answer": "the hippocampus",
        "reward": 500,
    },
    {
        "category": "Brain Science",
        "clue": "I am a chemical messenger associated with reward, motivation, and movement. What am I?",
        "answers": ["dopamine"],
        "display_answer": "dopamine",
        "reward": 450,
    },
    {
        "category": "Ecology",
        "clue": "I describe two species helping each other, such as bees pollinating flowers. What relationship am I?",
        "answers": ["mutualism"],
        "display_answer": "mutualism",
        "reward": 450,
    },
    {
        "category": "Ecology",
        "clue": "I am the role an organism has in its ecosystem, including how it gets food and survives. What am I?",
        "answers": ["niche", "ecological niche", "the niche"],
        "display_answer": "an ecological niche",
        "reward": 500,
    },
    {
        "category": "Ecology",
        "clue": "I am the process where plants release water vapor through tiny openings in their leaves. What am I?",
        "answers": ["transpiration"],
        "display_answer": "transpiration",
        "reward": 500,
    },
    {
        "category": "Biology",
        "clue": "I am called the powerhouse of the cell because I produce much of its usable energy. What am I?",
        "answers": ["mitochondria", "mitochondrion", "the mitochondria"],
        "display_answer": "the mitochondria",
        "reward": 400,
    },
    {
        "category": "Biology",
        "clue": "I store most genetic instructions in living things. What molecule am I?",
        "answers": ["dna", "deoxyribonucleic acid"],
        "display_answer": "DNA",
        "reward": 350,
    },
    {
        "category": "Biology",
        "clue": "I am the process plants use light energy to make sugar. What am I?",
        "answers": ["photosynthesis"],
        "display_answer": "photosynthesis",
        "reward": 350,
    },
    {
        "category": "Earth Science",
        "clue": "I am the thick layer of Earth between the crust and the core. What am I?",
        "answers": ["mantle", "the mantle"],
        "display_answer": "the mantle",
        "reward": 400,
    },
    {
        "category": "Earth Science",
        "clue": "I divide Earth into the Northern and Southern Hemispheres. What imaginary line am I?",
        "answers": ["equator", "the equator"],
        "display_answer": "the equator",
        "reward": 350,
    },
    {
        "category": "Earth Science",
        "clue": "I describe the continuous movement of water between the atmosphere, land, and oceans. What cycle am I?",
        "answers": [
            "water cycle",
            "the water cycle",
            "hydrologic cycle",
            "hydrological cycle",
        ],
        "display_answer": "the water cycle",
        "reward": 400,
    },
    {
        "category": "Space and Physics",
        "clue": "I am the force that attracts objects with mass toward one another. What am I?",
        "answers": ["gravity", "gravitation"],
        "display_answer": "gravity",
        "reward": 350,
    },
    {
        "category": "Space and Physics",
        "clue": "I am famous for my visible rings made mostly of ice and rock. Which planet am I?",
        "answers": ["saturn", "planet saturn"],
        "display_answer": "Saturn",
        "reward": 300,
    },
    {
        "category": "Space and Physics",
        "clue": "I am the nearest star to Earth. What am I?",
        "answers": ["sun", "the sun"],
        "display_answer": "the Sun",
        "reward": 300,
    },
]


def normalize_answer(value):
    """Ignore capitalization, punctuation, and extra spaces."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class ScienceGame(commands.Cog):
    """A server-wide clue-based science guessing game."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.active_channels = set()
        self.last_category = None

    @commands.command(
        name="guessit",
        aliases=["scienceguess", "challenge"],
    )
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def guessit(self, ctx):
        """Start a clue-based science challenge."""

        if ctx.channel.id in self.active_channels:
            await ctx.send(
                "⏳ A Guess It challenge is already running in this channel."
            )
            return

        self.active_channels.add(ctx.channel.id)

        try:
            available = [
                question
                for question in QUESTIONS
                if question["category"] != self.last_category
            ]

            question = random.choice(available or QUESTIONS)
            self.last_category = question["category"]

            embed = discord.Embed(
                title="🔬 Guess It!",
                description=(
                    f"**Category:** {question['category']}\n\n"
                    f"🧩 **Clue:** {question['clue']}\n\n"
                    "Type your answer in this channel. "
                    "The first correct answer wins!\n"
                    "⏱️ You have **30 seconds**."
                ),
                color=COLOR_PRIMARY,
            )

            await ctx.send(embed=footer(embed, ctx))

            def check(message):
                return (
                    message.channel.id == ctx.channel.id
                    and not message.author.bot
                )

            valid_answers = {
                normalize_answer(answer)
                for answer in question["answers"]
            }

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

                if normalize_answer(message.content) not in valid_answers:
                    continue

                new_balance = await self.db.add_balance(
                    ctx.guild.id,
                    message.author.id,
                    question["reward"],
                )

                winner = discord.Embed(
                    title="🎉 Correct!",
                    description=(
                        f"{message.author.mention} solved it!\n\n"
                        f"✅ Answer: **{question['display_answer']}**\n"
                        f"💰 Reward: **+{question['reward']:,} coins**\n"
                        f"💳 Balance: **{new_balance:,}**"
                    ),
                    color=discord.Color.green(),
                )

                await ctx.send(embed=winner)
                return

        finally:
            self.active_channels.discard(ctx.channel.id)


async def setup(bot):
    await bot.add_cog(ScienceGame(bot))
