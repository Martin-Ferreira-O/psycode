import asyncio
from datetime import timedelta
import hashlib
import json
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from asgiref.sync import sync_to_async
from django.test import TransactionTestCase, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from backend.config import asgi

from .pc_registry import create_agent, revoke_agent
from .models import AudioTest, CaptureSession, FragmentJob, SessionState
from .test_ingestion import wav_bytes
from .upload_access import reserve_fragment_upload


class UploadAccessTests(TransactionTestCase):
    path = "/api/v2/internal/fragments"
    audio_test = False

    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(CAPTURE_FRAGMENT_ROOT=root, CAPTURE_V2_MAX_CONCURRENT_UPLOADS=5))
        self.agent, token = create_agent(name="PC de prueba", box="box-3")
        self.header = (b"authorization", f"Agent {token}".encode("ascii"))

    async def request(self, *headers, path=None):
        scope = {
            "type": "http", "method": "POST", "path": path or self.path,
            "client": ("127.0.0.1", 1234), "headers": list(headers),
        }
        receive = AsyncMock(side_effect=AssertionError("Body read before upload admission"))
        send = AsyncMock()
        await asgi.application(scope, receive, send)
        return scope, receive, send

    async def test_missing_credential_rejects_without_reading(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            _, receive, send = await self.request()
            receive.assert_not_awaited()
            django_app.assert_not_awaited()
            self.assertEqual(send.await_args_list[0].args[0]["status"], 401)
            self.assertEqual(json.loads(send.await_args.args[0]["body"])["error"]["code"], "AUTH_REQUIRED")
            django_app.assert_not_awaited()

    async def test_authorized_upload_is_forwarded_without_consuming_body(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            scope, receive, send = await self.request(self.header)
            django_app.assert_awaited_once_with(scope, receive, send)
            receive.assert_not_awaited()

    async def test_invalid_credential_rejects_without_reading(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            _, receive, send = await self.request((b"authorization", b"Agent synthetic-invalid"))
            receive.assert_not_awaited()
            django_app.assert_not_awaited()
            self.assertEqual(send.await_args_list[0].args[0]["status"], 401)
            self.assertEqual(json.loads(send.await_args.args[0]["body"])["error"]["code"], "AUTH_INVALID_TOKEN")

    async def test_duplicate_authorization_headers_reject_without_reading(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            _, receive, send = await self.request(self.header, self.header)
            receive.assert_not_awaited()
            django_app.assert_not_awaited()
            self.assertEqual(send.await_args_list[0].args[0]["status"], 401)

    async def test_revoked_agent_is_rejected_before_django_reads_upload(self):
        await sync_to_async(revoke_agent)(self.agent)
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            _, receive, send = await self.request(self.header)
            receive.assert_not_awaited()
            django_app.assert_not_awaited()
            self.assertEqual(send.await_args_list[0].args[0]["status"], 401)
            self.assertEqual(json.loads(send.await_args.args[0]["body"])["error"]["code"], "AUTH_INVALID_TOKEN")
            django_app.assert_not_awaited()

    async def test_same_box_retry_waits_without_reading_upload(self):
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            with reserve_fragment_upload(self.agent.box, audio_test=self.audio_test) as reserved:
                self.assertTrue(reserved)
                _, receive, send = await self.request(self.header)
                receive.assert_not_awaited()
                django_app.assert_not_awaited()
                response = send.await_args_list[0].args[0]
                self.assertEqual(response["status"], 503)
                self.assertIn((b"retry-after", b"5"), response["headers"])
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            await self.request(self.header)
            django_app.assert_awaited_once()

    async def test_five_boxes_with_same_ip_can_upload_at_once(self):
        headers = [self.header]
        for number in range(4, 8):
            _, token = await sync_to_async(create_agent)(name=f"PC {number}", box=f"box-{number}")
            headers.append((b"authorization", f"Agent {token}".encode("ascii")))
        all_entered = asyncio.Event()
        release = asyncio.Event()
        entered = []

        async def django_app(scope, receive, send):
            entered.append(scope["client"][0])
            if len(entered) == 5:
                all_entered.set()
            await release.wait()

        with patch.object(asgi, "http_application", django_app):
            async with asyncio.TaskGroup() as tasks:
                for header in headers:
                    tasks.create_task(self.request(header))
                try:
                    await asyncio.wait_for(all_entered.wait(), timeout=5)
                    self.assertEqual(entered, ["127.0.0.1"] * 5)
                    with reserve_fragment_upload("box-other", audio_test=self.audio_test) as reserved:
                        self.assertFalse(reserved)
                    with reserve_fragment_upload("box-other", audio_test=not self.audio_test) as reserved:
                        self.assertTrue(reserved)
                finally:
                    release.set()
        with reserve_fragment_upload("box-other", audio_test=self.audio_test) as reserved:
            self.assertTrue(reserved)

    async def test_interrupted_upload_releases_the_box_slot(self):
        interrupted = AsyncMock(side_effect=asyncio.CancelledError)
        with patch.object(asgi, "http_application", interrupted):
            with self.assertRaises(asyncio.CancelledError):
                await self.request(self.header)
        with patch.object(asgi, "http_application", new_callable=AsyncMock) as django_app:
            await self.request(self.header)
            django_app.assert_awaited_once()

    async def test_clinical_and_test_uploads_can_overlap_in_the_same_box(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def django_app(scope, receive, send):
            if scope["path"] == self.path:
                entered.set()
                await release.wait()
            else:
                await send({"type": "http.response.start", "status": 200, "headers": []})

        other = UploadAccessTests.path if self.audio_test else AudioTestUploadAccessTests.path
        with patch.object(asgi, "http_application", django_app):
            upload = asyncio.create_task(self.request(self.header))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                _, receive, send = await asyncio.wait_for(self.request(self.header, path=other), timeout=5)
                receive.assert_not_awaited()
                self.assertEqual(send.await_args_list[0].args[0]["status"], 200)
            finally:
                release.set()
                await upload


class AudioTestUploadAccessTests(UploadAccessTests):
    path = "/api/v2/internal/audio-tests/11111111-1111-4111-8111-111111111111/fragments"
    audio_test = True


class RealAudioUploadBoundaryTests(TransactionTestCase):
    """Real ASGI/Django/authentication and ingestion, without HTTP sockets."""

    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(CAPTURE_FRAGMENT_ROOT=root))
        self.agent, self.token = create_agent(name="PC sintético R1", box="box-3")
        now = timezone.now()
        self.clinical_session = CaptureSession.objects.create(
            box=self.agent.box, origin="agenda", state=SessionState.ACTIVE,
            scheduled_start=now, scheduled_end=now + timedelta(hours=1),
            authorized_at=now, actual_start=now, last_seen_at=now,
        )
        self.test_id = uuid4()
        self.url = f"/api/v2/internal/audio-tests/{self.test_id}"
        result = self.client.put(self.url, {"scenario": "neutral", "samples": 16000},
                                 content_type="application/json", HTTP_AUTHORIZATION=f"Agent {self.token}")
        self.assertEqual(result.status_code, 201, result.json())
        self.profile = result.json()["data"]

    def body(self, **changes):
        wav = wav_bytes(b"\x01\x00" * 16000)
        data = dict(archivo=SimpleUploadedFile("synthetic.wav", wav, "audio/wav"), box="box-3",
                    session_id=str(self.test_id), secuencia=0, formato="wav",
                    checksum=hashlib.sha256(wav).hexdigest(), captured_at=self.profile["started_at"],
                    session_start_sample=0, session_end_sample=16000, new_audio_start_sample=0,
                    sample_rate=16000, chunk_samples=160000, overlap_samples=16000)
        data.update(changes)
        return encode_multipart(BOUNDARY, data)

    async def request(self, *, token=None, body=None, path=None):
        body = self.body() if body is None else body
        headers = [(b"host", b"testserver"), (b"content-type", MULTIPART_CONTENT.encode()),
                   (b"content-length", str(len(body)).encode())]
        if token:
            headers.append((b"authorization", f"Agent {token}".encode()))
        scope = dict(type="http", asgi={"version": "3.0"}, http_version="1.1", method="POST",
                     scheme="https", path=path or self.url + "/fragments", root_path="",
                     query_string=b"", headers=headers, client=("127.0.0.1", 1234), server=("testserver", 443))
        delivered = False
        responses = []

        async def receive():
            nonlocal delivered
            if delivered:
                await asyncio.Event().wait()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        receiver = AsyncMock(side_effect=receive)
        async def send(message):
            responses.append(message)
        started = timezone.datetime.fromisoformat(self.profile["started_at"])
        with patch("django.utils.timezone.now", return_value=started + timedelta(seconds=2)):
            await asgi.application(scope, receiver, send)
        status = next(m["status"] for m in responses if m["type"] == "http.response.start")
        payload = b"".join(m.get("body", b"") for m in responses if m["type"] == "http.response.body")
        return status, json.loads(payload), receiver

    async def test_real_django_rejects_credentials_without_receiving_any_body(self):
        for token in (None, "synthetic-invalid"):
            with self.subTest(credential="missing" if token is None else "invalid"):
                status, _, receiver = await self.request(token=token)
                self.assertEqual(status, 401)
                receiver.assert_not_awaited()
        await sync_to_async(revoke_agent)(self.agent)
        status, _, receiver = await self.request(token=self.token)
        self.assertEqual(status, 401)
        receiver.assert_not_awaited()

    async def test_audio_test_is_accepted_during_a_clinical_upload(self):
        with reserve_fragment_upload(self.agent.box) as reserved:
            self.assertTrue(reserved)
            status, payload, _ = await self.request(token=self.token)

        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["data"]["session_id"], str(self.test_id))
        await sync_to_async(self.clinical_session.refresh_from_db)()
        self.assertEqual(self.clinical_session.state, SessionState.ACTIVE)
        self.assertEqual(self.clinical_session.next_sequence, 0)

    async def test_authorized_real_asgi_upload_is_idempotent(self):
        first, one, receiver = await self.request(token=self.token)
        self.assertEqual(first, 201, one)
        self.assertGreater(receiver.await_count, 0)
        second, two, _ = await self.request(token=self.token)
        self.assertEqual(second, 200, two)
        self.assertEqual(one["data"], two["data"])
        self.assertEqual(await sync_to_async(FragmentJob.objects.count)(), 1)

    async def test_other_pc_cannot_upload_to_the_test(self):
        _, token = await sync_to_async(create_agent)(name="Otro PC sintético", box="box-4")
        status, payload, _ = await self.request(token=token)
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "AUDIO_TEST_NOT_FOUND")
        self.assertEqual(await sync_to_async(FragmentJob.objects.count)(), 0)

    async def test_invalid_sequence_timeline_and_checksum_remain_rejected(self):
        for changes, expected in (({"secuencia": 1}, 409), ({"session_end_sample": 8000}, 422),
                                  ({"checksum": "0" * 64}, 422)):
            with self.subTest(fields=tuple(changes)):
                status, payload, _ = await self.request(token=self.token, body=self.body(**changes))
                self.assertEqual(status, expected, payload)
        self.assertEqual(await sync_to_async(FragmentJob.objects.count)(), 0)

    async def test_expired_test_and_clinical_endpoint_do_not_accept_test_audio(self):
        await sync_to_async(AudioTest.objects.filter(pk=self.test_id).update)(
            expires_at=timezone.datetime.fromisoformat(self.profile["started_at"]))
        status, payload, _ = await self.request(token=self.token)
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "AUDIO_TEST_EXPIRED")
        status, payload, _ = await self.request(token=self.token, path=UploadAccessTests.path)
        self.assertEqual(status, 404, payload)
        self.assertEqual(await sync_to_async(FragmentJob.objects.count)(), 0)
