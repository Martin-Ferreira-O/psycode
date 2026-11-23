import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from backend.apps.accounts.models import Role, User
from backend.apps.analysis.domain import AnalysisState, Fragment, JevDecision, Transcription, Word
from backend.apps.analysis.tests.test_integration import answer
from backend.apps.capture.pc_registry import create_agent, revoke_agent
from backend.config.composition import analysis_worker

from .models import OperationalConfiguration, SMILE_TIMEZONE

TEST_SMILE_URL = "https://smile.example.test/index.php/"


class ProcessingConfigurationTests(APITestCase):
    url = "/api/v1/configuracion-operativa"
    profile_url = "/api/v2/internal/smile-configuration"
    collections = "/api/v2/internal/agenda-collections"

    def setUp(self):
        self.client.force_authenticate(User.objects.create_user(
            username="processing-admin", email="processing@example.test", role=Role.ADMIN,
        ))
        self.first, first_key = create_agent(name="Primer PC", box="box-3")
        self.second, second_key = create_agent(name="Segundo PC", box="box-4")
        self.machines = [APIClient(), APIClient()]
        for client, key in zip(self.machines, (first_key, second_key), strict=True):
            client.credentials(HTTP_AUTHORIZATION="Agent " + key)

    def put(self, **data):
        return self.client.put(self.url, data, format="json")

    def test_threshold_update_changes_next_analysis_on_same_worker(self):
        self.assertEqual(self.client.get(self.url).data["data"]["jev_threshold"], 0.55)
        for value in (True, "0.55", None, -0.1, 1.1):
            with self.subTest(value=value):
                self.assertEqual(self.put(jev_threshold=value).status_code, 400)
        self.assertEqual(self.client.get(self.url).data["data"]["jev_threshold"], 0.55)

        with TemporaryDirectory() as root:
            worker = analysis_worker(directory=root, alert_store=Mock(), audit=Mock(), ledger=Mock())
            worker.transcriptor = Mock()
            worker.transcriptor.transcribe.return_value = Transcription(
                "Ojalá no despertar", (Word("Ojalá no despertar", 0, 1, "S1"),), "deleted",
            )
            worker.analyzer = Mock()
            worker.analyzer.evaluate.return_value = JevDecision(
                "jev-1.14.0", "afirmacion_propia", (0.1, 0.7, *[0.1] * 6), 1, 1, evidence_turns={"1": ["t0"]},
                text_evidence={"t0": {"choice": "nivel_1", "score": .7}},
            )
            worker.register_signals = Mock()

            def analyze():
                fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc),
                                    Path(root) / "synthetic.pcm", analysis_unit="fragment")
                return worker.process(fragment, roles={"S1": "patient"}).state

            self.assertEqual(analyze(), AnalysisState.SIGNAL)
            self.assertEqual(self.put(jev_threshold=0.8).status_code, 200)
            self.assertEqual(analyze(), AnalysisState.INDETERMINATE)
            self.assertEqual(self.put(jev_threshold=0.7).status_code, 200)
            self.assertEqual(analyze(), AnalysisState.SIGNAL)

            checkpoint = Mock(data={})
            self.assertEqual(worker._threshold(checkpoint), 0.7)
            self.assertEqual(self.put(jev_threshold=0.9).status_code, 200)
            self.assertEqual(worker._threshold(checkpoint), 0.7)
            self.assertEqual(worker._threshold(Mock(data={"roles": {}})), 0.55)

    def assign(self, agent, **fields):
        response = self.put(**{
            "smile_collector_id": str(agent.pk), "smile_source": "smile", "smile_boxes": ["box-3", "box-4"],
            "smile_url": "https://smile.example.test/index.php", **fields,
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def profile(self, machine):
        response = machine.get(self.profile_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("no-store", response["Cache-Control"])
        return response.data["data"]

    def issue(self, machine, profile):
        return machine.post(self.collections, {
            "source": "smile", "revision": profile["revision"],
        }, format="json")

    @override_settings(SMILE_DEFAULT_URL=TEST_SMILE_URL)
    def test_smile_defaults_are_available_to_admin_and_assigned_agent(self):
        initial = self.client.get(self.url).data["data"]
        self.assertEqual(initial["smile_url"], TEST_SMILE_URL)
        self.assertEqual(initial["smile_timezone"], SMILE_TIMEZONE)
        self.assertIsNone(self.profile(self.machines[0]))

        assigned = self.put(smile_collector_id=str(self.first.pk), smile_boxes=["box-3"])
        self.assertEqual(assigned.status_code, 200, assigned.data)
        profile = self.profile(self.machines[0])
        self.assertEqual((profile["url"], profile["timezone"]), (TEST_SMILE_URL, SMILE_TIMEZONE))
        self.assertEqual(self.put(smile_timezone="UTC").status_code, 400)
        self.assertEqual(self.put(smile_timezone=SMILE_TIMEZONE).status_code, 200)
        self.assertEqual(self.profile(self.machines[0]), profile)

    def test_reassignment_revokes_old_agent_and_stale_collection(self):
        old, new = self.machines
        self.assertEqual(APIClient().get(self.profile_url).status_code, 401)
        self.assertIsNone(self.profile(old))
        config = self.assign(self.first)
        self.assertEqual((config["jev_model"], config["speechmatics_model"]), ("1.14", "enhanced"))
        self.assertIn(str(self.second.pk), [pc["id"] for pc in config["options"]["smile_collectors"]])
        profile = self.profile(old)
        self.assertEqual(set(profile), {"source", "url", "interval", "timeout", "request_timeout", "format", "timezone", "revision"})
        self.assertEqual(profile["url"], "https://smile.example.test/index.php/")
        issued = self.issue(old, profile)
        self.assertEqual(issued.status_code, 201)
        self.assertIsNone(self.profile(new))
        self.assertEqual(self.issue(new, profile).status_code, 403)

        self.assign(self.second, smile_interval=60)
        self.assertIsNone(self.profile(old))
        self.assertEqual(self.issue(old, profile).status_code, 403)
        current = self.profile(new)
        self.assertEqual(current["interval"], 60)
        self.assertEqual(self.issue(new, profile).status_code, 409)
        self.assertEqual(self.issue(new, current).status_code, 201)
        catalog = old.post("/api/v2/internal/smile-room-catalogues", {
            "version": "1.0", "source": "smile", "collection_id": issued.data["data"]["collection_id"],
            "rooms": [{"box": "box-3", "name": "Box 3", "smile_box_id": "20"}],
        }, format="json")
        self.assertEqual(catalog.status_code, 403)
        disabled = self.put(smile_collector_id=None)
        self.assertEqual(disabled.status_code, 200, disabled.data)
        self.assertIsNone(self.profile(new))
        self.assertEqual(self.issue(new, current).status_code, 403)

    def test_validation_rejects_invalid_values_atomically(self):
        self.assign(self.first)
        revoke_agent(self.second)
        for field, value in (
            ("jev_model", 1.14), ("jev_model", "latest"), ("speechmatics_model", "unknown"),
            ("smile_collector_id", str(self.second.pk)), ("smile_url", "https://user@smile.test/index.php/"),
            ("smile_url", "http://smile.test/index.php/"), ("smile_url", ""),
            ("smile_interval", "30"), ("smile_interval", True), ("smile_timeout", 0), ("smile_request_timeout", 301),
            ("smile_timezone", "../UTC"), ("smile_format", "pdf"), ("smile_source", "ámbito"),
            ("smile_boxes", ["box-3", "box-3"]), ("smile_boxes", ["box-999"]),
        ):
            with self.subTest(field=field, value=value):
                response = self.put(**{field: value})
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data["error"]["details"]["fields"])
        self.assertEqual(self.put(smile_format="smile.excel.v1").status_code, 400)
        self.assertEqual(self.client.get(self.url).data["data"]["smile_collector_id"], str(self.first.pk))

    def test_in_flight_catalogue_cannot_publish_after_profile_changes(self):
        machine = self.machines[0]
        self.assign(self.first)
        previous = self.profile(machine)
        issued = self.issue(machine, previous)
        self.assertEqual(issued.status_code, 201, issued.data)
        updated = self.put(smile_format="smile.excel.v1", smile_boxes=["box-3"])
        self.assertEqual(updated.status_code, 200, updated.data)
        catalog = machine.post("/api/v2/internal/smile-room-catalogues", {
            "version": "1.0", "source": "smile", "collection_id": issued.data["data"]["collection_id"],
            "rooms": [{"box": "box-3", "name": "Box 3", "smile_box_id": "20"}],
        }, format="json")
        self.assertEqual(catalog.status_code, 409, catalog.data)
        self.assertEqual(catalog.data["error"]["code"], "AGENDA_CONFIGURATION_CHANGED")
        next_collection = self.issue(machine, self.profile(machine))
        self.assertEqual(next_collection.data["data"]["formats"], ["smile.excel.v1"])

    def test_worker_uses_latest_models_without_reconstruction(self):
        speech_requests, jev_requests = [], []

        def speech(request):
            if request.method == "POST":
                body = request.content.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0]
                speech_requests.append(json.loads(body)["transcription_config"])
                return httpx.Response(201, json={"id": "synthetic"})
            if request.url.path.endswith("/transcript"):
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={"job": {"status": "done"}})

        def jev(request):
            model = json.loads(request.content)["model"]
            jev_requests.append(model)
            return httpx.Response(200, json=answer(model=model))

        with TemporaryDirectory() as root, patch.dict(os.environ, {
            "SPEECHMATICS_API_KEY": "test", "TYPESAFE_API_KEY": "test",
            "PSYCODE_EXTERNAL_PROCESSING_ENABLED": "1", "JEV_PROVIDER": "typesafe",
            "SPEECHMATICS_MODEL": "invalid", "JEV_MODEL": "invalid",
        }), httpx.Client(transport=httpx.MockTransport(speech)) as speech_client, httpx.Client(
            transport=httpx.MockTransport(jev),
        ) as jev_client:
            worker = analysis_worker(directory=root, speechmatics_http=speech_client, jev_http=jev_client)
            audio = Path(root) / "synthetic.pcm"
            audio.write_bytes(b"\0\0" * 16000)

            def cycle():
                fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc), audio, end=16000)
                worker.transcriptor.transcribe(fragment)
                worker.analyzer.evaluate({}, [])

            cycle()
            for model in ("standard", "melia-1", "oak-1"):
                self.assertEqual(self.put(jev_model="1.13", speechmatics_model=model).status_code, 200)
                cycle()
            self.assertEqual(jev_requests, ["jev-1.14.0", *["jev-1.13.0"] * 3])
            self.assertEqual([item["model"] for item in speech_requests], ["enhanced", "standard", "melia-1", "oak-1"])
            self.assertEqual(speech_requests[0]["domain"], "medical")
            self.assertIn("additional_vocab", speech_requests[1])
            for item in speech_requests[2:]:
                self.assertEqual((item["language"], item["language_hints"]), ("multi", ["es"]))
                self.assertNotIn("additional_vocab", item)
                self.assertNotIn("domain", item)


class SmileMigrationTests(TransactionTestCase):
    @override_settings(
        CAPTURE_AGENTS={"old-agent": {"box": "box-5", "token_sha256": "a" * 64}},
        SMILE_DEFAULT_URL=TEST_SMILE_URL,
    )
    def test_imports_legacy_scope_and_defaults(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate([("operational", "0003_audiochunkconfigurationchange_and_more")])
        with patch.dict(os.environ, {
            "CAPTURE_AGENDA_SOURCES": json.dumps({"legacy": {"collector_id": "old-agent", "boxes": ["box-5"]}}),
        }):
            MigrationExecutor(connection).migrate(latest)
        config = OperationalConfiguration.objects.get(pk=1)
        self.assertEqual((config.jev_model, config.speechmatics_model), ("1.14", "enhanced"))
        self.assertEqual(config.smile_legacy_sources, {"legacy": {"collector_id": "old-agent", "boxes": ["box-5"]}})
        self.assertEqual((config.smile_source, config.smile_boxes), ("legacy", ["box-5"]))
        self.assertEqual(config.smile_url, TEST_SMILE_URL)

    @override_settings(SMILE_DEFAULT_URL=TEST_SMILE_URL)
    def test_existing_custom_url_survives_fixed_timezone_migration(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        previous = [("operational", "0004_central_processing_and_smile")]
        executor.migrate(previous)
        legacy = executor.loader.project_state(previous).apps.get_model("operational", "OperationalConfiguration")
        collector, _ = create_agent(name="Colector", box="box-3")
        custom_url = "https://custom-smile.example.test/index.php/"
        legacy.objects.update_or_create(pk=1, defaults={
            "smile_url": custom_url, "smile_timezone": "UTC", "smile_collector_id": collector.pk, "smile_revision": 4,
        })

        MigrationExecutor(connection).migrate(latest)

        config = OperationalConfiguration.objects.get(pk=1)
        self.assertEqual((config.smile_url, config.smile_revision), (custom_url, 5))
