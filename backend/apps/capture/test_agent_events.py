import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import AgentConnectivityEvent

TOKEN = "events-3." + "s" * 43
AGENTS = {"events-3": {"box": "box-3", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}}
URL = "/api/v2/internal/agent-events"


@override_settings(CAPTURE_AGENTS=AGENTS)
class AgentEventTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)
        self.event = {"event_id": str(uuid4()), "session_id": None, "kind": "wss.disconnected",
            "occurred_at": (timezone.now() - timedelta(hours=2)).isoformat(),
            "outage_id": str(uuid4()), "duration_ms": None, "cause": "TIMEOUT"}

    def post(self, events=None):
        return self.client.post(URL, {"version": "1.0", "events": events or [self.event]}, format="json")

    def test_offline_events_and_lost_response_retry_keep_original_receipt(self):
        recovered = {**self.event, "event_id": str(uuid4()), "kind": "wss.reconnected",
            "occurred_at": timezone.now().isoformat(), "duration_ms": 7200000}
        first = self.post([self.event, recovered])
        self.assertEqual(first.status_code, 200, first.data)
        received = list(AgentConnectivityEvent.objects.values_list("received_at", flat=True))
        second = self.post([self.event, recovered])
        self.assertEqual(first.data["data"], second.data["data"])
        self.assertEqual(AgentConnectivityEvent.objects.count(), 2)
        self.assertEqual(list(AgentConnectivityEvent.objects.values_list("received_at", flat=True)), received)
        self.assertEqual(AgentConnectivityEvent.objects.first().box, "box-3")

    def test_conflict_rolls_back_entire_batch(self):
        self.post()
        other = {**self.event, "event_id": str(uuid4())}
        response = self.post([other, {**self.event, "cause": "CONNECTION_ERROR"}])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(AgentConnectivityEvent.objects.count(), 1)

    def test_no_identity_or_extra_fields_accepted_from_payload(self):
        for changes in ({"box": "box-4"}, {"agent_id": "other"}, {"message": "untrusted"},
                        {"cause": "arbitrary exception"}, {"session_id": str(uuid4())}):
            with self.subTest(changes=list(changes)):
                response = self.post([{**self.event, **changes}])
                self.assertIn(response.status_code, (400, 403), response.data)
        self.assertFalse(AgentConnectivityEvent.objects.exists())

    def test_timestamps_and_duration_are_validated(self):
        for changes in ({"occurred_at": "2026-01-01T12:00:00"},
                        {"occurred_at": (timezone.now() + timedelta(minutes=5)).isoformat()},
                        {"duration_ms": -1}, {"duration_ms": 1}):
            self.assertEqual(self.post([{**self.event, **changes}]).status_code, 400)

    def test_authentication_and_bounded_body(self):
        self.client.credentials()
        self.assertEqual(self.post().status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)
        response = self.client.generic("POST", URL, json.dumps({"padding": "x" * 65537}),
                                       content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertFalse(AgentConnectivityEvent.objects.exists())
