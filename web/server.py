import os
from aiohttp import web


async def handle(request):
    return web.Response(text="Bot is running smoothly!")


async def health(request):
    return web.json_response({"status": "ok", "service": "ECLIPSE"})


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server successfully started on port {port}")
