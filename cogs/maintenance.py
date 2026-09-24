"""Bot maintenance and disk-cache cleanup."""

import asyncio
import os
import shutil
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks

DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_MAX_AGE_HOURS = 6

# Only bot-owned/cache-like locations are touched. The database, cookies,
# source files, logs, and arbitrary user files are never targeted.
CACHE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "cache",
    "runtime_cache",
    "tmp",
    "temp",
}

TEMP_FILE_SUFFIXES = {
    ".part",
    ".ytdl",
    ".tmp",
    ".temp",
}


class Maintenance(commands.Cog):
    """Keeps generated Python/cache artifacts from consuming disk space."""

    def __init__(self, bot):
        self.bot = bot
        self.started_at = time.time()
        self.cache_cleaner.start()

    def cog_unload(self):
        self.cache_cleaner.cancel()

    def _cache_roots(self):
        root = Path.cwd()
        roots = []

        # Explicit bot-owned cache locations.
        configured = os.getenv("BOT_CACHE_DIRS", "")
        for raw in configured.split(","):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw).expanduser())

        # Known cache directories anywhere in the repository.
        for path in root.rglob("*"):
            if path.is_dir() and path.name in CACHE_DIR_NAMES:
                roots.append(path)

        # Deduplicate without resolving arbitrary missing paths.
        unique = []
        seen = set()
        for path in roots:
            key = str(path.absolute())
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    def clean_cache(self, max_age_hours=DEFAULT_MAX_AGE_HOURS):
        cutoff = time.time() - (float(max_age_hours) * 3600)
        removed_files = 0
        removed_dirs = 0
        removed_bytes = 0

        for directory in self._cache_roots():
            if not directory.exists() or not directory.is_dir():
                continue

            # Python/cache directories can be safely rebuilt.
            if directory.name in CACHE_DIR_NAMES:
                try:
                    size = sum(
                        p.stat().st_size
                        for p in directory.rglob("*")
                        if p.is_file()
                    )
                except OSError:
                    size = 0
                try:
                    shutil.rmtree(directory)
                    removed_dirs += 1
                    removed_bytes += size
                except OSError:
                    pass
                continue

            # Configured custom cache roots: only delete stale files.
            for path in list(directory.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                    if stat.st_mtime >= cutoff:
                        continue
                    if path.suffix.lower() not in TEMP_FILE_SUFFIXES:
                        continue
                    path.unlink()
                    removed_files += 1
                    removed_bytes += stat.st_size
                except OSError:
                    continue

        return removed_files, removed_dirs, removed_bytes

    @staticmethod
    def _format_bytes(value):
        value = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    @tasks.loop(minutes=DEFAULT_INTERVAL_MINUTES)
    async def cache_cleaner(self):
        try:
            result = await asyncio.to_thread(self.clean_cache)
            files, dirs, size = result
            if files or dirs:
                print(
                    f"[maintenance] cache cleanup removed "
                    f"{files} file(s), {dirs} cache dir(s), "
                    f"{self._format_bytes(size)}."
                )
        except Exception as exc:
            print(f"[maintenance] cache cleanup failed: {exc}")

    @cache_cleaner.before_loop
    async def before_cache_cleaner(self):
        await self.bot.wait_until_ready()

    @commands.command(name="cacheclean", aliases=["cleancache", "cleanupcache"])
    @commands.is_owner()
    async def cacheclean(self, ctx, hours: float = DEFAULT_MAX_AGE_HOURS):
        """Owner-only manual cache cleanup."""
        hours = max(1.0, min(hours, 168.0))
        files, dirs, size = await asyncio.to_thread(self.clean_cache, hours)

        embed = discord.Embed(
            title="🧹 Cache Cleanup",
            description=(
                f"Removed **{files}** stale file(s) and **{dirs}** cache directorie(s).\n"
                f"Freed approximately **{self._format_bytes(size)}**."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Stale threshold: {hours:g} hour(s)")
        await ctx.send(embed=embed)

    @commands.command(name="cachestatus", aliases=["diskcache"])
    @commands.is_owner()
    async def cachestatus(self, ctx):
        roots = self._cache_roots()
        total_bytes = 0
        files = 0

        for directory in roots:
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if path.is_file():
                    try:
                        total_bytes += path.stat().st_size
                        files += 1
                    except OSError:
                        pass

        embed = discord.Embed(
            title="💾 Cache Status",
            description=(
                f"Tracked cache files: **{files:,}**\n"
                f"Tracked cache size: **{self._format_bytes(total_bytes)}**\n"
                f"Automatic cleanup: **every {DEFAULT_INTERVAL_MINUTES} minutes**\n"
                f"Default stale threshold: **{DEFAULT_MAX_AGE_HOURS} hours**"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Maintenance(bot))
