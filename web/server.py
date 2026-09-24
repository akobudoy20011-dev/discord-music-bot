import os
import time
from datetime import datetime, timezone

from aiohttp import web


def _format_uptime(seconds):
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02}h {minutes:02}m {seconds:02}s"


async def handle(request):
    return web.Response(text="ECLIPSE is online.")


async def health(request):
    """Lightweight health endpoint for Render/external monitoring."""
    bot = request.app["bot"]
    started_at = request.app["started_at"]

    discord_ready = bool(bot and not bot.is_closed() and bot.is_ready())
    db_ok = False
    db_latency_ms = None

    if bot is not None and getattr(bot, "db", None) is not None:
        try:
            db_health = await bot.db.health_check()
            db_ok = True
            db_latency_ms = round(float(db_health.get("latency_ms", 0)), 1)
        except Exception:
            db_ok = False

    uptime_seconds = max(0, int(time.monotonic() - started_at))
    overall_ready = discord_ready and db_ok

    watchdog = None
    watchdog_cog = bot.get_cog("Watchdog") if bot is not None else None
    if watchdog_cog is not None:
        watchdog = {
            "running": watchdog_cog._tick.is_running(),
            "last_run": watchdog_cog.last_run,
            "last_error": watchdog_cog.last_error,
            "recovery_count": watchdog_cog.recovery_count,
            "last_recovery": watchdog_cog.last_recovery,
            "last_voice_failure": watchdog_cog.last_voice_failure,
        }

    payload = {
        "status": "ok" if overall_ready else "degraded",
        "service": "ECLIPSE",
        "process": "up",
        "ready": overall_ready,
        "discord": {
            "ready": discord_ready,
            "latency_ms": round(bot.latency * 1000, 1) if discord_ready else None,
            "guilds": len(bot.guilds) if bot is not None else 0,
        },
        "database": {
            "ready": db_ok,
            "latency_ms": db_latency_ms,
        },
        "watchdog": watchdog,
        "uptime_seconds": uptime_seconds,
        "uptime": _format_uptime(uptime_seconds),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Keep this 200 while the process is alive. A monitor can distinguish
    # process liveness from Discord/DB readiness using the JSON fields.
    return web.json_response(payload)


async def start_web_server(bot, started_at):
    app = web.Application()
    app["bot"] = bot
    app["started_at"] = started_at

    app.router.add_get("/", handle)
    app.router.add_get("/health", health)
    app.router.add_get("/healthz", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server successfully started on port {port}")
