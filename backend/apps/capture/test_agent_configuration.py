import json
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from backend.apps.accounts.models import Role, User

from .models import AgentConfiguration, AgentRegistration
from .protocol import decode, envelope


class AgentConfigurationTests(APITestCase):
    def setUp(self):
        self.agent = AgentRegistration.objects.create(name="PC Box 3", box="box-3", token_sha256="0" * 64)
        self.url = reverse("capture:agent_config", args=[self.agent.pk])

    def test_active_psycode_admin_without_staff_can_set_and_read_configuration(self):
        admin = User(role=Role.ADMIN, is_active=True, is_staff=False)
        self.client.force_authenticate(admin)

        response = self.client.put(self.url, {"desired_config": {}}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["version"], 1)
        self.assertEqual(AgentConfiguration.objects.get().requested_by, admin.pk)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["desired_config"], {})

    def test_staff_without_psycode_admin_role_and_inactive_admin_are_forbidden(self):
        for user in (User(role=Role.SUPERVISOR, is_staff=True), User(role=Role.ADMIN, is_active=False)):
            with self.subTest(role=user.role, active=user.is_active):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.put(self.url, {"desired_config": {}}, format="json").status_code, 403)
        self.assertFalse(AgentConfiguration.objects.exists())

    def test_put_rejects_missing_and_non_object_configuration(self):
        self.client.force_authenticate(User(role=Role.ADMIN))
        for data in ({}, {"desired_config": []}, {"desired_config": None}):
            with self.subTest(data=data):
                self.assertEqual(self.client.put(self.url, data, format="json").status_code, 400)
        self.assertFalse(AgentConfiguration.objects.exists())


class ConfigurationProtocolTests(SimpleTestCase):
    def test_configuration_and_error_messages_round_trip(self):
        config_id = str(uuid4())
        messages = {
            "config_sync": {"config_id": config_id, "version": 1, "desired_config": {}},
            "config_ack": {"config_id": config_id, "success": True},
            "config_receipt": {"config_id": config_id, "state": "aplicado"},
            "error": {"code": "INVALID_MESSAGE", "recoverable": False},
        }
        for kind, payload in messages.items():
            with self.subTest(kind=kind):
                message = envelope(kind, payload)
                self.assertEqual(decode(json.dumps(message)), message)
