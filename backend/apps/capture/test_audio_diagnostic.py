from datetime import timedelta
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
import httpx
from rest_framework.test import APIClient

from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.tests.test_integration import answer
from backend.config.composition import fragment_job_processor
from .models import AgentCommand, AgentRegistration, FragmentJob
from .test_ingestion import wav_bytes


class AudioDiagnosticTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        config = override_settings(CAPTURE_FRAGMENT_ROOT=self.root / "audio")
        config.enable()
        self.addCleanup(config.disable)
        self.agent = self.new_agent(self.client)

    def new_agent(self, client):
        agent = uuid4()
        token = f"{agent}." + "a" * 43
        AgentRegistration.objects.create(pk=agent, box="box-3", name="PC sintético",
                                         token_sha256=hashlib.sha256(token.encode()).hexdigest())
        client.defaults["HTTP_AUTHORIZATION"] = "Agent " + token
        return agent

    def start(self, scenario, samples=16000):
        ident = str(uuid4())
        url = f"/api/v1/internal/audio-tests/{ident}"
        payload = {"scenario": scenario, "samples": samples}
        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.json())
        data = response.json()["data"]
        self.assertEqual(self.client.put(url, payload, content_type="application/json").json()["data"], data)
        return url, data

    def upload(self, url, data, *, seq=0, offset=0, end=16000, new=0, **changes):
        wav = wav_bytes(b"\x01\x00" * (end - offset))
        started = timezone.datetime.fromisoformat(data["started_at"])
        payload = dict(
            archivo=SimpleUploadedFile("clip-ficticio.wav", wav, "audio/wav"),
            box="box-3", session_id=data["test_id"], secuencia=seq, formato="wav",
            checksum=hashlib.sha256(wav).hexdigest(),
            captured_at=(started + timedelta(seconds=offset / 16000)).isoformat(),
            session_start_sample=offset, session_end_sample=end, new_audio_start_sample=new,
            sample_rate=16000, chunk_samples=160000, overlap_samples=16000,
        )
        payload.update(changes)
        now = max(timezone.now(), started + timedelta(seconds=end / 16000))
        with patch("django.utils.timezone.now", return_value=now):
            return self.client.post(url, payload)

    def test_authorization_is_scoped_to_test_and_to_the_same_pc(self):
        url, data = self.start("neutral")
        other = APIClient()
        self.new_agent(other)
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(other.post(url + "/fragments").status_code, 404)
        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertEqual(self.upload("/api/v2/internal/fragments", data).status_code, 404)
        self.assertEqual(self.upload(url + "/fragments", data, seq=1).status_code, 409)
        self.assertEqual(self.upload(url + "/fragments", data, end=8000).status_code, 422)
        clinical = self.client.get("/api/v1/internal/sessions/" + data["test_id"])
        self.assertEqual(clinical.json()["error"]["code"], "SESSION_NOT_FOUND")
        self.assertFalse(AgentCommand.objects.exists())
        self.assertFalse(FragmentJob.objects.exists())

    def test_clip_goes_through_transcription_classifier_and_test_alerts(self):
        settings = Settings(speechmatics_key="test-speech-key", jev_key="test-jev-key", external_enabled=True)
        sent_to_jev, provider_calls = [], []
        text = ""
        signal = None

        def speech(request):
            provider_calls.append(request.method)
            if request.method == "POST":
                return httpx.Response(201, json={"id": "synthetic-job"})
            if request.method == "DELETE":
                return httpx.Response(200)
            if request.url.path.endswith("/transcript"):
                return httpx.Response(200, json={"results": [{
                    "type": "word", "start_time": 0, "end_time": 0.8,
                    "alternatives": [{"content": text, "speaker": "S1"}],
                }]})
            return httpx.Response(200, json={"job": {"status": "done"}})

        def jev(request):
            sent_to_jev.append(request.content)
            return httpx.Response(200, json=answer(signal))

        with (httpx.Client(transport=httpx.MockTransport(speech)) as speech_client,
              httpx.Client(transport=httpx.MockTransport(jev)) as jev_client):
            processor = fragment_job_processor(settings=settings, directory=self.root,
                                               speechmatics_http=speech_client, jev_http=jev_client,
                                               alert_store=Mock(), audit=Mock())
            processor.analysis.alerts = Mock()
            for scenario, text, signal, expected in [
                ("neutral", "Me gusta tomar café por la mañana", None, 0),
                ("alerta", "Ojalá no despertar", 1, 1),
            ]:
                with self.subTest(scenario=scenario):
                    url, data = self.start(scenario)
                    self.assertEqual(data["state"], "receiving")
                    first = self.upload(url + "/fragments", data)
                    self.assertEqual(first.status_code, 201, first.json())
                    retry = self.upload(url + "/fragments", data)
                    self.assertEqual(retry.status_code, 200, retry.json())
                    self.assertEqual(first.json()["data"], retry.json()["data"])
                    self.assertEqual(self.client.get(url).json()["data"]["state"], "analyzing")
                    self.assertEqual(processor.process_next(), FragmentJob.State.COMPLETED)
                    finished = self.client.get(url).json()["data"]
                    self.assertEqual(finished["state"], "completed")
                    self.assertEqual(finished["accepted"], 1)
                    self.assertEqual(finished["analyzed"], 1)
                    self.assertEqual(finished["indeterminate"], 0)
                    self.assertEqual(len(finished["alerts"]), expected)
                    self.assertNotIn(text, str(finished))
            processor.analysis.alerts.register_alert.assert_not_called()
        self.assertEqual(provider_calls, ["POST", "GET", "GET", "DELETE"] * 2)
        self.assertEqual(len(sent_to_jev), 2)

    def test_ten_minute_test_can_stop_and_restart_at_another_position(self):
        url, data = self.start("alerta", samples=16000 * 600)
        self.assertEqual(data["expected"], 67)
        started = timezone.datetime.fromisoformat(data["started_at"])
        other = APIClient()
        self.new_agent(other)
        self.assertEqual(other.delete(url).status_code, 404)
        with patch("django.utils.timezone.now", return_value=started + timedelta(minutes=6)):
            first = self.upload(url + "/fragments", data, end=160000)
            self.assertEqual(first.status_code, 201, first.json())
            stopped = self.client.delete(url).json()["data"]
            self.assertEqual((stopped["state"], stopped["accepted"]), ("stopped", 1))
            self.assertEqual(self.client.delete(url).json()["data"], stopped)
            self.assertEqual(self.upload(url + "/fragments", data, end=160000).status_code, 200)
            late = self.upload(url + "/fragments", data, seq=1, offset=144000, end=304000, new=160000)
            self.assertEqual(late.json()["error"]["code"], "AUDIO_TEST_EXPIRED")
            _, resumed = self.start("alerta", samples=16000 * 120)
            self.assertNotEqual(resumed["test_id"], data["test_id"])
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertFalse(AgentCommand.objects.exists())
