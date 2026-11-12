"""Audio sintético: negociación, snapshot y recepción grande, sin proveedores."""
import asyncio
import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase, TransactionTestCase, override_settings

from backend.apps.operational.models import OperationalConfiguration
from .authentication import AgentIdentity
from .chunk_config import CAPABILITY, byte_limit, duration
from .models import CaptureSession, FragmentJob
from .protocol import envelope
from .services import CaptureSessionService
from .storage import FragmentError
from . import test_api as api_tests
from .test_api import AGENTS, TOKEN
from .test_ingestion import IngestionFixtures, wav_bytes
from .tests import CaptureFixtures, NOW
from .websocket import RemoteControl


class ChunkSnapshotTests(CaptureFixtures, TestCase):
    def test_snapshot_survives_config_change_repeated_authorization_and_restart(self):
        self.create()
        config = OperationalConfiguration.load()
        config.audio_chunk_duration = 120
        config.audio_chunk_mode = "session"
        config.save()
        CaptureSessionService().apply_authorization(self.authorization, now=NOW)
        session = CaptureSession.objects.get()
        self.assertEqual(session.capture_chunk_config, {"audio_chunk_duration": 60, "audio_chunk_mode": "fixed",
                                                             "analysis_unit": "fragment"})
        self.assertIsNone(self.service.commands("box-3", now=NOW)[0].audio_chunk_duration)
        self.assertFalse(session.audio_profile)

    def test_resolution_rounds_window_up_and_clamps_fixed(self):
        session = CaptureSession(scheduled_start=NOW, scheduled_end=NOW + timedelta(seconds=10.2),
                                 capture_chunk_config={"audio_chunk_duration": 60, "audio_chunk_mode": "fixed"})
        self.assertEqual(duration(session), 11)
        session.scheduled_end = NOW + timedelta(seconds=2)
        self.assertEqual(duration(session), 10)
        session.scheduled_end = NOW + timedelta(seconds=120.2)
        session.capture_chunk_config["audio_chunk_mode"] = "session"
        self.assertEqual(duration(session), 121)

    def test_negotiation_is_fixed_on_first_delivery_and_stop_omits_field(self):
        self.create()
        control = RemoteControl(AgentIdentity("test", "box-3"), uuid4())
        control.chunk_config_supported = True
        with patch("django.utils.timezone.now", return_value=NOW):
            first, = control.commands()
            config = OperationalConfiguration.load()
            config.audio_chunk_duration = 300
            config.save()
            repeated, = control.commands()
        self.assertEqual(first, repeated)
        self.assertEqual(first["audio_chunk_duration"], 60)
        session = CaptureSession.objects.get()
        self.assertIs(session.capture_chunk_negotiated, True)
        self.service.acknowledge("box-3", first["command_id"], now=NOW)
        stopped = self.stop()
        control.chunk_config_supported = False
        self.assertNotIn("audio_chunk_duration", control.command_payload(stopped))

    def test_legacy_first_delivery_cannot_be_upgraded_mid_session(self):
        self.create()
        control = RemoteControl(AgentIdentity("test", "box-3"), uuid4())
        with patch("django.utils.timezone.now", return_value=NOW):
            first, = control.commands()
            control.chunk_config_supported = True
            second, = control.commands()
        self.assertNotIn("audio_chunk_duration", first)
        self.assertEqual(first, second)
        self.assertIs(CaptureSession.objects.get().capture_chunk_negotiated, False)

    def test_historical_session_has_no_inferred_config(self):
        self.create()
        CaptureSession.objects.update(capture_chunk_config={})
        command, = self.service.commands("box-3", now=NOW, chunk_config_supported=True)
        self.assertIsNone(command.audio_chunk_duration)
        self.assertIs(CaptureSession.objects.get().capture_chunk_negotiated, False)


class ConfiguredIngestionTests(IngestionFixtures, TestCase):
    def configure(self, seconds=3600):
        CaptureSession.objects.update(capture_chunk_config={"audio_chunk_duration": seconds, "audio_chunk_mode": "session"},
                                      capture_chunk_negotiated=True)

    def timeline(self, seconds, chunk=3600, overlap=16000):
        return dict(session_start_sample=0, session_end_sample=seconds * 16000,
                    new_audio_start_sample=0, sample_rate=16000, chunk_samples=chunk * 16000,
                    overlap_samples=overlap)

    def test_large_full_session_and_retry_are_durable_and_processable(self):
        from .processing import FragmentJobProcessor
        from .test_processing import FakeAnalysis
        self.configure()
        data = wav_bytes(b"\0\0" * (900 * 16000))  # >25 MiB
        args = dict(content=data, temporal=self.timeline(900), now=NOW + timedelta(seconds=910))
        first, created = self.receive(**args)
        self.assertTrue(created)
        second, created = self.receive(**args)
        self.assertFalse(created)
        self.assertEqual(first, second)
        analysis = FakeAnalysis()
        FragmentJobProcessor(self.storage, analysis).process_next()
        self.assertEqual(analysis.calls[0][0].end, 900 * 16000)
        self.assertEqual(analysis.calls[0][0].context_start, 0)

    def test_legacy_still_rejects_chunk_over_600_and_keeps_size_limit(self):
        session = CaptureSession.objects.get()
        self.assertEqual(byte_limit(session, self.storage.max_bytes), self.storage.max_bytes)
        with self.assertRaises(FragmentError) as error:
            self.receive(temporal=self.timeline(1, chunk=601))
        self.assertEqual(error.exception.code, "INVALID_AUDIO_TIMELINE")

    def test_requested_profile_and_overlap_are_required(self):
        self.configure()
        for temporal in (None, self.timeline(1, chunk=60), self.timeline(1, overlap=0)):
            with self.subTest(temporal=temporal), self.assertRaises(FragmentError):
                self.receive(content=wav_bytes(b"\0\0" * 16000), temporal=temporal)
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(self.blobs())

    def test_revocation_bounds_audio_and_rollback_does_not_freeze_profile(self):
        self.configure()
        CaptureSession.objects.update(authorization_ended_at=NOW + timedelta(seconds=10.5))
        with self.assertRaises(FragmentError) as error:
            self.receive(content=wav_bytes(b"\0\0" * 16000), temporal=self.timeline(1))
        self.assertEqual(error.exception.code, "INVALID_AUDIO_TIMELINE")
        self.assertEqual(CaptureSession.objects.get().audio_profile, {})
        self.assertFalse(self.blobs())

    def test_configured_size_is_bounded_before_publishing(self):
        self.configure()
        CaptureSession.objects.update(capture_chunk_config={"audio_chunk_duration": 10, "audio_chunk_mode": "fixed"})
        with self.assertRaises(FragmentError) as error:
            self.receive(content=wav_bytes(b"\0\0" * (20 * 16000)), temporal=self.timeline(20, chunk=10))
        self.assertEqual(error.exception.code, "FRAGMENT_TOO_LARGE")
        self.assertFalse(self.blobs())


# Reuse API fixtures without inheriting the legacy test methods.
class ConfiguredUploadTests(IngestionFixtures, TestCase):
    payload = api_tests.FragmentAPITests.payload

    def setUp(self):
        from rest_framework.test import APIClient
        super().setUp()
        config = override_settings(CAPTURE_FRAGMENT_ROOT=self.root, CAPTURE_AGENTS=AGENTS)
        config.enable()
        self.addCleanup(config.disable)
        clock = patch("django.utils.timezone.now", return_value=NOW + timedelta(seconds=20))
        clock.start()
        self.addCleanup(clock.stop)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)

    def test_v2_large_upload_works_even_when_file_is_first(self):
        CaptureSession.objects.update(capture_chunk_config={"audio_chunk_duration": 3600, "audio_chunk_mode": "session"},
                                      capture_chunk_negotiated=True)
        data = wav_bytes(b"\0\0" * (900 * 16000))
        temporal = dict(session_start_sample=0, session_end_sample=900 * 16000,
                        new_audio_start_sample=0, sample_rate=16000, chunk_samples=3600 * 16000,
                        overlap_samples=16000)
        with patch("django.utils.timezone.now", return_value=NOW + timedelta(seconds=910)):
            response = self.client.post("/api/v2/internal/fragments", self.payload(data, **temporal), format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(list(self.root.glob("*.part")))

    def test_legacy_session_cannot_use_negotiated_size_allowance(self):
        data = wav_bytes(b"\0\0" * (900 * 16000))
        temporal = dict(session_start_sample=0, session_end_sample=900 * 16000,
                        new_audio_start_sample=0, sample_rate=16000, chunk_samples=3600 * 16000,
                        overlap_samples=16000)
        response = self.client.post("/api/v2/internal/fragments", self.payload(data, **temporal), format="multipart")
        self.assertEqual(response.status_code, 413, response.data)
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(list(self.root.glob("*.part")))


    def test_other_negotiated_session_does_not_raise_legacy_acceptance_limit(self):
        # Otra sesión del mismo box eleva la cota preliminar del parser; la
        # sesión destinataria sigue sometida a su límite legacy exacto.
        other = CaptureSession.objects.get()
        other.pk = uuid4()
        other.state = "completada"
        other.actual_end = NOW
        other.authorization_ended_at = NOW
        other.capture_chunk_config = {"audio_chunk_duration": 3600, "audio_chunk_mode": "session"}
        other.capture_chunk_negotiated = True
        other.save(force_insert=True)
        data = wav_bytes(b"\0\0" * (900 * 16000))
        temporal = dict(session_start_sample=0, session_end_sample=900 * 16000,
                        new_audio_start_sample=0, sample_rate=16000, chunk_samples=3600 * 16000,
                        overlap_samples=16000)
        response = self.client.post("/api/v2/internal/fragments", self.payload(data, **temporal), format="multipart")
        self.assertEqual(response.status_code, 413, response.data)
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(list(self.root.glob("*.part")))
        self.assertFalse(self.blobs())


class ChunkHandshakeTests(CaptureFixtures, TransactionTestCase):
    @override_settings(CAPTURE_AGENTS=AGENTS)
    def test_real_asgi_ready_negotiation_and_command(self):
        from backend.config.asgi import application
        self.create()
        async def exercise(capabilities):
            received, sent = asyncio.Queue(), []
            await received.put({"type": "websocket.connect"})
            await received.put({"type": "websocket.receive", "text": json.dumps(envelope(
                "hello", {"agent_version": "test", "capabilities": capabilities}))})
            async def send(event):
                sent.append(event)
                if event["type"] == "websocket.send" and json.loads(event["text"])["type"] == "command":
                    await received.put({"type": "websocket.disconnect"})
            await application({"type": "websocket", "path": "/ws/v1/agents",
                               "headers": [(b"authorization", ("Agent " + TOKEN).encode())],
                               "query_string": b""}, received.get, send)
            return [json.loads(e["text"]) for e in sent if "text" in e]
        with patch("django.utils.timezone.now", return_value=NOW):
            messages = asyncio.run(exercise([CAPABILITY, "audio.v2"]))
            legacy = asyncio.run(exercise([]))
            without_v2 = asyncio.run(exercise([CAPABILITY]))
        ready = next(m["payload"] for m in messages if m["type"] == "ready")
        command = next(m["payload"] for m in messages if m["type"] == "command")
        self.assertIn(CAPABILITY, ready["capabilities"])
        self.assertEqual(command["audio_chunk_duration"], 60)
        self.assertNotIn(CAPABILITY, next(m["payload"] for m in legacy if m["type"] == "ready")["capabilities"])
        self.assertFalse(any(m["type"] == "command" for m in legacy))
        self.assertEqual(next(m["payload"] for m in legacy if m["type"] == "error"),
                         {"code": "CAPABILITIES_CHANGED", "recoverable": False})

        self.assertNotIn(CAPABILITY, next(m["payload"] for m in without_v2 if m["type"] == "ready")["capabilities"])
        self.assertFalse(any(m["type"] == "command" for m in without_v2))
        self.assertEqual(next(m["payload"] for m in without_v2 if m["type"] == "error"),
                         {"code": "CAPABILITIES_CHANGED", "recoverable": False})
        self.assertIs(CaptureSession.objects.get().capture_chunk_negotiated, True)

        # Revocar cancela el inicio pendiente: aun sin capacidad debe entregarse
        # la detención para apagar una captura que pudo comenzar sin ACK.
        from dataclasses import replace
        denied = replace(self.authorization, authorized=False, inicio=None, termino=None)
        self.service.apply_authorization(denied, now=NOW + timedelta(seconds=30))
        with patch("django.utils.timezone.now", return_value=NOW + timedelta(seconds=31)):
            stopped = asyncio.run(exercise([]))
        stop = next(m["payload"] for m in stopped if m["type"] == "command")
        self.assertEqual(stop["kind"], "detencion")
        self.assertNotIn("audio_chunk_duration", stop)
        self.assertFalse(any(m["type"] == "error" for m in stopped))


class NonOverlappingSnapshotTests(CaptureFixtures, TestCase):
    def control(self, *, v2=True):
        control = RemoteControl(AgentIdentity("test", "box-3"), uuid4())
        control.chunk_config_supported = True
        control.chunk_config_v2_supported = v2
        return control

    def test_v2_freezes_zero_overlap_and_reconnect_cannot_downgrade(self):
        self.create()
        control = self.control()
        with patch("django.utils.timezone.now", return_value=NOW):
            first, = control.commands()
            session = CaptureSession.objects.get()
            self.assertEqual(session.capture_chunk_config["analysis_unit"], "fragment")
            self.assertEqual(session.capture_chunk_config["audio_chunk_overlap"], 0)
            self.assertEqual(first["audio_chunk_overlap"], 0)
            self.assertEqual(first, self.control().commands()[0])
            with self.assertRaisesMessage(ValueError, "CAPABILITIES_CHANGED"):
                self.control(v2=False).commands()
        session.refresh_from_db()
        self.assertEqual(session.capture_chunk_config["audio_chunk_overlap"], 0)
        self.service.acknowledge("box-3", first["command_id"], now=NOW)
        stopped = self.stop()
        data = self.control(v2=False).command_payload(stopped)
        self.assertNotIn("audio_chunk_overlap", data)
        self.assertNotIn("audio_chunk_duration", data)

    def test_existing_v1_snapshot_stays_unchanged_on_v2_reconnect(self):
        self.create()
        old = {"audio_chunk_duration": 60, "audio_chunk_mode": "fixed"}
        CaptureSession.objects.update(capture_chunk_config=old, capture_chunk_negotiated=True)
        with patch("django.utils.timezone.now", return_value=NOW):
            first, = self.control(v2=False).commands()
            repeated, = self.control().commands()
        self.assertEqual(first, repeated)
        self.assertNotIn("audio_chunk_overlap", repeated)
        self.assertEqual(CaptureSession.objects.get().capture_chunk_config, old)

    def test_new_v1_delivery_cannot_upgrade_on_v2_reconnect(self):
        self.create()
        with patch("django.utils.timezone.now", return_value=NOW):
            first, = self.control(v2=False).commands()
            saved = CaptureSession.objects.get().capture_chunk_config
            repeated, = self.control().commands()
        self.assertEqual(first, repeated)
        self.assertEqual(saved["audio_chunk_overlap"], 1)
        self.assertEqual(CaptureSession.objects.get().capture_chunk_config, saved)


class NonOverlappingIngestionTests(IngestionFixtures, TestCase):
    def configure(self):
        CaptureSession.objects.update(
            scheduled_end=NOW + timedelta(seconds=3700),
            capture_chunk_config={"audio_chunk_duration": 600, "audio_chunk_mode": "fixed",
                                  "audio_chunk_overlap": 0, "analysis_unit": "fragment"},
            capture_chunk_negotiated=True)

    def receive_block(self, number, seconds=600, overlap=0):
        start = number * 600 * 16000
        temporal = dict(session_start_sample=start, session_end_sample=start + seconds * 16000,
                        new_audio_start_sample=start, sample_rate=16000, chunk_samples=600 * 16000,
                        overlap_samples=overlap)
        return self.receive(number=number, content=wav_bytes(b"\x01\0" * seconds * 16000),
                            captured_at=NOW + timedelta(seconds=10 + number * 600),
                            now=NOW + timedelta(seconds=10 + number * 600 + seconds), temporal=temporal)

    def test_hour_creates_exactly_six_jobs_and_retries_do_not_duplicate(self):
        self.configure()
        for number in range(6):
            receipt, created = self.receive_block(number)
            self.assertTrue(created)
            retry, created = self.receive_block(number)
            self.assertFalse(created)
            self.assertEqual(receipt, retry)
        self.assertEqual(FragmentJob.objects.count(), 6)
        session = CaptureSession.objects.get()
        self.assertEqual(session.next_sequence, 6)
        self.assertEqual(session.audio_profile["overlap_samples"], 0)
        self.assertEqual(FragmentJob.objects.order_by("sequence__number").last().temporal["session_end_sample"], 3600 * 16000)

    def test_last_partial_is_only_new_audio_and_profile_cannot_change(self):
        self.configure()
        self.receive_block(0)
        with self.assertRaises(FragmentError):
            self.receive_block(1, seconds=1, overlap=16000)
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.receive_block(1, seconds=1)
        final = FragmentJob.objects.order_by("sequence__number").last().temporal
        self.assertEqual(final["new_audio_start_sample"], 600 * 16000)
        self.assertEqual(final["session_end_sample"], 601 * 16000)


class NonOverlappingHandshakeTests(CaptureFixtures, TransactionTestCase):
    @override_settings(CAPTURE_AGENTS=AGENTS)
    def test_v2_ready_advertises_both_versions_and_delivers_explicit_overlap(self):
        from backend.config.asgi import application
        from .chunk_config import CAPABILITY_V2
        self.create()

        async def exercise():
            received, sent = asyncio.Queue(), []
            await received.put({"type": "websocket.connect"})
            await received.put({"type": "websocket.receive", "text": json.dumps(envelope(
                "hello", {"agent_version": "test", "capabilities": [CAPABILITY, CAPABILITY_V2, "audio.v2"]}))})

            async def send(event):
                sent.append(event)
                if event["type"] == "websocket.send" and json.loads(event["text"])["type"] == "command":
                    await received.put({"type": "websocket.disconnect"})

            await application({"type": "websocket", "path": "/ws/v1/agents",
                               "headers": [(b"authorization", ("Agent " + TOKEN).encode())],
                               "query_string": b""}, received.get, send)
            return [json.loads(e["text"]) for e in sent if "text" in e]

        with patch("django.utils.timezone.now", return_value=NOW):
            messages = asyncio.run(exercise())
        ready = next(m["payload"] for m in messages if m["type"] == "ready")
        command = next(m["payload"] for m in messages if m["type"] == "command")
        self.assertIn(CAPABILITY, ready["capabilities"])
        self.assertIn(CAPABILITY_V2, ready["capabilities"])
        self.assertEqual(command["audio_chunk_overlap"], 0)
        self.assertEqual(command["audio_chunk_duration"], 60)
