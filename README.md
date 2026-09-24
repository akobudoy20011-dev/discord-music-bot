# Music Delivery Bot

A Discord bot with per-server economy, leveling, games, music (with a
real queue), an AI chat that can send songs, fun commands, and basic
moderation — split into cogs instead of one giant file.

## Project layout

```
main.py            entrypoint — loads cogs, starts the health server
database.py         async SQLite layer (per-guild data)
constants.py         achievements, rank titles, embed colors, shared helpers
cogs/
  economy.py         balance, daily streaks, work, pay, shop, leaderboard
  leveling.py         XP on message, rank, profile, xp leaderboard, achievements
  games.py            rps, dice, guess, 8ball, trivia, coinflip, slots, blackjack
  music.py            join/leave, queue, pause/resume/skip/stop, volume, loop, download
  fun.py              avatar, userinfo, serverinfo, choose, rate, ship, stats
  admin.py            !config + kick/ban/mute/warn/clear
  ai.py               !chat — Claude, with a tool to actually send a song
  help.py             categorized !help
web/server.py         Render health-check endpoint
```

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - `DISCORD_TOKEN` — required
   - `ANTHROPIC_API_KEY` — required for `!chat`/`!ask`/`!ai`
   - `YTDLP_COOKIES_FILE` — optional but likely needed (see below)
3. `python main.py`

## The YouTube "Sign in to confirm you're not a bot" error

Cloud hosts (Render, Railway, etc.) get IP-blocked by YouTube fairly
often. The fix is a cookies file:

1. Log into YouTube in your browser.
2. Export cookies with an extension like "Get cookies.txt LOCALLY"
   (Netscape format).
3. Upload `cookies.txt` to your host.
4. Set `YTDLP_COOKIES_FILE=/path/to/cookies.txt`.

## Data persistence — read this before you rely on it

`database.py` uses SQLite (`bot.db` by default), which is a big step
up from the old JSON files: atomic writes, no corruption on crash,
and proper per-server scoping. **But it's still a local file.** On
Render's free tier, local disk is wiped on every restart/redeploy, so
a redeploy will still reset everyone's coins/XP/levels.

To actually fix that you need one of:
- A Render paid plan with a **persistent disk** mounted, with
  `DB_PATH` pointed at it, or
- Migrating to a hosted Postgres (Railway/Supabase/Neon all have free
  tiers) — `database.py` is written as a single class with clean
  method boundaries specifically so this swap only touches one file.

## What I deliberately left out

The original wishlist had ~36 items. I skipped a few on purpose
rather than bolt them on badly:

- **Automod** (spam/link/caps/mention filtering) — this needs tuning
  per-server to avoid false positives; shipping it default-on would
  likely annoy your members more than help. Worth a follow-up once
  you know what abuse actually looks like in your server.
- **A second database backend (Postgres) built in now** — added
  complexity for a problem you may not hit yet (see persistence note
  above). The abstraction is there for when you need it.
- **Buttons on every embed / a full admin config UI** — implemented
  the highest-value ones (game menu, blackjack) rather than wrapping
  every command in interactive components for its own sake.

Everything else from the list — cogs split, database, per-guild
economy, cooldowns/anti-spam, leveling + ranks + profiles,
achievements, more games, daily streaks, pay/shop/inventory, a real
music queue with pause/skip/volume/loop/shuffle, better error
messages, categorized help, config command, and moderation basics —
is in here and working.
