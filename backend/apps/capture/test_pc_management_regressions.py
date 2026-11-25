import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from .authentication import authenticate_agent_header
from .models import (AgentConfiguration, AgentConnectivityEvent, AgentRegistration, AgentStatus,
                     ConfigurationState, RuntimeLease, ServerConnectivityOutage)
from .pc_registry import create_agent, revoke_agent, renew_agent
from .protocol import envelope
from .websocket import CONFIG_CAPABILITY, RemoteControl, agent_websocket, db


class SocketLifecycleTests(TransactionTestCase):
    def setUp(self):
        self.agent, self.token = create_agent(name="PC sintético", box="box-3")

    def exercise(self, messages=(), invalidate=None, capabilities=()):
        async def run():
            incoming, sent = asyncio.Queue(), []
            await incoming.put({"type": "websocket.connect"})
            await incoming.put({"type": "websocket.receive", "text": json.dumps(envelope(
                "hello", {"agent_version": "test-96", "capabilities": list(capabilities)}))})
            deferred = CONFIG_CAPABILITY in capabilities
            async def send_requests():
                for kind, data in messages:
                    await incoming.put({"type": "websocket.receive", "text": json.dumps(envelope(kind, data))})
                if not invalidate:
                    await incoming.put({"type": "websocket.disconnect", "code": 1000})
            if not deferred:
                await send_requests()
            async def send(event):
                sent.append(event)
                if event["type"] != "websocket.send":
                    return
                kind = json.loads(event["text"])["type"]
                if invalidate and kind == "ready":
                    await db(invalidate, self.agent)
                if deferred and kind == "config_sync":
                    await send_requests()
            await asyncio.wait_for(agent_websocket({
                "type": "websocket", "path": "/ws/v1/agents", "query_string": b"",
                "headers": [(b"authorization", f"Agent {self.token}".encode())],
                "client": ("192.0.2.96", 9000),
            }, incoming.get, send), timeout=3)
            return sent
        return asyncio.run(run())

    def test_socket_processes_multiple_messages_and_records_disconnect(self):
        sent = self.exercise([("status", {"pending": 2, "free_bytes": 1234, "capturing": False}), ("sync", {})])
        messages = [json.loads(e["text"]) for e in sent if e["type"] == "websocket.send"]
        self.assertEqual([m["type"] for m in messages], ["ready", "state", "state"])
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.diagnostics["pending"], 2)
        self.assertEqual(self.agent.diagnostics["agent_version"], "test-96")
        self.assertIsNone(self.agent.control_owner)
        self.assertEqual(ServerConnectivityOutage.objects.count(), 1)
        self.assertFalse(RuntimeLease.objects.filter(name="control:box-3").exists())

    def test_pending_config_is_delivered_only_after_capability_negotiation(self):
        config = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 15})
        sent = self.exercise([("sync", {})])
        messages = [json.loads(event["text"]) for event in sent if event["type"] == "websocket.send"]
        self.assertEqual([message["type"] for message in messages], ["ready", "state"])
        self.assertNotIn(CONFIG_CAPABILITY, messages[0]["payload"]["capabilities"])
        config.refresh_from_db()
        self.assertEqual(config.state, ConfigurationState.PENDING)

        ack = {"config_id": str(config.pk), "success": True, "effective_config": {'heartbeat_interval': 15}}
        sent = self.exercise([("config_ack", ack)], capabilities=[CONFIG_CAPABILITY])
        messages = [json.loads(event["text"]) for event in sent if event["type"] == "websocket.send"]
        self.assertEqual([message["type"] for message in messages], ["ready", "config_sync", "config_receipt"])
        self.assertIn(CONFIG_CAPABILITY, messages[0]["payload"]["capabilities"])
        self.assertEqual(messages[1]["payload"], {
            "config_id": str(config.pk), "version": 1, "desired_config": {'heartbeat_interval': 15}, "base_local_revision": 0,
        })
        config.refresh_from_db()
        self.assertEqual(config.state, ConfigurationState.APPLIED)

    def test_revocation_closes_already_accepted_socket(self):
        sent = self.exercise(invalidate=revoke_agent)
        self.assertEqual(sent[-1], {"type": "websocket.close", "code": 4401})
        self.assertEqual(ServerConnectivityOutage.objects.get().cause, "CREDENTIAL_REVOKED")

    def test_renewal_closes_old_socket_and_preserves_identity(self):
        sent = self.exercise(invalidate=renew_agent)
        self.assertEqual(sent[-1]["code"], 4401)
        self.assertEqual(AgentRegistration.objects.count(), 1)

    def test_replaced_socket_cannot_disconnect_new_socket_for_same_pc(self):
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        old, new = RemoteControl(identity, uuid4()), RemoteControl(identity, uuid4())
        old.open()
        new.open()
        old.close()
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.control_owner, new.owner)
        self.assertEqual(ServerConnectivityOutage.objects.count(), 0)
        self.assertEqual(new.poll(), [])

    def test_displaced_client_cannot_take_back_a_live_lease(self):
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        original, current, retry = [RemoteControl(identity, uuid4()) for _ in range(3)]
        self.assertTrue(original.open())
        self.assertTrue(current.open())
        retry.yield_replaced = True
        self.assertFalse(retry.open())
        self.assertTrue(RuntimeLease.objects.filter(name="control:box-3", owner=current.owner).exists())
        current.close()
        self.assertTrue(retry.open())
        retry.close()

    def test_reconnect_after_expired_lease_preserves_outage_without_dashboard_visit(self):
        identity = authenticate_agent_header(f"Agent {self.token}".encode())
        old, new = RemoteControl(identity, uuid4()), RemoteControl(identity, uuid4())
        old.open()
        old.register_hello("test")
        RuntimeLease.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        new.open()
        from .server_connectivity import register_server_reconnect
        register_server_reconnect(identity)
        outage = ServerConnectivityOutage.objects.get()
        self.assertIsNotNone(outage.recovered_at)
        self.assertEqual(outage.start_time_quality, "estimated")
        old.close()
        self.assertEqual(new.poll(), [])

    def test_missing_lease_is_a_controlled_replacement(self):
        control = RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()), uuid4())
        control.open()
        RuntimeLease.objects.filter(name=control.name).delete()
        for operation in (control.poll, lambda: control.dispatch(envelope("sync", {}))):
            with self.assertRaisesRegex(ValueError, "CONNECTION_REPLACED"):
                operation()


    def test_qa_multiple_pending_versions(self):
        v1 = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 10})
        v2 = AgentConfiguration.objects.create(agent=self.agent, version=2, desired_config={'heartbeat_interval': 20})
        ack2 = {"config_id": str(v2.pk), "success": True, "effective_config": {'heartbeat_interval': 20}}
        ack1 = {"config_id": str(v1.pk), "success": True, "effective_config": {'heartbeat_interval': 10}}
        self.exercise([("config_ack", ack2), ("config_ack", ack1)], capabilities=[CONFIG_CAPABILITY])
        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v2.state, ConfigurationState.APPLIED)
        self.assertEqual(v1.state, ConfigurationState.FAILED)

    def test_qa_configuracion_otro_pc(self):
        other_agent, _ = create_agent(name="Otro PC", box="box-4")
        other_config = AgentConfiguration.objects.create(agent=other_agent, version=1, desired_config={'heartbeat_interval': 10})
        ack = {"config_id": str(other_config.pk), "success": True, "effective_config": {'heartbeat_interval': 10}}
        sent = self.exercise([("config_ack", ack)])
        messages = [json.loads(e["text"])["type"] for e in sent if e["type"] == "websocket.send"]
        other_config.refresh_from_db()
        self.assertEqual(messages, ["ready", "error"])
        self.assertEqual(other_config.state, ConfigurationState.PENDING)

    def test_qa_ack_duplicado(self):
        config = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 10})
        ack = {"config_id": str(config.pk), "success": True, "effective_config": {'heartbeat_interval': 10}}
        self.exercise([("config_ack", ack)], capabilities=[CONFIG_CAPABILITY])
        config.refresh_from_db()
        first_updated = config.updated_at
        self.exercise([("config_ack", ack)])
        config.refresh_from_db()
        self.assertEqual(config.state, ConfigurationState.APPLIED)
        self.assertEqual(config.updated_at, first_updated)

    def test_qa_reconexion_pendiente(self):
        config = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 10})
        sent1 = self.exercise([], capabilities=[CONFIG_CAPABILITY])
        sent2 = self.exercise([], capabilities=[CONFIG_CAPABILITY])
        sync1 = [json.loads(e["text"]) for e in sent1 if e["type"] == "websocket.send" and json.loads(e["text"])["type"] == "config_sync"]
        sync2 = [json.loads(e["text"]) for e in sent2 if e["type"] == "websocket.send" and json.loads(e["text"])["type"] == "config_sync"]
        config.refresh_from_db()
        self.assertEqual(config.state, ConfigurationState.PENDING)
        self.assertEqual(len(sync1), 1)
        self.assertEqual(len(sync2), 1)

    def test_qa_configuracion_efectiva(self):
        config = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 15})
        ack = {"config_id": str(config.pk), "success": True}
        self.exercise([("config_ack", ack)], capabilities=[CONFIG_CAPABILITY])
        config.refresh_from_db()
        self.assertEqual(config.state, ConfigurationState.FAILED)
        self.assertEqual(config.error_code, "MISSING_EFFECTIVE_CONFIG")

    def test_qa_fallo_conserva_configuracion(self):
        v1 = AgentConfiguration.objects.create(agent=self.agent, version=1, desired_config={'heartbeat_interval': 10})
        ack1 = {"config_id": str(v1.pk), "success": True, "effective_config": {'heartbeat_interval': 10}}
        self.exercise([("config_ack", ack1)], capabilities=[CONFIG_CAPABILITY])
        v1.refresh_from_db()
        v2 = AgentConfiguration.objects.create(
            agent=self.agent, version=2, desired_config={'heartbeat_interval': 20}, effective_config=v1.effective_config
        )
        ack2 = {"config_id": str(v2.pk), "success": False, "error_code": "CONFIG_APPLY_FAILED"}
        self.exercise([("config_ack", ack2)], capabilities=[CONFIG_CAPABILITY])
        v2.refresh_from_db()
        self.assertEqual(v1.state, ConfigurationState.APPLIED)
        self.assertEqual(v1.effective_config, {'heartbeat_interval': 10})
        self.assertEqual(v2.state, ConfigurationState.FAILED)
        self.assertEqual(v2.effective_config, {'heartbeat_interval': 10})
        self.assertEqual(v2.error_code, "CONFIG_APPLY_FAILED")


class RegistryRegressionTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="regression96", email="regression96@example.test", password="Synthetic-96-only!", role="admin")
        self.client.force_authenticate(self.admin)
        self.agent, self.token = create_agent(name="PC nuevo", box="box-3")
        self.history = f"/api/v1/pcs/{self.agent.pk}/historial"

    def event(self, kind, when, outage_id, box="box-3"):
        return AgentConnectivityEvent.objects.create(
            agent_id=str(self.agent.pk), event_id=uuid4(), box=box, kind=kind,
            occurred_at=when, received_at=when, outage_id=outage_id, cause="UNKNOWN",
        )

    def test_new_pc_does_not_inherit_box_telemetry_or_connection(self):
        AgentStatus.objects.create(box="box-3", seen_at=timezone.now(), diagnostics={"agent_version": "other", "pending": 7})
        RuntimeLease.objects.create(name="control:box-3", owner=uuid4(), expires_at=timezone.now() + timedelta(minutes=1))
        row = self.client.get("/api/v1/pcs").data["data"][0]
        self.assertEqual(row["connection"], "offline")
        self.assertEqual(row["pending"], 0)
        self.assertFalse(row["capturing"])
        self.assertEqual(row["telemetry_fields"], [])
        self.assertIsNone(row["version"])
        self.assertIsNone(row["last_seen_at"])

    def test_shared_box_pcs_keep_individual_diagnostics(self):
        from .pc_registry import _generate_credential
        other = AgentRegistration(name="PC segundo", box="box-3")
        token, other.token_sha256 = _generate_credential(other.pk)
        other.save()
        first = RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()), uuid4())
        first.open(); first.register_hello("first")
        first.dispatch(envelope("status", {"pending": 7}))
        second = RemoteControl(authenticate_agent_header(f"Agent {token}".encode()), uuid4())
        second.open(); second.register_hello("second")
        rows = {r["agent_id"]: r for r in self.client.get("/api/v1/pcs").data["data"]}
        self.assertEqual(rows[str(self.agent.pk)]["pending"], 7)
        self.assertEqual(rows[str(self.agent.pk)]["connection"], "offline")
        self.assertEqual(rows[str(other.pk)]["connection"], "online")
        self.assertNotIn("pending", rows[str(other.pk)]["telemetry_fields"])
        self.assertEqual(self.agent.server_connectivity_outages.count(), 1)

    def test_expired_lease_is_persisted_once_and_recovers(self):
        control = RemoteControl(authenticate_agent_header(f"Agent {self.token}".encode()), uuid4())
        control.open(); control.register_hello("test")
        RuntimeLease.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client.get("/api/v1/pcs")
        self.client.get(self.history)
        self.assertEqual(self.agent.server_connectivity_outages.count(), 1)
        self.assertTrue(self.agent.server_connectivity_outages.get().is_active)

    def test_invalid_dates_and_reversed_range_are_rejected(self):
        for params in ({"desde": "bad"}, {"hasta": "2026-02-30"}, {"desde": "2026-11-09", "hasta": "2026-11-08"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.history, params).status_code, 400)

    def test_date_filter_keeps_recovery_outside_range(self):
        start = timezone.now().replace(hour=12, minute=0)
        outage = uuid4()
        self.event("wss.disconnected", start, outage)
        self.event("wss.reconnected", start + timedelta(days=1), outage)
        day = timezone.localdate(start).isoformat()
        result = self.client.get(self.history, {"desde": day, "hasta": day}).data["data"]["results"][0]
        self.assertIsNotNone(result["recovered_at"])
        self.assertFalse(result["active"])
        self.assertEqual(result["duration_ms"], 86400000)

    def test_reassignment_keeps_previous_box_history(self):
        self.event("wss.disconnected", timezone.now(), uuid4(), box="box-4")
        data = self.client.get(self.history).data["data"]
        self.assertEqual(data["pagination"]["total"], 1)
        self.assertEqual(data["results"][0]["box"], "box-4")
        self.assertEqual(self.client.get(self.history, {"box": "box-3"}).data["data"]["results"], [])

    def test_shared_outage_id_does_not_mix_channels(self):
        now, outage = timezone.now(), uuid4()
        self.event("wss.disconnected", now, outage)
        self.event("https.reconnected", now + timedelta(seconds=5), outage)
        rows = self.client.get(self.history).data["data"]["results"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(next(r for r in rows if r["channel"] == "wss")["active"])
