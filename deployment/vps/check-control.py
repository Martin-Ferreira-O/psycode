"""Comprueba WSS desde el proxy con la credencial de un box reservado para ensayo."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from websockets.asyncio.client import connect


async def main():
    settings = json.loads(Path(os.environ["PSYCODE_CONTROL_PROBE"]).read_text(encoding="utf-8"))
    url = settings["url"]
    if not url.startswith("wss://"):
        raise ValueError("CONTROL_PROBE_REQUIRES_WSS")
    # Conserva SNI, hostname y validación TLS de la URL pública. En una VPS
    # detrás de NAT se conecta al mismo Nginx sin depender del retorno por IP.
    endpoint = {"host": "127.0.0.1", "port": 443} if os.environ.get("PSYCODE_PROBE_LOCAL") == "1" else {}
    async with asyncio.timeout(10), connect(url, proxy=None,
            additional_headers={"Authorization": "Agent " + settings["token"]},
            open_timeout=5, close_timeout=1, max_size=65536, **endpoint) as socket:
        async def request(kind, payload, expected):
            mid = str(uuid4())
            await socket.send(json.dumps(dict(protocol_version="1.0", message_id=mid, type=kind,
                                              sent_at=datetime.now(timezone.utc).isoformat(), payload=payload)))
            async for raw in socket:
                message = json.loads(raw)
                if message.get("correlation_id") == mid:
                    if message.get("type") != expected:
                        raise RuntimeError("CONTROL_PROBE_RESPONSE")
                    return message["payload"]
            raise RuntimeError("CONTROL_PROBE_DISCONNECTED")

        ready = await request("hello", {"agent_version": "deploy-probe", "capabilities": []}, "ready")
        if ready["box"] != settings["box"]:
            raise RuntimeError("CONTROL_PROBE_WRONG_BOX")
        state = await request("sync", {}, "state")
        if not isinstance(state["commands"], list) or not isinstance(state["sessions"], list):
            raise RuntimeError("CONTROL_PROBE_STATE")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit("CONTROL_PROBE_FAILED") from None
