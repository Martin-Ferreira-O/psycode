"""Contrato, leases y audio versionado; no importa el paquete del agente."""
import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from .authentication import AgentIdentity, authenticate_agent_header
from .test_api import AGENTS, TOKEN
from .test_ingestion import IngestionFixtures, wav_bytes
from .tests import NOW, CaptureFixtures
from .models import FragmentJob, CaptureSession, AgentStatus
from .storage import FragmentError
from .protocol import decode, envelope
from .websocket import RemoteControl, agent_websocket
from . import leases
from rest_framework.exceptions import AuthenticationFailed

from backend.common.errors import ServiceError
from .agent_registry import create_agent, revoke_agent

class AudioTimelineTests(IngestionFixtures, TestCase):
    def timeline(self, start=0, end=160000, new=0):
        return dict(session_start_sample=start, session_end_sample=end, new_audio_start_sample=new,
                    sample_rate=16000, chunk_samples=160000, overlap_samples=16000)

    def test_overlap_partial_retry_and_frozen_profile(self):
        t = self.timeline()
        content = wav_bytes(b'\0\0'*160000)
        first, created = self.receive(content=content, temporal=t)
        again, created = self.receive(content=content, temporal=t)
        self.assertFalse(created)
        self.assertEqual(first, again)
        self.receive(content=wav_bytes(b'\0\0'*32000), number=1,
                     captured_at=NOW+timedelta(seconds=19), now=NOW+timedelta(seconds=22),
                     temporal=self.timeline(144000,176000,160000))
        self.assertEqual(FragmentJob.objects.count(),2)
        with self.assertRaises(FragmentError):
            self.receive(content=content, number=2, captured_at=NOW+timedelta(seconds=20),
                         temporal=self.timeline(160000,320000,176000))

    def test_sample_count_continuity_and_upper_window_rejected(self):
        for t in (self.timeline(end=10),self.timeline(new=1),self.timeline(start=1),self.timeline(end=1600000)):
            with self.subTest(t=t), self.assertRaises(FragmentError):
                self.receive(temporal=t)
        content=wav_bytes(b'\0\0'*160000)
        with self.assertRaises(FragmentError):
            self.receive(content=content, temporal=self.timeline(), captured_at=self.session.scheduled_end-timedelta(seconds=1),
                         now=self.session.scheduled_end+timedelta(seconds=1))
        self.assertEqual(FragmentJob.objects.count(),0)

    def test_v1_does_not_allow_silent_extra_fields(self):
        from .serializers import FragmentSerializer
        from django.http import QueryDict
        q=QueryDict('',mutable=True);q['session_start_sample']='0'
        self.assertFalse(FragmentSerializer(data=q).is_valid())

class ControlTests(CaptureFixtures, TestCase):
    @override_settings(CAPTURE_AGENTS=AGENTS)
    def test_authentication_and_owner_replacement(self):
        identity=authenticate_agent_header(('Agent '+TOKEN).encode())
        first,second=RemoteControl(identity,uuid4()),RemoteControl(identity,uuid4())
        first.open();second.open()
        with self.assertRaisesRegex(ValueError,'CONNECTION_REPLACED'):
            first.poll()
        self.assertEqual(second.poll(),[])
        leases.release(first.name,first.owner)
        self.assertTrue(leases.owned(second.name,second.owner))

    def test_coordinator_exclusion_expiry(self):
        first,second=uuid4(),uuid4()
        self.assertTrue(leases.acquire('coordinator',first))
        self.assertFalse(leases.acquire('coordinator',second))
        from .models import RuntimeLease
        RuntimeLease.objects.filter(name='coordinator').update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertTrue(leases.acquire('coordinator',second))

    def test_duplicate_ack_is_durable_and_box_is_derived_from_identity(self):
        session=self.create()
        control=RemoteControl(AgentIdentity('test','box-3'),uuid4());control.open()
        with patch('django.utils.timezone.now',return_value=NOW+timedelta(seconds=1)):
            command,=control.poll()
            data=dict(command_id=command['command_id'],session_id=str(session.session_id),success=True,
                      occurred_at=(NOW+timedelta(seconds=1)).isoformat())
            a=control.dispatch(envelope('command_ack',data))
            b=control.dispatch(envelope('command_ack',data))
            self.assertEqual(a,b)
            with self.assertRaisesRegex(ValueError,'BOX_FORBIDDEN'):
                control.dispatch(envelope('heartbeat',dict(session_id=str(session.session_id),box='box-4')))
        self.assertEqual(CaptureSession.objects.get().state,'activa')

    def test_protocol_rejects_bad_version_uuid_and_naive_time(self):
        for changes in ({'protocol_version':'9'},{'message_id':'bad'},{'sent_at':'2026-10-27T00:00:00'}):
            m=envelope('sync',{});m.update(changes)
            with self.assertRaises(ValueError):decode(json.dumps(m))

    def test_status_acepta_autonomia_y_alertas_de_almacenamiento(self):
        control = RemoteControl(
            AgentIdentity("test", "box-3"),
            uuid4(),
        )
        control.open()

        response = control.dispatch(
            envelope(
                "status",
                {
                    "obs": "ready",
                    "capturing": False,
                    "pending": 2,
                    "free_bytes": 20 * 1024**3,
                    "remaining_seconds": 7200,
                    "smile_last_sync": None,
                    "operational_code": "STORAGE_WARNING",
                },
            )
        )

        self.assertIsNotNone(response)

        status_row = AgentStatus.objects.get(
            box="box-3",
        )

        self.assertEqual(
            status_row.diagnostics["free_bytes"],
            20 * 1024**3,
        )

        self.assertEqual(
            status_row.diagnostics["remaining_seconds"],
            7200,
        )

        self.assertEqual(
            status_row.diagnostics["operational_code"],
            "STORAGE_WARNING",
        )

    @override_settings(
        CAPTURE_AGENT_AUTH_ID_LIMIT=2,
        CAPTURE_AGENT_AUTH_IP_LIMIT=100,
        CAPTURE_AGENT_AUTH_WINDOW_SECONDS=60,
    )
    def test_agent_auth_limita_intentos_repetidos_por_identidad(self):
        header = (
            "Agent abusive-agent." + "x" * 43
        ).encode()

        for _ in range(2):
            with self.assertRaises(AuthenticationFailed):
                authenticate_agent_header(
                    header,
                    source_ip="192.0.2.10",
                )

        with self.assertRaises(ServiceError) as limited:
            authenticate_agent_header(
                header,
                source_ip="192.0.2.10",
            )

        self.assertEqual(
            limited.exception.code,
            "AUTH_RATE_LIMITED",
        )
        self.assertEqual(
            limited.exception.status,
            429,
        )

    @override_settings(
        CAPTURE_AGENT_AUTH_ID_LIMIT=100,
        CAPTURE_AGENT_AUTH_IP_LIMIT=2,
        CAPTURE_AGENT_AUTH_WINDOW_SECONDS=60,
    )
    def test_agent_auth_limita_intentos_abusivos_por_ip(self):
        for index in range(2):
            header = (
                f"Agent unknown-{index}." + "x" * 43
            ).encode()

            with self.assertRaises(AuthenticationFailed):
                authenticate_agent_header(
                    header,
                    source_ip="192.0.2.20",
                )

        third_header = (
            "Agent unknown-3." + "x" * 43
        ).encode()

        with self.assertRaises(ServiceError) as limited:
            authenticate_agent_header(
                third_header,
                source_ip="192.0.2.20",
            )

        self.assertEqual(
            limited.exception.code,
            "AUTH_RATE_LIMITED",
        )
        self.assertEqual(
            limited.exception.status,
            429,
        )
    def test_revocacion_invalida_conexion_activa_de_pc_administrado(self):
        agent, token = create_agent(
            name="PC Box 3",
            box="box-3",
        )

        identity = authenticate_agent_header(
            ("Agent " + token).encode(),
        )

        control = RemoteControl(
            identity,
            uuid4(),
        )
        control.open()

        # Antes de revocar, la conexión funciona.
        self.assertEqual(
            control.poll(),
            [],
        )

        revoke_agent(agent)

        # La misma conexión ya autenticada debe quedar inválida.
        with self.assertRaises(AuthenticationFailed):
            control.poll()
            
class HandshakeTests(TransactionTestCase):
    @override_settings(CAPTURE_AGENTS=AGENTS)
    def test_incompatible_version_and_invalid_identity_have_no_domain_effect(self):
        async def exercise(header,version):
            received=asyncio.Queue();sent=[]
            await received.put({'type':'websocket.connect'})
            m=envelope('hello',dict(agent_version='1.0',capabilities=[]));m['protocol_version']=version
            await received.put({'type':'websocket.receive','text':json.dumps(m)})
            async def send(event):sent.append(event)
            await agent_websocket({'type':'websocket','path':'/ws/v1/agents','headers':[(b'authorization',header)],'query_string':b''},received.get,send)
            return sent
        bad=asyncio.run(exercise(b'Agent wrong','1.0'))
        self.assertEqual(bad[-1]['code'],4401)
        incompatible=asyncio.run(exercise(('Agent '+TOKEN).encode(),'9'))
        self.assertEqual(incompatible[-1]['code'],4406)
        self.assertEqual(CaptureSession.objects.count(),0)

class AudioSessionOffsetTests(IngestionFixtures, TestCase):
    def test_processor_keeps_wav_offsets_local_and_session_origin_separate(self):
        from .test_processing import FakeAnalysis
        from .processing import FragmentJobProcessor
        self.receive(content=wav_bytes(b'\0\0'*160000),temporal=AudioTimelineTests.timeline(self))
        self.receive(content=wav_bytes(b'\0\0'*160000),number=1,captured_at=NOW+timedelta(seconds=19),
                     now=NOW+timedelta(seconds=30),temporal=AudioTimelineTests.timeline(self,144000,304000,160000))
        analysis=FakeAnalysis()
        processor=FragmentJobProcessor(self.storage,analysis)
        processor.process_next();processor.process_next()
        fragment=analysis.calls[1][0]
        self.assertEqual((fragment.context_start,fragment.start,fragment.end),(0,0,160000))
        self.assertEqual((fragment.session_origin_sample,fragment.new_audio_start_sample),(144000,160000))
