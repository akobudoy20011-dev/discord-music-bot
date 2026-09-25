"""Dedicated ECLIPSE trivia game using the full persistent question pool."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import discord
from discord.ext import commands

from constants import COLOR_PRIMARY, footer

POOL_PATH = Path(__file__).resolve().parent.parent / "data" / "trivia_questions.json"
STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "trivia_state.json"
QUESTION_TIMEOUT = 30


class TriviaView(discord.ui.View):
    def __init__(self, cog, ctx, question_data):
        super().__init__(timeout=QUESTION_TIMEOUT)
        self.cog = cog
        self.ctx = ctx
        self.qdata = question_data
        self.answered = False

        labels = ["A", "B", "C", "D"]
        for idx, option in enumerate(question_data["options"]):
            button = discord.ui.Button(
                label=f"{labels[idx]}: {option}",
                style=discord.ButtonStyle.primary,
                custom_id=f"trivia:{idx}",
            )
            button.callback = self.make_callback(idx)
            self.add_item(button)

    def make_callback(self, chosen_idx):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message(
                    "❌ This trivia isn't for you!", ephemeral=True
                )
                return
            if self.answered:
                return

            self.answered = True
            self.stop()
            correct_idx = int(self.qdata["answer"])

            for item in self.children:
                item.disabled = True
                idx = int(item.custom_id.rsplit(":", 1)[1])
                if idx == correct_idx:
                    item.style = discord.ButtonStyle.success
                elif idx == chosen_idx:
                    item.style = discord.ButtonStyle.danger

            if chosen_idx == correct_idx:
                reward = int(self.qdata.get("reward", 0))
                new_balance = await self.cog.db.add_balance(
                    self.ctx.guild.id, self.ctx.author.id, reward
                )
                embed = discord.Embed(
                    title="🎉 Correct Answer!",
                    description=(
                        f"**Question:** {self.qdata['q']}\n"
                        f"✅ You picked: **{self.qdata['options'][chosen_idx]}**\n\n"
                        f"💰 Earned: **+{reward:,} coins**\n"
                        f"💳 Balance: **{new_balance:,}**"
                    ),
                    color=discord.Color.green(),
                )
            else:
                embed = discord.Embed(
                    title="❌ Wrong Answer!",
                    description=(
                        f"**Question:** {self.qdata['q']}\n"
                        f"❌ You picked: **{self.qdata['options'][chosen_idx]}**\n"
                        f"✅ Correct answer: **{self.qdata['options'][correct_idx]}**"
                    ),
                    color=discord.Color.red(),
                )

            await interaction.response.edit_message(
                embed=footer(embed, self.ctx), view=self
            )
        return callback

    async def on_timeout(self):
        if self.answered:
            return
        self.answered = True
        for item in self.children:
            item.disabled = True
        self.stop()
        try:
            await self.message.edit(
                content="⏰ Trivia expired — no answer was submitted.",
                view=self,
            )
        except (AttributeError, discord.HTTPException):
            pass


class Trivia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.questions = self._load_pool()
        self._state_lock = asyncio.Lock()
        self.state = self._load_state()

    @staticmethod
    def _load_pool():
        with POOL_PATH.open("r", encoding="utf-8") as fp:
            pool = json.load(fp)
        if not isinstance(pool, list) or len(pool) != 1450:
            raise RuntimeError(
                f"Trivia pool invalid: expected 1450 questions, got "
                f"{len(pool) if isinstance(pool, list) else 'non-list'}"
            )
        return pool

    @staticmethod
    def _load_state():
        try:
            with STATE_PATH.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
            return raw if isinstance(raw, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state_unlocked(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.state, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(STATE_PATH)

    async def _next_question(self, guild_id):
        key = str(guild_id)
        async with self._state_lock:
            state = self.state.setdefault(key, {"deck": [], "used": 0})
            deck = state.get("deck")
            if not isinstance(deck, list):
                deck = []
            if not deck:
                deck = list(range(len(self.questions)))
                random.shuffle(deck)
                state["deck"] = deck
                state["used"] = 0
            idx = int(deck.pop())
            state["used"] = int(state.get("used", 0)) + 1
            self._save_state_unlocked()
            return self.questions[idx]

    @commands.command(name="trivia")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def trivia(self, ctx):
        question = await self._next_question(ctx.guild.id)
        view = TriviaView(self, ctx, question)
        embed = discord.Embed(
            title="🧠 ECLIPSE · TRIVIA",
            description=(
                f"**{question['q']}**\n\n"
                "*Select A / B / C / D within 30 seconds!*"
            ),
            color=COLOR_PRIMARY,
        )
        message = await ctx.send(embed=footer(embed, ctx), view=view)
        view.message = message


async def setup(bot):
    await bot.add_cog(Trivia(bot))
