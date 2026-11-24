import os
import re

from asgiref.sync import sync_to_async
from django.core.asgi import get_asgi_application
from django.http import JsonResponse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")
http_application = get_asgi_application()

from backend.apps.capture.upload_access import check_fragment_upload_access, reserve_fragment_upload
from backend.apps.capture.websocket import agent_websocket
from backend.common.errors import error_body

AUDIO_TEST_FRAGMENT_PATH = re.compile(
    r"/api/v2/internal/audio-tests/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/fragments"
)

async def send_json(send, response):
    await send({
        "type": "http.response.start",
        "status": response.status_code,
        "headers": [(name.lower().encode("ascii"), value.encode("latin1")) for name, value in response.items()],
    })
    await send({"type": "http.response.body", "body": response.content})


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
    path = scope.get("path", "").removeprefix(scope.get("root_path", ""))
    audio_test = AUDIO_TEST_FRAGMENT_PATH.fullmatch(path) is not None
    if scope["type"] == "http" and (path == "/api/v2/internal/fragments" or audio_test):
        # Django spools the body before running middleware or view authentication.
        # Workers share upload slots on the fragment volume. Never queue upload bodies.
        header = b",".join(value for name, value in scope["headers"] if name == b"authorization")
        if not header.strip():
            response = JsonResponse(
                error_body("AUTH_REQUIRED", "Autenticación requerida o inválida"),
                status=401, headers={"WWW-Authenticate": "Agent"},
            )
            return await send_json(send, response)
        client = scope.get("client")
        access = await sync_to_async(check_fragment_upload_access)(header, client[0] if client else "")
        if isinstance(access, JsonResponse):
            return await send_json(send, access)
        with reserve_fragment_upload(access.box, audio_test=audio_test) as reserved:
            if reserved:
                return await http_application(scope, receive, send)
        response = JsonResponse(
            error_body("UPLOAD_BUSY", "La carga de audio está ocupada. Reintenta en unos segundos."),
            status=503, headers={"Retry-After": "5"},
        )
        return await send_json(send, response)
    return await http_application(scope, receive, send)
