import json
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from backend.apps.accounts.models import Role, User

from .authentication import authenticate_agent_header
from .models import AgentConfiguration, AgentRegistration, ConfigurationState
from .pc_registry import create_agent
from .protocol import decode, envelope
from .serializers import AgentConfigurationSerializer
from .websocket import RemoteControl


class AgentConfigurationTests(APITestCase):
    def setUp(self):
        self.agent, self.token = create_agent(name="PC Box 3", box="box-3")
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

    def test_bug_97_01_serializer_rejects_unknown_parameters_and_negative_values(self):
        serializer = AgentConfigurationSerializer(
            data={"desired_config": {"parametro_inventado": True, "audio_chunk_duration": -999}}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("desired_config", serializer.errors)

    def test_bug_97_02_03_04_state_transitions_obsolete_rejection_and_effective_config(self):
        v1 = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={"qa": 10})
        v2 = AgentConfiguration.objects.create(agent=self.agent, version=2, desired_config={"qa": 30})
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        control = RemoteControl(identity, uuid4())
        control.open()

        control.mark_config_received(v2.pk)
        v2.refresh_from_db()
        self.assertEqual(v2.state, ConfigurationState.RECEIVED)

        v_missing = AgentConfiguration.objects.create(agent=self.agent, version=3, desired_config={"qa": 30})
        control.acknowledge_config(v_missing.pk, success=True, effective_config=None)
        v_missing.refresh_from_db()
        self.assertEqual(v_missing.state, ConfigurationState.FAILED)
        self.assertEqual(v_missing.error_code, "MISSING_EFFECTIVE_CONFIG")

        control.acknowledge_config(v2.pk, success=True, effective_config={"qa": 30})
        v2.refresh_from_db()
        self.assertEqual(v2.state, ConfigurationState.APPLIED)
        self.assertEqual(v2.effective_config, {"qa": 30})

        control.acknowledge_config(v1.pk, success=True, effective_config={"qa": 10})
        v1.refresh_from_db()
        self.assertNotEqual(v1.state, ConfigurationState.APPLIED)
        self.assertEqual(v1.state, ConfigurationState.FAILED)

    def test_bug_97_05_concurrent_or_stale_edits_are_rejected_and_audited(self):
        admin = User(role=Role.ADMIN, is_active=True, is_staff=False)
        self.client.force_authenticate(admin)

        with patch("backend.common.audit.AuditWriter.emit") as emit:
            initial = self.client.get(self.url).data["data"]["version"]
            self.assertEqual(initial, 0)

            first = self.client.put(self.url, {"desired_config": {"qa": 10}, "base_version": 0}, format="json")
            self.assertEqual(first.status_code, 201)
            self.assertEqual(first.data["data"]["version"], 1)
            self.assertGreaterEqual(emit.call_count, 1)

            stale = self.client.put(self.url, {"desired_config": {"qa": 20}, "base_version": 0}, format="json")
            self.assertEqual(stale.status_code, 409)

            blind_stale = self.client.put(self.url, {"desired_config": {"qa": 25}}, format="json")
            self.assertEqual(blind_stale.status_code, 409)

    def test_qa_auditoria_configuracion(self):
        admin = User(role=Role.ADMIN, is_active=True, is_staff=False)
        self.client.force_authenticate(admin)
        with patch("backend.common.audit.AuditWriter.emit") as emit:
            response = self.client.put(self.url, {"desired_config": {"qa": 10}}, format="json")
            sql_count = AgentConfiguration.objects.filter(agent=self.agent).count()
            audit_count = emit.call_count
            self.assertEqual(response.status_code, 201)
            self.assertEqual(sql_count, 1)
            self.assertGreaterEqual(audit_count, 1)

    def test_qa_ediciones_concurrentes(self):
        admin = User(role=Role.ADMIN, is_active=True, is_staff=False)
        self.client.force_authenticate(admin)
        v_init = self.client.get(self.url).data["data"]["version"]
        r1 = self.client.put(self.url, {"desired_config": {"qa": 10}, "base_version": v_init}, format="json")
        r2 = self.client.put(self.url, {"desired_config": {"qa": 20}, "base_version": v_init}, format="json")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 409)

    def test_qa_multiple_pending_versions(self):
        v1 = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={"qa": 10})
        v2 = AgentConfiguration.objects.create(agent=self.agent, version=2, desired_config={"qa": 20})
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        control = RemoteControl(identity, uuid4())
        control.open()
        control.acknowledge_config(v2.pk, success=True, effective_config={"qa": 20})
        control.acknowledge_config(v1.pk, success=True, effective_config={"qa": 10})
        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v2.state, ConfigurationState.APPLIED)
        self.assertEqual(v1.state, ConfigurationState.FAILED)

    def test_qa_configuracion_efectiva(self):
        v1 = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={"qa": 30})
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        control = RemoteControl(identity, uuid4())
        control.open()
        control.acknowledge_config(v1.pk, success=True, effective_config=None)
        v1.refresh_from_db()
        self.assertEqual(v1.state, ConfigurationState.FAILED)
        self.assertEqual(v1.error_code, "MISSING_EFFECTIVE_CONFIG")


class ConfigurationProtocolTests(SimpleTestCase):
    def test_configuration_and_error_messages_round_trip(self):
        config_id = str(uuid4())
        messages = {
            "config_sync": {"config_id": config_id, "version": 1, "desired_config": {}},
            "config_received": {"config_id": config_id},
            "config_ack": {"config_id": config_id, "success": True},
            "config_receipt": {"config_id": config_id, "state": "aplicado"},
            "error": {"code": "INVALID_MESSAGE", "recoverable": False},
        }
        for kind, payload in messages.items():
            with self.subTest(kind=kind):
                message = envelope(kind, payload)
                self.assertEqual(decode(json.dumps(message)), message)