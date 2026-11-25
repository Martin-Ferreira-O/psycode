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

    def test_bug_97_02_03_04_state_transitions_obsolete_rejection_and_effective_config(self):
        v1 = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 10})
        v2 = AgentConfiguration.objects.create(agent=self.agent, version=2, desired_config={'heartbeat_interval': 15})
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        control = RemoteControl(identity, uuid4())
        control.open()

        control.mark_config_received(v2.pk)
        v2.refresh_from_db()
        self.assertEqual(v2.state, ConfigurationState.RECEIVED)

        v_missing = AgentConfiguration.objects.create(agent=self.agent, version=3, desired_config={'heartbeat_interval': 15})
        control.acknowledge_config(v_missing.pk, success=True, effective_config=None)
        v_missing.refresh_from_db()
        self.assertEqual(v_missing.state, ConfigurationState.FAILED)
        self.assertEqual(v_missing.error_code, "MISSING_EFFECTIVE_CONFIG")

        control.acknowledge_config(v2.pk, success=True, effective_config={'heartbeat_interval': 15})
        v2.refresh_from_db()
        self.assertEqual(v2.state, ConfigurationState.APPLIED)
        self.assertEqual(v2.effective_config, {'heartbeat_interval': 15})

        control.acknowledge_config(v1.pk, success=True, effective_config={'heartbeat_interval': 10})
        v1.refresh_from_db()
        self.assertNotEqual(v1.state, ConfigurationState.APPLIED)
        self.assertEqual(v1.state, ConfigurationState.FAILED)

    def test_configuration_write_is_audited_and_stale_edits_are_rejected(self):
        admin = User(role=Role.ADMIN, is_active=True, is_staff=False)
        self.client.force_authenticate(admin)

        with patch("backend.common.audit.AuditWriter.emit") as emit:
            initial = self.client.get(self.url).data["data"]["version"]
            self.assertEqual(initial, 0)

            first = self.client.put(self.url, {"desired_config": {'heartbeat_interval': 10}, "base_version": 0}, format="json")
            self.assertEqual(first.status_code, 201)
            self.assertEqual(first.data["data"]["version"], 1)
            self.assertEqual(AgentConfiguration.objects.filter(agent=self.agent).count(), 1)
            self.assertGreaterEqual(emit.call_count, 1)

            stale = self.client.put(self.url, {"desired_config": {'heartbeat_interval': 20}, "base_version": 0}, format="json")
            self.assertEqual(stale.status_code, 409)

            blind_stale = self.client.put(self.url, {"desired_config": {'heartbeat_interval': 25}}, format="json")
            self.assertEqual(blind_stale.status_code, 409)


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


class RemoteConfigurationAcceptanceTests(APITestCase):
    def setUp(self):
        AgentConfigurationTests.setUp(self)

    def test_audio_parameters_are_owned_by_operational_configuration(self):
        self.client.force_authenticate(User(role=Role.ADMIN))
        for desired in ({"audio_chunk_duration":60},{"audio_chunk_overlap":0},
                        {"audio_chunk_mode":"session"}):
            with self.subTest(desired=desired):
                self.assertEqual(self.client.put(self.url,{"desired_config":desired},format="json").status_code,400)
        self.assertFalse(AgentConfiguration.objects.exists())

    def test_global_session_mode_is_not_overridden_by_historical_pc_audio(self):
        from datetime import timedelta
        from django.utils import timezone
        from backend.apps.operational.models import OperationalConfiguration
        from backend.apps.operational.capture_authorization import BoxCaptureAuthorization
        from .services import CaptureSessionService
        global_config=OperationalConfiguration.load()
        global_config.audio_chunk_duration=120;global_config.audio_chunk_mode='session';global_config.save()
        now=timezone.now()
        CaptureSessionService().apply_authorization(BoxCaptureAuthorization('box-3',True,now,now+timedelta(seconds=600),'agenda'),now=now)
        AgentConfiguration.objects.create(agent=self.agent,version=1,state=ConfigurationState.APPLIED,
            desired_config={'audio_chunk_duration':30},effective_config={'audio_chunk_duration':30,'heartbeat_interval':15})
        control=RemoteControl(authenticate_agent_header(f'Agent {self.token}'.encode()),uuid4());control.open()
        control.config_supported=control.chunk_config_supported=control.chunk_config_v2_supported=True
        self.assertEqual(control.commands()[0]['audio_chunk_duration'],600)

    def test_permissions_include_reads_and_unauthenticated_requests(self):
        self.assertEqual(self.client.get(self.url).status_code,401)
        self.assertEqual(self.client.put(self.url,{"desired_config":{}},format="json").status_code,401)
        for user in (User(role=Role.SUPERVISOR),User(role=Role.ADMIN,is_active=False)):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code,403)
        self.assertFalse(AgentConfiguration.objects.exists())

    def test_base_version_aliases_reject_coercion_and_ambiguous_values(self):
        self.client.force_authenticate(User(role=Role.ADMIN))
        for version in (True,0.5,"0",[],{},None,-1,9223372036854775807):
            for key in ("base_version","expected_version","version"):
                with self.subTest(key=key,value=version):
                    self.assertEqual(self.client.put(self.url,{"desired_config":{},key:version},format="json").status_code,400)
        self.assertEqual(self.client.put(self.url,{"desired_config":{},"version":0,"base_version":1},format="json").status_code,400)
        self.assertEqual(self.client.put(self.url,{"desired_config":{},"expected_version":0},format="json").status_code,201)

    def test_success_ack_must_match_requested_values(self):
        row=AgentConfiguration.objects.create(agent=self.agent,version=1,desired_config={'heartbeat_interval': 15})
        control=RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()),uuid4());control.open()
        control.acknowledge_config(row.pk,success=True,effective_config={'heartbeat_interval': 30})
        row.refresh_from_db()
        self.assertEqual(row.state,ConfigurationState.FAILED)
        self.assertEqual(row.error_code,"INVALID_EFFECTIVE_CONFIG")

    def test_legacy_effective_settings_are_reported_without_broadening_editable_limits(self):
        control=RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()),uuid4());control.open();control.config_supported=True
        legacy={"audio_chunk_duration":7200,"audio_chunk_overlap":1,"heartbeat_interval":.5}
        control.dispatch(envelope("config_local",{"base_version":0,"local_revision":0,"effective_config":legacy}))
        self.assertEqual(AgentConfiguration.objects.get().effective_config,{'heartbeat_interval':.5})
        with self.assertRaises(ValueError):
            control.dispatch(envelope("config_local",{"base_version":0,"local_revision":1,"effective_config":{}}))
        self.client.force_authenticate(User(role=Role.ADMIN))
        self.assertEqual(self.client.put(self.url,{"base_version":0,"desired_config":legacy},format="json").status_code,400)

    def test_invalid_types_and_unsupported_parameters_are_400(self):
        self.client.force_authenticate(User(role=Role.ADMIN))
        self.client.raise_request_exception = False
        for desired in ({"audio_chunk_mode": []}, {"analysis_unit": {}},
                        {"obs_port": 65536}, {"log_level": {}},
                        {"audio_chunk_duration": 10, "audio_chunk_overlap": 20},
                        {"parametro_inventado": True}, {"heartbeat_interval": -999}):
            with self.subTest(desired=desired):
                self.assertEqual(self.client.put(self.url, {"desired_config": desired}, format="json").status_code, 400)

    def test_applied_version_still_requires_compare_and_swap(self):
        self.client.force_authenticate(User(role=Role.ADMIN))
        AgentConfiguration.objects.create(agent=self.agent, version=1, state=ConfigurationState.APPLIED,
            desired_config={'heartbeat_interval': 15}, effective_config={'heartbeat_interval': 15})
        self.assertEqual(self.client.put(self.url, {"desired_config": {'heartbeat_interval': 20}}, format="json").status_code, 409)

    def test_pending_request_does_not_hide_last_confirmed_effective(self):
        self.client.force_authenticate(User(role=Role.ADMIN))
        first = AgentConfiguration.objects.create(agent=self.agent, version=1,
            desired_config={'heartbeat_interval': 15})
        AgentConfiguration.objects.create(agent=self.agent, version=2,
            desired_config={'heartbeat_interval': 20})
        first.state = ConfigurationState.APPLIED
        first.effective_config = first.desired_config
        first.save()
        data = self.client.get(self.url).data["data"]
        self.assertEqual(data["effective_config"], first.effective_config)
        self.assertEqual(data["effective_version"], 1)

    def test_effective_payload_and_diagnostics_are_validated(self):
        row = AgentConfiguration.objects.create(agent=self.agent, version=1,
            desired_config={'heartbeat_interval': 15})
        control = RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()), uuid4()); control.open()
        with patch("backend.common.audit.AuditWriter.emit") as audit:
            control.dispatch(envelope("config_ack", {"config_id": str(row.pk), "success": True,
                "effective_config": {"agent_token": "SYNTHETIC_DO_NOT_LOG"}, "error_code": "SYNTHETIC_DO_NOT_LOG"}))
            self.assertNotIn("SYNTHETIC_DO_NOT_LOG", str(audit.call_args_list))
        row.refresh_from_db()
        self.assertEqual(row.state, ConfigurationState.FAILED)
        self.assertEqual(row.error_code, "INVALID_EFFECTIVE_CONFIG")
        self.assertEqual(row.effective_config, {})

    def test_local_revision_persists_conflict_without_overwriting_web_intent(self):
        control = RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()), uuid4()); control.open()
        control.config_supported = True
        baseline = {'heartbeat_interval': 30}
        self.assertEqual(control.dispatch(envelope("config_local", {"base_version":0,
            "local_revision":0,"effective_config":baseline}))[1]["version"], 0)
        self.client.force_authenticate(User(role=Role.ADMIN))
        result = self.client.put(self.url, {"base_version":0,"desired_config":{'heartbeat_interval': 15}}, format="json")
        self.assertEqual(result.status_code, 201)
        effective = {**baseline, 'heartbeat_interval': 20}
        control.dispatch(envelope("config_local", {"base_version":0,"local_revision":1,"effective_config":effective}))
        remote = AgentConfiguration.objects.get(source="remote")
        self.assertEqual(remote.error_code, "CONFIG_VERSION_CONFLICT")
        state = self.client.get(self.url).data["data"]
        self.assertEqual(state["state"], "fallido")
        self.assertEqual(state["desired_config"], {'heartbeat_interval': 15})
        self.assertEqual(state["effective_config"], effective)
        self.assertEqual(state["effective_local_revision"], 1)
        self.assertEqual(state["version"], 2)
        count = AgentConfiguration.objects.count()
        control.dispatch(envelope("config_local", {"base_version":2,"local_revision":1,"effective_config":effective}))
        self.assertEqual(AgentConfiguration.objects.count(), count)

    def test_lost_local_receipt_replays_on_reconnect_without_overwriting_later_web_change(self):
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        control = RemoteControl(identity, uuid4())
        control.open()
        control.config_supported = True
        control.dispatch(envelope("config_local", {"base_version": 0, "local_revision": 0,
            "effective_config": {"heartbeat_interval": 30}}))
        update = {"base_version": 0, "local_revision": 1, "effective_config": {"heartbeat_interval": 20}}
        first = control.dispatch(envelope("config_local", update))
        self.assertEqual(first, ("config_receipt", {"version": 1, "local_revision": 1}))
        control.close()
        control = RemoteControl(identity, uuid4())
        control.open()
        control.config_supported = True
        self.assertEqual(control.dispatch(envelope("config_local", update)), first)
        self.assertEqual(self.agent.configurations.count(), 2)
        with self.assertRaisesRegex(ValueError, "CONFIG_VERSION_CONFLICT"):
            control.dispatch(envelope("config_local", {**update, "effective_config": {"heartbeat_interval": 15}}))
        remote = self.agent.configurations.create(version=2, local_revision=1,
            state=ConfigurationState.APPLIED, effective_config={"heartbeat_interval": 15})
        for revision in (1, 2):
            with self.assertRaisesRegex(ValueError, "CONFIG_VERSION_CONFLICT") as rejected:
                control.dispatch(envelope("config_local", {**update, "local_revision": revision}))
            self.assertEqual(rejected.exception.effective, {"version": remote.version, "local_revision": 1,
                "effective_config": {"heartbeat_interval": 15}, "source": "remote"})
        self.assertEqual(self.agent.configurations.count(), 3)

    def test_hello_preserves_timestamp_of_last_status_until_new_telemetry(self):
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        control = RemoteControl(identity, uuid4())
        control.open()
        control.register_hello("2.1.2")
        control.dispatch(envelope("status", {"operational_code": "RECOVERY_REQUIRED", "pending": 1}))
        self.agent.refresh_from_db()
        reported = self.agent.diagnostics["status_reported_at"]

        control.register_hello("2.1.3")
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.diagnostics["status_reported_at"], reported)
        self.assertEqual(self.agent.diagnostics["operational_code"], "RECOVERY_REQUIRED")
        self.assertEqual(self.agent.diagnostics["agent_version"], "2.1.3")
        control.dispatch(envelope("status", {"pending": 0}))
        self.agent.refresh_from_db()
        self.assertNotEqual(self.agent.diagnostics["status_reported_at"], reported)
        self.assertNotIn("operational_code", self.agent.diagnostics)

    def test_new_start_waits_for_configuration_and_frozen_session_never_changes(self):
        from datetime import timedelta
        from dataclasses import replace
        from django.utils import timezone
        from .services import CaptureSessionService
        from .models import CaptureSession
        from backend.apps.operational.capture_authorization import BoxCaptureAuthorization
        now = timezone.now()
        service = CaptureSessionService()
        window = BoxCaptureAuthorization("box-3", True, now, now + timedelta(minutes=10), "agenda")
        sid = service.apply_authorization(window, now=now).session_id
        control = RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()), uuid4()); control.open()
        control.config_supported = control.chunk_config_supported = control.chunk_config_v2_supported = True
        row = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 15})
        self.assertEqual(control.commands(), [])
        session = CaptureSession.objects.get(pk=sid)
        self.assertIsNone(session.capture_chunk_negotiated)
        control.dispatch(envelope("config_ack", {"config_id":str(row.pk),"success":True,
            "effective_config":{'heartbeat_interval': 30}}))
        first = control.commands()[0]
        self.assertEqual(first["audio_chunk_duration"],60)
        self.assertEqual(first["audio_chunk_overlap"],0)
        row2 = AgentConfiguration.objects.create(agent=self.agent, version=2, desired_config={'heartbeat_interval': 20})
        control.dispatch(envelope("config_ack", {"config_id":str(row2.pk),"success":True,"effective_config":{'heartbeat_interval': 20}}))
        self.assertEqual(control.commands()[0]["audio_chunk_duration"],60)
        AgentConfiguration.objects.create(agent=self.agent, version=3, desired_config={'heartbeat_interval': 25})
        service.apply_authorization(replace(window,authorized=False,inicio=None,termino=None),now=now)
        self.assertEqual(control.commands()[0]["kind"],"detencion")
