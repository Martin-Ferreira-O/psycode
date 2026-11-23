import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from .models import AgentCommand, AgentConnectivityEvent, AgentStatus, CaptureEvent, CaptureSession
from .protocol import envelope
from .tests import CaptureFixtures, NOW
from .websocket import agent_websocket

TOKEN = "continuity-3." + "s" * 43
AGENTS = {"continuity-3": {"box": "box-3", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}}


@override_settings(CAPTURE_AGENTS=AGENTS)
class AgentSessionContinuityAPITests(CaptureFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.session = self.active()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)
        self.url = f"/api/v2/internal/sessions/{self.session.session_id}"
        clock = patch("django.utils.timezone.now", return_value=NOW + timedelta(seconds=40))
        clock.start()
        self.addCleanup(clock.stop)

    def end(self, **changes):
        payload = {"occurred_at": (NOW + timedelta(seconds=20)).isoformat(),
                   "last_sequence": None, "reason_code": "RECOVERY_STOPPED"}
        payload.update(changes)
        return self.client.post(self.url + "/capture-ended", payload, format="json")

    def test_capture_end_unknown_sequence_and_later_recovery_have_separate_states(self):
        response = self.end()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["capture"], "finished")
        self.assertEqual(response.data["data"]["reception"], "intervention_required")
        self.assertIsNone(response.data["data"]["final_sequence"])
        stop = AgentCommand.objects.get(session_id=self.session.session_id, kind="detencion")
        self.assertIsNone(stop.succeeded)
        count = CaptureEvent.objects.count()
        again = self.end()
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(CaptureEvent.objects.count(), count)
        known = self.end(last_sequence=0)
        self.assertEqual(known.status_code, 200, known.data)
        inspected = self.client.get(self.url)
        self.assertEqual(inspected.status_code, 200, inspected.data)
        self.assertEqual(inspected.data["data"]["final_sequence"], 0)
        self.assertEqual(inspected.data["data"]["reception"], "pending")
        self.assertEqual(inspected.data["data"]["processing"], "pending")
        self.assertNotIn("storage_key", inspected.data["data"])

    def test_capture_end_conflicts_preserve_original_physical_evidence(self):
        self.assertEqual(self.end(last_sequence=0).status_code, 200)
        for changes in ({"occurred_at": (NOW + timedelta(seconds=21)).isoformat()},
                        {"last_sequence": 1}, {"reason_code": "DISK_LOW"}):
            with self.subTest(changes=changes):
                response = self.end(**changes)
                self.assertEqual(response.status_code, 409, response.data)
        stored = CaptureSession.objects.get()
        self.assertEqual(stored.actual_end, NOW + timedelta(seconds=20))
        self.assertEqual(stored.final_sequence, 0)
        self.assertEqual(stored.capture_end_reason, "RECOVERY_STOPPED")

    def test_identity_is_required_and_cannot_report_another_box(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.end().status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)
        other = self.service.apply_authorization(replace(self.authorization, box="box-4"), now=NOW)
        foreign_url = f"/api/v2/internal/sessions/{other.session_id}"
        self.assertGreaterEqual(self.client.get(foreign_url).status_code, 400)
        response = self.client.post(foreign_url + "/capture-ended", {
            "occurred_at": (NOW + timedelta(seconds=20)).isoformat(),
            "last_sequence": -1, "reason_code": "AGENT_STOPPED",
        }, format="json")
        self.assertGreaterEqual(response.status_code, 400)
        self.assertIsNone(CaptureSession.objects.get(pk=other.session_id).actual_end)

    def test_capture_end_validates_timestamp_sequence_reason_and_body(self):
        for changes in ({"occurred_at": "2026-10-19T12:00:00"}, {"last_sequence": -2},
                        {"last_sequence": True}, {"reason_code": "arbitrary failure message"},
                        {"box": "box-4"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.end(**changes).status_code, 400)
        future = self.end(occurred_at=(NOW + timedelta(seconds=41)).isoformat())
        self.assertEqual(future.status_code, 409, future.data)
        oversized = self.client.generic("POST", self.url + "/capture-ended",
            json.dumps({"padding": "x" * 65537}), content_type="application/json")
        self.assertEqual(oversized.status_code, 413)
        self.assertIsNone(CaptureSession.objects.get().actual_end)


class CaptureHealthContinuityTests(CaptureFixtures, TestCase):
    def test_health_reports_independent_states_and_last_event_per_channel_safely(self):
        session = self.active()
        self.ack_stop(self.stop(), last_sequence=0)
        AgentStatus.objects.create(box="box-3", seen_at=NOW, diagnostics={
            "operational_code": "DISK_LOW", "pending": 1, "PRIVATE": "DO_NOT_PRINT",
        })
        for channel in ("wss", "https"):
            for seconds, transition in ((10, "disconnected"), (20, "reconnected")):
                AgentConnectivityEvent.objects.create(event_id=uuid4(), agent_id="synthetic-agent", box="box-3",
                    session_id=session.session_id, kind=channel + "." + transition,
                    occurred_at=NOW + timedelta(seconds=seconds), received_at=NOW + timedelta(days=1),
                    outage_id=uuid4(), duration_ms=None if seconds == 10 else 10000, cause="TIMEOUT")
        output = StringIO()
        with patch("django.utils.timezone.now", return_value=NOW + timedelta(days=8)):
            call_command("capture_health", stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report["backlog_counts"]["reception_intervention"], 1)
        self.assertEqual(report["backlog_counts"]["critical"], 1)
        lifecycle = report["session_lifecycles"][0]
        self.assertEqual(lifecycle["capture"], "finished")
        self.assertEqual(lifecycle["reception"], "intervention_required")
        latest = next(item for item in report["last_connection_events"] if item["box"] == "box-3")
        self.assertEqual(latest["wss"]["kind"], "wss.reconnected")
        self.assertEqual(latest["https"]["kind"], "https.reconnected")
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertNotIn("DO_NOT_PRINT", output.getvalue())
        self.assertNotIn("storage_key", output.getvalue())


@override_settings(CAPTURE_AGENTS=AGENTS)
class ContinuityCapabilityHandshakeTests(TransactionTestCase):
    def test_ready_announces_additive_capabilities_to_existing_agent(self):
        async def exercise():
            received = asyncio.Queue()
            sent = []
            for event in ({"type": "websocket.connect"},
                          {"type": "websocket.receive", "text": json.dumps(envelope("hello", {
                              "agent_version": "1.0", "capabilities": [],
                          }))}, {"type": "websocket.disconnect"}):
                await received.put(event)

            async def send(event):
                sent.append(event)

            await agent_websocket({"type": "websocket", "path": "/ws/v1/agents",
                "headers": [(b"authorization", ("Agent " + TOKEN).encode())],
                "query_string": b""}, received.get, send)
            return sent

        sent = asyncio.run(exercise())
        ready = next(json.loads(event["text"]) for event in sent
                     if event["type"] == "websocket.send" and json.loads(event["text"])["type"] == "ready")
        self.assertEqual(ready["protocol_version"], "1.0")
        self.assertIn("audio.v2", ready["payload"]["capabilities"])
        self.assertNotIn("audio.v1", ready["payload"]["capabilities"])
        self.assertIn("agent.events.v1", ready["payload"]["capabilities"])
        self.assertIn("sessions.capture-ended.v1", ready["payload"]["capabilities"])
