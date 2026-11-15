"""Regresiones de la auditoría WSS con ASGI, SQL y datos sintéticos."""
import asyncio
import json
from datetime import timedelta

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from .models import CaptureSession, RuntimeLease
from .pc_registry import create_agent
from .protocol import envelope, MAX_BYTES
from .websocket import RemoteControl, agent_websocket, db
from .services import CaptureSessionService
from backend.apps.operational.capture_authorization import BoxCaptureAuthorization
from backend.apps.operational.smile_configuration import CAPABILITY as SMILE_CONFIG_CAPABILITY
from backend.apps.agenda.collector_check import CAPABILITY as SMILE_CHECK_CAPABILITY


class WebSocketAuditTests(TransactionTestCase):
    def setUp(self):
        self.agent, self.token = create_agent(name="PC sintético", box="box-3")

    @override_settings(CAPTURE_AGENT_AUTH_IP_LIMIT=1, CAPTURE_AGENT_AUTH_ID_LIMIT=1)
    def test_upgrade_rejections_are_distinguishable(self):
        async def run(path, token):
            events = []
            async def receive():
                return {"type": "websocket.connect"}
            async def send(event):
                events.append(event)
            await agent_websocket({"type": "websocket", "path": path,
                "extensions": {"websocket.http.response": {}}, "client": ("192.0.2.203", 443),
                "headers": [(b"authorization", f"Agent {token}".encode())]}, receive, send)
            return events[0]["status"], dict(events[0]["headers"])
        route, _ = asyncio.run(run("/ws/incorrecta", self.token))
        rejected, headers = asyncio.run(run("/ws/v1/agents", "sintetico." + "x" * 43))
        limited, retry = asyncio.run(run("/ws/v1/agents", "sintetico." + "x" * 43))
        self.assertEqual((route, rejected, limited), (404, 401, 429))
        self.assertEqual(headers[b"x-psycode-control-error"], b"CREDENTIAL_INVALID")
        self.assertGreater(int(retry[b"retry-after"]), 0)

    def test_backlog_does_not_hide_stop_from_legacy_or_current_client(self):
        now = timezone.now()
        CaptureSession.objects.bulk_create([
            CaptureSession(box="box-3", state="finalizando", origin="agenda",
                scheduled_start=now - timedelta(days=n + 1), scheduled_end=now - timedelta(days=n, minutes=1),
                authorized_at=now - timedelta(days=n + 1), actual_end=now - timedelta(days=n, hours=1),
                stop_requested_at=now - timedelta(days=n, hours=1), last_seen_at=now)
            for n in range(240)
        ])
        service = CaptureSessionService()
        window = BoxCaptureAuthorization("box-3", True, now, now + timedelta(hours=1), "agenda")
        sid = service.apply_authorization(window, now=now).session_id
        service.commands("box-3", now=now)
        from dataclasses import replace
        service.apply_authorization(replace(window, authorized=False, inicio=None, termino=None), now=now)

        async def run(capabilities):
            messages, incoming = [], asyncio.Queue()
            await incoming.put({"type": "websocket.connect"})
            await incoming.put({"type": "websocket.receive", "text": json.dumps(
                envelope("hello", {"agent_version": "test", "capabilities": capabilities}))})
            async def send(event):
                if event["type"] != "websocket.send":
                    return
                raw = event["text"]
                message = json.loads(raw)
                messages.append((len(raw.encode()), message))
                if message["type"] == "ready":
                    await incoming.put({"type": "websocket.receive", "text": json.dumps(envelope("sync", {}))})
                if message["type"] == "state":
                    await incoming.put({"type": "websocket.disconnect"})
            await asyncio.wait_for(agent_websocket({"type": "websocket", "path": "/ws/v1/agents",
                "headers": [(b"authorization", f"Agent {self.token}".encode())]}, incoming.get, send), timeout=5)
            return messages

        for caps in ([], ["audio.v2", "audio.chunk-config.v2", SMILE_CONFIG_CAPABILITY, SMILE_CHECK_CAPABILITY]):
            messages = asyncio.run(run(caps))
            ready = next(m["payload"] for _, m in messages if m["type"] == "ready")
            for capability in (SMILE_CONFIG_CAPABILITY, SMILE_CHECK_CAPABILITY):
                self.assertEqual(capability in ready["capabilities"], capability in caps)
            length, message = next((n, m) for n, m in messages if m["type"] == "state")
            self.assertLess(length, MAX_BYTES)
            state = message["payload"]
            self.assertEqual([s["state"] for s in state["sessions"]], ["finalizando"])
            stop, = state["commands"]
            self.assertEqual((stop["kind"], stop["session_id"]), ("detencion", str(sid)))

    def test_cancelled_handshake_releases_its_owner_after_sql_commit(self):
        from threading import Event
        from unittest.mock import patch
        committed, release = Event(), Event()
        original = RemoteControl.open

        def open_with_barrier(control):
            acquired = original(control)
            committed.set()
            release.wait(3)
            return acquired

        async def run():
            incoming = asyncio.Queue()
            await incoming.put({"type": "websocket.connect"})
            await incoming.put({"type": "websocket.receive", "text": json.dumps(
                envelope("hello", {"agent_version": "test", "capabilities": []}))})
            async def send(event):
                pass
            task = asyncio.create_task(agent_websocket({"type": "websocket", "path": "/ws/v1/agents",
                "headers": [(b"authorization", f"Agent {self.token}".encode())]}, incoming.get, send))
            self.assertTrue(await asyncio.to_thread(committed.wait, 2))
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
        with patch.object(RemoteControl, "open", open_with_barrier):
            asyncio.run(run())
        self.agent.refresh_from_db()
        self.assertIsNone(self.agent.control_owner)
        self.assertFalse(RuntimeLease.objects.filter(name="control:box-3").exists())
