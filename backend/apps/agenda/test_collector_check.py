from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from backend.apps.accounts.models import Role
from backend.apps.capture.authentication import authenticate_agent_header
from backend.apps.capture.models import AgentRegistration, RuntimeLease
from backend.apps.capture.pc_registry import create_agent
from backend.apps.capture.test_api import AGENTS, TOKEN
from backend.apps.capture.websocket import RemoteControl

from .models import AgendaCollection, SmileCollectorCheck
from .test_persistence import SOURCES


@override_settings(CAPTURE_AGENDA_SOURCES=SOURCES, CAPTURE_AGENTS=AGENTS)
class SmileCollectorCheckTests(APITestCase):
    def setUp(self):
        self.machine = APIClient()
        self.machine.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)
        self.identity = authenticate_agent_header(("Agent " + TOKEN).encode())
        self.agent = AgentRegistration.objects.get(pk=self.identity.registry_id)
        self.control = RemoteControl(self.identity, uuid4())
        self.control.open()
        self.control.register_hello("synthetic", True)
        self.control.dispatch({"type": "status", "payload": {"obs": "ready"}})
        self.url = f"/api/v1/pcs/{self.agent.pk}/smile/prueba"
        self.internal = "/api/v1/internal/smile-collector-check"
        user = get_user_model().objects.create_user(
            username="admin-smile", email="admin@example.test", password="synthetic", role=Role.ADMIN,
        )
        self.client.force_authenticate(user)

    def post(self, client, url, data):
        return client.post(url, data, format="json")

    def test_admin_queues_only_one_check_and_machine_finishes_idempotently(self):
        for _ in range(2):
            response = self.post(self.client, self.url, {"source": "smile"})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.data["data"]["state"], "queued")
        claim = self.post(self.machine, self.internal, {"action": "claim"})
        self.assertEqual(claim.status_code, 200)
        task = claim.data["data"]
        self.assertEqual(task["source"], "smile")
        self.assertIsNone(self.post(self.machine, self.internal, {"action": "claim"}).data["data"])
        finish = {"action": "finish", "request_id": task["request_id"], "result": "missing_profile"}
        for _ in range(2):
            self.assertEqual(self.post(self.machine, self.internal, finish).status_code, 200)
        self.assertEqual(self.post(self.machine, self.internal, {**finish, "result": "ok"}).status_code, 409)
        pc = next(row for row in self.client.get("/api/v1/pcs").data["data"]
                  if row["agent_id"] == str(self.agent.pk))
        self.assertEqual(pc["smile_sources"], ["smile"])
        self.assertEqual(pc["smile_check"]["result"], "missing_profile")
        self.assertFalse(AgendaCollection.objects.exists())
        self.assertEqual(self.post(self.client, self.url, {"source": "smile"}).status_code, 429)

    def test_supervisor_and_other_pc_cannot_run_or_finish_the_check(self):
        supervisor = get_user_model().objects.create_user(
            username="supervisor-smile", email="supervisor@example.test", password="synthetic", role=Role.SUPERVISOR,
        )
        viewer = APIClient()
        viewer.force_authenticate(supervisor)
        self.assertEqual(self.post(viewer, self.url, {"source": "smile"}).status_code, 403)
        other, token = create_agent(name="Otro PC", box="box-8")
        other_machine = APIClient()
        other_machine.credentials(HTTP_AUTHORIZATION="Agent " + token)
        self.assertEqual(self.post(self.client, f"/api/v1/pcs/{other.pk}/smile/prueba", {"source": "smile"}).status_code, 403)
        self.post(self.client, self.url, {"source": "smile"})
        self.assertIsNone(self.post(other_machine, self.internal, {"action": "claim"}).data["data"])
        task = self.post(self.machine, self.internal, {"action": "claim"}).data["data"]
        finish = {"action": "finish", "request_id": task["request_id"], "result": "ok"}
        self.assertEqual(self.post(other_machine, self.internal, finish).status_code, 409)
        self.assertEqual(self.post(self.machine, self.internal, {**finish, "result": "free text"}).status_code, 400)

    def test_expired_check_cannot_run_and_offline_or_old_agents_cannot_queue(self):
        self.post(self.client, self.url, {"source": "smile"})
        SmileCollectorCheck.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(self.post(self.machine, self.internal, {"action": "claim"}).data["data"])
        self.control.register_hello("older-agent")
        response = self.post(self.client, self.url, {"source": "smile"})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "SMILE_CHECK_UPDATE_REQUIRED", status_code=409)
        RuntimeLease.objects.all().delete()
        response = self.post(self.client, self.url, {"source": "smile"})
        self.assertContains(response, "SMILE_CHECK_OFFLINE", status_code=409)
