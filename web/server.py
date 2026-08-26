import asyncio
from aiohttp import web

async def handle(request):
    # Ito ang magre-reply kapag tiningnan ng Render kung buhay ang server mo
    return web.Response(text="Bot is running smoothly!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Gagamitin nito ang Port na binibigay ng Render, o 8080 kung local
    import os
    port = int(os.environ.get("PORT", 8080))
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server successfully started on port {port}")
