"""El reproductor del agente respeta el perfil operativo usando multipart real."""
import hashlib
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import httpx
from django.test import TestCase, override_settings

from backend.apps.capture.models import AgentRegistration, AudioTest, FragmentJob
from backend.apps.capture.tests import NOW
from backend.apps.operational.models import OperationalConfiguration
from psycode_agent import audio_test
from psycode_agent.config import AgentConfig


class AudioTestProfileIntegrationTests(TestCase):
    def exercise(self, duration, expected):
        config = OperationalConfiguration.load()
        config.audio_chunk_duration = duration
        config.save()
        agent_id = uuid4()
        token = f"{agent_id}." + "a" * 43
        AgentRegistration.objects.create(pk=agent_id, box="box-3", name="PC sintético",
                                         token_sha256=hashlib.sha256(token.encode()).hexdigest())
        elapsed, posts, reports = [0.0], [], []
        def server(request):
            if request.method == "GET":
                # Solo simula el análisis; recepción y fragmentación son reales.
                FragmentJob.objects.update(state=FragmentJob.State.COMPLETED, result=FragmentJob.Result.NO_RISK_DETECTED)
            response = self.client.generic(
                request.method, request.url.raw_path.decode(), data=request.content,
                content_type=request.headers.get("Content-Type", "application/json"),
                HTTP_AUTHORIZATION=request.headers["Authorization"],
            )
            result = httpx.Response(response.status_code, content=response.content,
                                    headers={"Content-Type": "application/json"})
            if request.method == "POST":
                self.assertIn(response.status_code, (200, 201), response.content)
                posts.append((elapsed[0], hashlib.sha256(request.content).hexdigest()))
                if len(posts) == 1:
                    raise httpx.ReadTimeout("Respuesta perdida tras commit", request=request)
            return result
        agent = AgentConfig("box-3", "", 4455, "", "", 10, 1,
                            backend_url="https://testserver", agent_token=token, retry_backoff=0)
        with (TemporaryDirectory() as root,
              override_settings(CAPTURE_FRAGMENT_ROOT=Path(root)),
              patch("django.utils.timezone.now", side_effect=lambda: NOW + timedelta(seconds=elapsed[0])),
              patch("psycode_agent.audio_test.monotonic", side_effect=lambda: elapsed[0]),
              patch("psycode_agent.audio_test.sleep", side_effect=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)),
              httpx.Client(transport=httpx.MockTransport(server), headers={"Authorization": "Agent " + token}) as client):
            final = audio_test.stream_test(agent, bytes(600 * 32000), "neutral", reports.append, client)
            self.assertEqual(FragmentJob.objects.count(), expected)
            run = AudioTest.objects.select_related("session").get()
            self.assertEqual(run.session.audio_profile["chunk_samples"], duration * 16000)
            self.assertEqual(run.session.final_sequence, expected - 1)
            self.assertEqual(posts[0][0], duration)
            # Multipart boundaries may change; durable job identity remains one per sequence.
            self.assertEqual(len(posts), expected + 1)
            self.assertIn(f"Duración configurada de fragmentos: {duration} s", final)
            self.assertIn("Prueba completada", final)
            self.assertIn("Resultados por fragmento", final)
            self.assertEqual(final.count("Sin señal detectada"), expected)

    def test_configured_ten_minutes_is_one_wav_and_lost_receipt_does_not_duplicate(self):
        self.exercise(600, 1)

    def test_default_sixty_seconds_is_used_instead_of_legacy_ten_seconds(self):
        self.exercise(60, 10)
