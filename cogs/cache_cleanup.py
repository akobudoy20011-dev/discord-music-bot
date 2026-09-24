"""Automatic disk-cache cleanup for the ECLIPSE Discord bot.

Only bot-owned cache locations are touched. The cleaner never walks arbitrary
system directories such as /tmp, and it never deletes the SQLite database,
configuration, cookies, or source files.

The cog performs one cleanup on startup and then periodically removes files
older than the configured age. Cleanup runs in a worker thread so filesystem
scans do not block the Discord event loop.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

from discord.ext import commands, tasks


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


class CacheCleanup(commands.Cog):
    """Keep transient music/download caches from growing without bound."""

    INTERVAL_SECONDS = _env_int("ECLIPSE_CACHE_CLEANUP_INTERVAL", 1800, 300)
    MAX_AGE_SECONDS = _env_int("ECLIPSE_CACHE_MAX_AGE", 21600, 900)
    YTDLP_MAX_AGE_SECONDS = _env_int(
        "ECLIPSE_YTDLP_CACHE_MAX_AGE", 86400, 3600
    )

    def __init__(self, bot):
        self.bot = bot
        self.started_at = time.time()
        self.last_run = None
        self.last_error = None
        self.last_removed_files = 0
        self.last_removed_bytes = 0
        self.total_removed_files = 0
        self.total_removed_bytes = 0
        self._task.start()

    def cog_unload(self):
        self._task.cancel()

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            if path.is_file():
                return path.stat().st_size
        except OSError:
            pass
        return 0

    @classmethod
    def _remove_stale_files(cls, root: Path, max_age: int) -> tuple[int, int]:
        if not root.exists() or not root.is_dir():
            return 0, 0

        cutoff = time.time() - max_age
        removed_files = 0
        removed_bytes = 0

        try:
            entries = list(root.iterdir())
        except OSError:
            return 0, 0

        for path in entries:
            try:
                # Never remove a path that became a symlink.
                if path.is_symlink():
                    continue

                stat = path.stat()
                if stat.st_mtime >= cutoff:
                    continue

                if path.is_file():
                    removed_bytes += stat.st_size
                    path.unlink()
                    removed_files += 1
                elif path.is_dir():
                    size = 0
                    for child in path.rglob("*"):
                        if child.is_symlink():
                            continue
                        try:
                            if child.is_file():
                                size += child.stat().st_size
                        except OSError:
                            pass
                    shutil.rmtree(path)
                    removed_files += 1
                    removed_bytes += size
            except (OSError, PermissionError):
                continue

        return removed_files, removed_bytes

    @classmethod
    def _cleanup_sync(cls) -> tuple[int, int]:
        """Clean only explicitly bot-owned transient locations."""
        roots: list[tuple[Path, int]] = []

        # A dedicated bot temp directory is the safest place for generated
        # audio/download artifacts. It may not exist on a fresh deployment.
        bot_tmp = Path(
            os.getenv(
                "ECLIPSE_TEMP_DIR",
                os.path.join(tempfile.gettempdir(), "eclipse-bot"),
            )
        )
        roots.append((bot_tmp, cls.MAX_AGE_SECONDS))

        # yt-dlp's standard user cache. Do not touch the entire ~/.cache tree.
        ytdlp_cache = Path(
            os.getenv(
                "YTDLP_CACHE_DIR",
                os.path.expanduser("~/.cache/yt-dlp"),
            )
        )
        roots.append((ytdlp_cache, cls.YTDLP_MAX_AGE_SECONDS))

        removed_files = 0
        removed_bytes = 0

        for root, max_age in roots:
            files, size = cls._remove_stale_files(root, max_age)
            removed_files += files
            removed_bytes += size

        return removed_files, removed_bytes

    async def cleanup_now(self) -> tuple[int, int]:
        return await asyncio.to_thread(self._cleanup_sync)

    async def run_cleanup(self):
        try:
            files, size = await self.cleanup_now()
            self.last_run = time.time()
            self.last_error = None
            self.last_removed_files = files
            self.last_removed_bytes = size
            self.total_removed_files += files
            self.total_removed_bytes += size
        except Exception as exc:
            self.last_run = time.time()
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.last_removed_files = 0
            self.last_removed_bytes = 0

    @tasks.loop(seconds=INTERVAL_SECONDS)
    async def _task(self):
        await self.run_cleanup()

    @_task.before_loop
    async def _before_task(self):
        await self.bot.wait_until_ready()
        # Run immediately after Discord is ready instead of waiting for the
        # first full interval.
        await self.run_cleanup()


async def setup(bot):
    await bot.add_cog(CacheCleanup(bot))
