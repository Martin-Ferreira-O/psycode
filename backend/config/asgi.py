import os
from django.core.asgi import get_asgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")
http_application = get_asgi_application()
from backend.apps.capture.websocket import agent_websocket

async def application(scope, receive, send):
    if scope["type"] == "websocket":
        return await agent_websocket(scope, receive, send)
    if scope["type"] == "lifespan":
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    return await http_application(scope, receive, send)
