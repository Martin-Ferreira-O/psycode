
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
from psycode_agent.upload_queue import UploadQueue

import httpx

from django.core.wsgi import get_wsgi_application
from django.test import TransactionTestCase, override_settings

from backend.apps.capture.models import (
    AcceptedSequence,
    FragmentJob,
    CaptureSession,
)
from backend.apps.capture.test_api import AGENTS, TOKEN
from backend.apps.capture.test_ingestion import IngestionFixtures
from backend.apps.capture.tests import NOW

from psycode_agent.audio_chunker import save_fragment
from psycode_agent.backend_client import BackendClient
from psycode_agent.config import AgentConfig
from psycode_agent.fragment_store import FragmentStore
from psycode_agent.command_journal import CommandJournal
from psycode_agent.domain import Command


class AgentHTTPIntegrationTests(IngestionFixtures, TransactionTestCase):
    """Integración real del agente con la API Django."""

    def active(self):
        # Registrar el ciclo real de inicio: la cola autónoma exige un ACK local
        # durable además de una sesión activa en el servidor.
        session = self.create()
        central, = self.service.commands('box-3', now=NOW)
        command = Command(**asdict(central))
        self.journal = CommandJournal(self.root / 'agent-state', 'box-3')
        self.journal.prepare(command)
        self.journal.mark_executed(command, NOW)
        self.service.acknowledge('box-3', command.command_id, occurred_at=NOW, now=NOW)
        self.journal.mark_acknowledged(command)
        return session

    def setUp(self):
        super().setUp()

        settings_context = override_settings(
            CAPTURE_FRAGMENT_ROOT=self.root,
            CAPTURE_AGENTS=AGENTS,
        )
        settings_context.enable()
        self.addCleanup(settings_context.disable)

        clock = patch(
            "django.utils.timezone.now",
            return_value=NOW + timedelta(seconds=20),
        )
        clock.start()
        self.addCleanup(clock.stop)

        config = AgentConfig(
            box_id="box-3",
            chunk_duration=10,
            chunk_overlap=1,
            backend_url="http://testserver",
            agent_token=TOKEN,
            http_timeout=15,
            max_retries=2,
            retry_backoff=0,
            agent_state_root=str(self.root / 'agent-state'),
        )

        self.backend_client = BackendClient(config)

        self.fragments_root = (
            self.root / "agent-fragments"
        )

        self.folder = (
            self.fragments_root
            / str(self.session.session_id)
        )

        audio = b"\x00\x00" * (16000 * 10)

        self.metadata = save_fragment(
            folder=self.folder,
            box="box-3",
            session_id=self.session.session_id,
            sequence=0,
            audio=audio,
            captured_at=NOW + timedelta(seconds=10),
            temporal=dict(session_start_sample=0, session_end_sample=160000, new_audio_start_sample=0,
                          sample_rate=16000, chunk_samples=160000, overlap_samples=16000),
        )

        self.wav_path = self.folder / "000000.wav"
        self.json_path = self.folder / "000000.json"

    def test_backend_client_contra_api_django(self):
        """Verifica HTTP 201, 200 e idempotencia."""

        statuses = []

        application = get_wsgi_application()

        transport = httpx.WSGITransport(
            app=application,
        )

        with httpx.Client(
            transport=transport,
            base_url="http://testserver",
        ) as local_client:

            def post_local(url, **kwargs):
                response = local_client.post(
                    url,
                    **kwargs,
                )

                statuses.append(
                    response.status_code
                )

                return response

            with patch(
                "psycode_agent.backend_client.httpx.post",
                side_effect=post_local,
            ):
                first = self.backend_client.upload_fragment(
                    file_path=self.wav_path,
                    session_id=self.metadata["session_id"],
                    sequence=self.metadata["sequence"],
                    captured_at=self.metadata["captured_at"],
                    checksum=self.metadata["checksum_sha256"],
                    temporal=self.metadata["temporal"],
                )

                second = self.backend_client.upload_fragment(
                    file_path=self.wav_path,
                    session_id=self.metadata["session_id"],
                    sequence=self.metadata["sequence"],
                    captured_at=self.metadata["captured_at"],
                    checksum=self.metadata["checksum_sha256"],
                    temporal=self.metadata["temporal"],
                )

        self.assertEqual(statuses, [201, 200])

        self.assertEqual(first, second)
        self.assertEqual(first["estado"], "aceptado")

        self.assertEqual(
            FragmentJob.objects.count(),
            1,
        )
        self.assertEqual(
            AcceptedSequence.objects.count(),
            1,
        )

        store = FragmentStore(
            self.fragments_root
        )

        store.mark_accepted(
            self.json_path,
            second,
        )

        self.assertFalse(self.wav_path.exists())

        metadata = json.loads(
            self.json_path.read_text(encoding="utf-8")
        )

        self.assertEqual(
            metadata["status"],
            "accepted",
        )

        self.assertEqual(store.pending(), [])

    def test_primer_fragmento_conserva_precision_del_inicio(self):
        started_at = NOW + timedelta(seconds=1, microseconds=123456)
        CaptureSession.objects.filter(pk=self.session.session_id).update(
            actual_start=started_at,
        )
        # Fixture independiente: un WAV publicado nunca se sobrescribe para
        # representar otra captura o fecha.
        precision_folder = self.root / "precision" / str(self.session.session_id)
        metadata = save_fragment(
            folder=precision_folder,
            box="box-3",
            session_id=self.session.session_id,
            sequence=0,
            audio=b"\x00\x00" * 16000,
            captured_at=started_at,
        )

        result, created = self.receive(
            content=(precision_folder / "000000.wav").read_bytes(),
            checksum=metadata["checksum_sha256"],
            captured_at=datetime.fromisoformat(metadata["captured_at"]),
        )

        self.assertTrue(created)
        self.assertEqual(result.sequence, 0)



    def test_upload_queue_contra_api_django(self):
        """La cola envía y confirma el WAV mediante la API real."""

        store = FragmentStore(self.fragments_root)
        queue = UploadQueue(store, self.backend_client)

        statuses = []

        transport = httpx.WSGITransport(
            app=get_wsgi_application()
        )

        with httpx.Client(
            transport=transport,
            base_url="http://testserver",
        ) as local_client:

            def post_local(url, **kwargs):
                response = local_client.post(url, **kwargs)
                statuses.append(response.status_code)
                return response

            with patch(
                "psycode_agent.backend_client.httpx.post",
                side_effect=post_local,
            ):
                uploaded = queue.process_pending()

                uploaded_again = queue.process_pending()

        self.assertEqual(uploaded, 1)
        self.assertEqual(uploaded_again, 0)

        self.assertEqual(statuses, [201])

        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(AcceptedSequence.objects.count(), 1)

        self.assertFalse(self.wav_path.exists())
        self.assertEqual(store.pending(), [])

        metadata = json.loads(
            self.json_path.read_text(encoding="utf-8")
        )

        self.assertEqual(metadata["status"], "accepted")
        self.assertEqual(metadata["attempts"], 1)
