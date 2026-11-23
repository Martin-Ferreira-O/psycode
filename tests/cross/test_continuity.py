"""Cinco agentes, dos sesiones por raíz, recepción tardía y respuesta perdida."""
import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from threading import Barrier, local
from unittest.mock import patch

import httpx
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings

from backend.apps.capture.models import CaptureSession, FragmentJob
from backend.apps.capture.services import CaptureSessionService
from backend.apps.capture.tests import NOW
from backend.apps.operational.capture_authorization import BoxCaptureAuthorization
from psycode_agent.audio_chunker import save_fragment
from psycode_agent.backend_client import BackendClient
from psycode_agent.command_journal import CommandJournal
from psycode_agent.config import AgentConfig
from psycode_agent.domain import Command
from psycode_agent.fragment_store import FragmentStore
from psycode_agent.upload_queue import UploadQueue


class FiveAgentContinuityTests(TransactionTestCase):
    def test_old_backlog_survives_restart_and_new_sessions_with_lost_http_receipts(self):
        with tempfile.TemporaryDirectory(prefix="psycode-five-") as temporary:
            root = Path(temporary)
            tokens = {f"box-{n}": f"five-{n}." + "s" * 43 for n in range(3, 8)}
            agents = {token.split(".")[0]: {"box": box, "token_sha256": hashlib.sha256(token.encode()).hexdigest()}
                      for box, token in tokens.items()}
            with override_settings(CAPTURE_AGENTS=agents, CAPTURE_FRAGMENT_ROOT=root / "central"), patch(
                "django.utils.timezone.now", return_value=NOW + timedelta(days=2, seconds=30)
            ):
                service = CaptureSessionService()
                pairs = []
                original_hashes = {}
                for box, token in tokens.items():
                    config = AgentConfig(box, 10, 1, autonomous=False,
                        backend_url="http://testserver", agent_token=token, agent_state_root=str(root / box),
                        max_retries=2, retry_backoff=0)
                    journal = CommandJournal(root / box, box)
                    session_ids = []
                    for index, start in enumerate((NOW, NOW + timedelta(days=2))):
                        session = service.apply_authorization(
                            BoxCaptureAuthorization(box, True, start, start + timedelta(hours=1), "agenda"), now=start)
                        central, = service.commands(box, now=start)
                        command = Command(**asdict(central))
                        journal.prepare(command)
                        journal.mark_executed(command, start)
                        service.acknowledge(box, command.command_id, occurred_at=start, now=start)
                        journal.mark_acknowledged(command)
                        folder = root / box / "fragments" / str(session.session_id)
                        for sequence in range(2 if index == 0 else 1):
                            offset = sequence * 9 * 16000
                            frames = (10 if sequence == 0 else 2) * 16000
                            temporal = dict(session_start_sample=offset, session_end_sample=offset + frames,
                                            new_audio_start_sample=sequence * 160000, sample_rate=16000,
                                            chunk_samples=160000, overlap_samples=16000)
                            save_fragment(folder, box, session.session_id, sequence,
                                bytes([sequence, 0]) * frames, start + timedelta(seconds=1 + sequence * 9), temporal)
                            path = folder / f"{sequence:06d}.wav"
                            original_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                        if index == 0:
                            # Desconexión supera ampliamente 120/300 s; captura ya cerrada,
                            # todos sus WAV siguen locales mientras se autoriza la sesión B.
                            service.confirm_capture_ended(box, session.session_id,
                                ended_at=start + timedelta(seconds=20), last_sequence=1,
                                reason_code="AUTHORIZATION_ENDED", now=start + timedelta(hours=2))
                            self.assertEqual(service.inspection(box, session.session_id,
                                now=start + timedelta(days=2))["reception"], "pending")
                        session_ids.append(session.session_id)
                    pairs.append((config, session_ids))

                barrier = Barrier(5)
                thread = local()
                application = get_wsgi_application()
                attempts = []

                def post(url, **kwargs):
                    path = kwargs["files"]["archivo"][1]
                    position = path.tell()
                    digest = hashlib.sha256(path.read()).hexdigest()
                    path.seek(position)
                    self.assertEqual(digest, original_hashes[str(path.name)])
                    with httpx.Client(transport=httpx.WSGITransport(app=application)) as client:
                        response = client.post(url, **kwargs)
                    attempts.append(response.status_code)
                    # El commit ocurrió, pero cada agente pierde su primera respuesta.
                    if not getattr(thread, "lost", False):
                        thread.lost = True
                        self.assertEqual(response.status_code, 201, response.text)
                        raise httpx.ReadTimeout("synthetic lost response")
                    return response

                def recover(pair):
                    config, sessions = pair
                    close_old_connections()
                    try:
                        barrier.wait(timeout=10)
                        # Nuevas instancias representan reapertura de cola/journal tras reinicio.
                        queue = UploadQueue(FragmentStore(Path(config.agent_state_root) / "fragments"), BackendClient(config))
                        self.assertEqual(queue.process_pending(), 3)
                        self.assertEqual(queue.store.pending(), [])
                    finally:
                        close_old_connections()

                with patch("psycode_agent.backend_client.httpx.post", side_effect=post):
                    with ThreadPoolExecutor(max_workers=5) as pool:
                        list(pool.map(recover, pairs))
                self.assertEqual(attempts.count(200), 5)
                self.assertEqual(attempts.count(201), 15)
                self.assertEqual(FragmentJob.objects.count(), 15)
                for _, (old, current) in pairs:
                    self.assertEqual(CaptureSession.objects.get(pk=old).state, "completada")
                    self.assertEqual(CaptureSession.objects.get(pk=current).state, "activa")
                    self.assertEqual(service.inspection(CaptureSession.objects.get(pk=old).box, old)["processing"], "pending")
