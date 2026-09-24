                    child.disabled = True
                payout, balance = await cog._payout(ctx, result, multiplier)
                await interaction.response.edit_message(
                    embed=cog._game_embed("🔮 HIGHER / LOWER · CASHED OUT", f"Final: {current}\n\n💰 {multiplier:.2f}x payout: {payout:,}\nBalance: {balance:,}", discord.Color.green()),
                    view=view,
                )

        await ctx.send(
            embed=self._game_embed("🔮 HIGHER / LOWER", f"Starting number: {current}\nMultiplier: 1.50x\nChoose higher, lower, or cash out."),
            view=HLView(),
        )

    @commands.command(name="target")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def target(self, ctx, bet: int = 100):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        target = random.randint(1, 100)
        roll = random.randint(1, 100)
        distance = abs(target - roll)
        multiplier = 10 if distance == 0 else 5 if distance <= 3 else 3 if distance <= 7 else 1.5 if distance <= 15 else 0
        if multiplier:
            payout, balance = await self._payout(ctx, result, multiplier)
            text = f"Target: {target}\nRoll: {roll}\nDistance: {distance}\n\n🎯 {multiplier}x payout: {payout:,}\nBalance: {balance:,}"
            color = discord.Color.green()
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            text = f"Target: {target}\nRoll: {roll}\nDistance: {distance}\n\n❌ Missed.\nBalance: {balance:,}"
            color = discord.Color.red()
        await ctx.send(embed=self._game_embed("🎯 TARGET", text, color))

    @commands.command(name="reaction", aliases=["reflex"])
    async def reaction(self, ctx, bet: int = 0):
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        cog = self

        class ReactionView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=12)
                view.go = False
                view.done = False

            async def on_timeout(view):
                if view.done:
                    return
                view.done = True
                if result:
                    await cog._refund(ctx, result)
                for child in view.children:
                    child.disabled = True
                try:
                    await ctx.send(embed=cog._game_embed("⚡ REACTION · TIMED OUT", "No response. Your bet was returned.", COLOR_GOLD))
                except discord.HTTPException:
                    pass

            @discord.ui.button(label="WAIT…", style=discord.ButtonStyle.secondary)
            async def press(view, interaction, button):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This reaction test is not yours.", ephemeral=True)
                    return
                if view.done:
                    return
                view.done = True
                view.stop()
                for child in view.children:
                    child.disabled = True
                if not view.go:
                    balance = await cog._balance(ctx)
                    text = f"❌ False start.\nBalance: {balance:,}"
                    color = discord.Color.red()
                else:
                    elapsed = time.monotonic() - view.go_time
                    multiplier = 3 if elapsed <= 0.35 else 2 if elapsed <= 0.65 else 1.5 if elapsed <= 1 else 0
                    if result and multiplier:
                        payout, balance = await cog._payout(ctx, result, multiplier)
                        text = f"Reaction: {elapsed:.3f}s\n\n🎉 {multiplier}x payout: {payout:,}\nBalance: {balance:,}"
                        color = discord.Color.green()
                    elif result:
                        balance = await cog._balance(ctx)
                        text = f"Reaction: {elapsed:.3f}s\n\n❌ Too slow.\nBalance: {balance:,}"
                        color = discord.Color.red()
                    else:
                        text = f"Reaction: {elapsed:.3f}s\n\n✦ Clean run."
                        color = COLOR_PRIMARY
                await interaction.response.edit_message(embed=cog._game_embed("⚡ REACTION", text, color), view=view)

        view = ReactionView()
        msg = await ctx.send(embed=self._game_embed("⚡ REACTION TEST", "Wait for GO. Do not click early."), view=view)
        await asyncio.sleep(random.uniform(1.5, 4))
        if not view.done:
            view.go = True
            view.go_time = time.monotonic()
            view.children[0].label = "GO! ⚡"
            view.children[0].style = discord.ButtonStyle.success
            try:
                await msg.edit(view=view)
            except discord.HTTPException:
                pass

    @commands.command(name="scramble", aliases=["anagram"])
    async def scramble(self, ctx, bet: int = 0):
        words = ["eclipse", "phantom", "velvet", "sovereign", "moonlight", "crystal", "seraph", "midnight", "cathedral", "nebula", "obsidian", "astral", "kingdom", "whisper", "celestial", "starlight"]
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        word = random.choice(words)
        letters = list(word)
        for _ in range(10):
            random.shuffle(letters)
            if "".join(letters) != word:
                break
        scrambled = "".join(letters)

        await ctx.send(embed=self._game_embed("🔤 WORD SCRAMBLE", f"Unscramble: {scrambled}\nYou have 20 seconds."))
        def check(message):
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id
        try:
            answer = await self.bot.wait_for("message", timeout=20, check=check)
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time. The word was {word}.")
            return
        if answer.content.strip().lower() == word:
            if result:
                payout, balance = await self._payout(ctx, result, 3)
                await ctx.send(f"🔤 Correct — {word}.\n🎉 Payout: {payout:,} · Balance: {balance:,}")
            else:
                await ctx.send(f"🔤 Correct — {word}.")
        else:
            balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
            await ctx.send(f"❌ Wrong. The word was {word}.\nBalance: {balance:,}")

    @commands.command(name="hangman")
    async def hangman(self, ctx, bet: int = 0):
        words = ["eclipse", "phantom", "velvet", "sovereign", "moonlight", "crystal", "seraph", "midnight", "nebula", "obsidian"]
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        word = random.choice(words)
        guessed = set()
        misses = 0
        while misses < 6:
            masked = " ".join(c if c in guessed else "_" for c in word)
            if all(c in guessed for c in word):
                if result:
                    payout, balance = await self._payout(ctx, result, 4)
                    await ctx.send(f"🕯️ SOLVED — {masked}\n🎉 Payout: {payout:,} · Balance: {balance:,}")
                else:
                    await ctx.send(f"🕯️ SOLVED — {masked}")
                return
            await ctx.send(f"🕯️ HANGMAN: {masked}\nMisses: {misses}/6\nType one letter.")
            def check(message):
                return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id and len(message.content.strip()) == 1 and message.content.isalpha()
            try:
                answer = await self.bot.wait_for("message", timeout=20, check=check)
            except asyncio.TimeoutError:
                await ctx.send(f"⏰ Time. Word was {word}.")
                return
            letter = answer.content.lower()
            if letter in guessed:
                continue
            guessed.add(letter)
            if letter not in word:
                misses += 1
        balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
        await ctx.send(f"🕯️ HANGMAN LOST — word was {word}.\nBalance: {balance:,}")

    @commands.command(name="mastermind", aliases=["codebreaker"])
    async def mastermind(self, ctx, bet: int = 0):
        if bet:
            ok, result = await self._take_bet(ctx, bet)
            if not ok:
                await ctx.send(f"❌ {result}")
                return
        else:
            result = 0
        code = "".join(random.sample("0123456789", 4))
        await ctx.send(embed=self._game_embed("🧩 MASTERMIND", "Break the 4-digit code. No repeated digits. You have 8 guesses.\nReply with four unique digits."))
        def check(message):
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id and message.content.isdigit() and len(message.content) == 4 and len(set(message.content)) == 4
        for attempt in range(1, 9):
            try:
                answer = await self.bot.wait_for("message", timeout=25, check=check)
            except asyncio.TimeoutError:
                await ctx.send(f"⏰ Time. Code was {code}.")
                return
            guess = answer.content
            exact = sum(a == b for a, b in zip(code, guess))
            misplaced = sum(min(code.count(d), guess.count(d)) for d in set(guess)) - exact
            if exact == 4:
                if result:
                    payout, balance = await self._payout(ctx, result, 6)
                    await ctx.send(f"🧩 CODE BROKEN in {attempt} guesses.\n🎉 Payout: {payout:,} · Balance: {balance:,}")
                else:
                    await ctx.send(f"🧩 CODE BROKEN: {code}")
                return
            await ctx.send(f"Attempt {attempt}/8 · Exact: {exact} · Misplaced: {misplaced}")
        balance = (await self.db.get_user(ctx.guild.id, ctx.author.id))["balance"]
        await ctx.send(f"🧩 LOCKED — code was {code}.\nBalance: {balance:,}")

    @commands.command(name="mines")
    async def mines(self, ctx, bet: int):
        ok, result = await self._take_bet(ctx, bet)
        if not ok:
            await ctx.send(f"❌ {result}")
            return
        mine_positions = set(random.sample(range(20), 4))
        revealed = set()
        multiplier = 1.0
        cog = self

        class MinesView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=120)
                view.done = False
                for index in range(20):
                    button = discord.ui.Button(label="·", style=discord.ButtonStyle.secondary, row=index // 5)
                    async def reveal(interaction, idx=index, btn=button):
                        nonlocal multiplier
                        if interaction.user.id != ctx.author.id:
                            await interaction.response.send_message("❌ This minefield is not yours.", ephemeral=True)
                            return
                        if view.done or idx in revealed:
                            return
                        revealed.add(idx)
                        if idx in mine_positions:
                            view.done = True
                            view.stop()
                            for child in view.children:
                                child.disabled = True
                            for pos, child in enumerate(view.children[:20]):
                                child.label = "💣" if pos in mine_positions else ("💎" if pos in revealed else "·")
                            balance = await cog._balance(ctx)
                            await interaction.response.edit_message(
                                embed=cog._game_embed("💣 MINES · DETONATED", f"Safe tiles: {len(revealed)-1}\n\n❌ Mine hit.\nBalance: {balance:,}", discord.Color.red()),
                                view=view,
                            )
                            return
                        btn.label = "💎"
                        btn.style = discord.ButtonStyle.success
                        multiplier = min(8.0, multiplier + 0.35)
                        if len(revealed) == 16:
                            view.done = True
                            view.stop()
                            for child in view.children:
                                child.disabled = True
                            payout, balance = await cog._payout(ctx, result, multiplier)
                            text = f"All safe tiles cleared.\n\n🎉 {multiplier:.2f}x payout: {payout:,}\nBalance: {balance:,}"
                            color = discord.Color.gold()