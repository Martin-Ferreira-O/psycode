import hashlib
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError
from django.test import TestCase, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from rest_framework.test import APIClient

from .models import AcceptedSequence, CaptureEvent, CaptureSession, FragmentJob
from .test_ingestion import IngestionFixtures, wav_bytes
from .tests import NOW
from .uploads import FragmentUploadHandler

TOKEN = "agent-3." + "s" * 43
AGENTS = {"agent-3": {"box": "box-3", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}}
URL = "/api/v2/internal/fragments"


class FragmentAPITests(IngestionFixtures, TestCase):
    def setUp(self):
        super().setUp()
        config = override_settings(CAPTURE_FRAGMENT_ROOT=self.root, CAPTURE_AGENTS=AGENTS)
        config.enable()
        self.addCleanup(config.disable)
        clock = patch("django.utils.timezone.now", return_value=NOW + timedelta(seconds=20))
        clock.start()
        self.addCleanup(clock.stop)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Agent " + TOKEN)

    def payload(self, content=None, **changes):
        content = wav_bytes() if content is None else content
        result = dict(archivo=SimpleUploadedFile("PRIVATE-CLINICAL-FILENAME.wav", content, "audio/wav"),
                      box="box-3", session_id=str(self.session.session_id), secuencia="0", formato="wav",
                      checksum=hashlib.sha256(content).hexdigest(),
                      captured_at=(NOW + timedelta(seconds=10)).isoformat(),
                      session_start_sample=0, session_end_sample=max(1, (len(content) - 44) // 2),
                      new_audio_start_sample=0, sample_rate=16000, chunk_samples=160000, overlap_samples=16000)
        result.update(changes)
        return result

    def post(self, content=None, **changes):
        return self.client.post(URL, self.payload(content, **changes), format="multipart")

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.data)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], code)
        self.assertEqual(response.data["error"]["details"], {})
        self.assertNotIn("PRIVATE", str(response.data))
        self.assertFalse(list(self.root.glob("*.part")))

    def test_receives_multipart_then_confirms_existing_receipt(self):
        first = self.post()
        self.assertEqual(first.status_code, 201, first.data)
        job = FragmentJob.objects.get()
        self.assertEqual(job.state, "pendiente")
        self.assertEqual(first.data["data"]["job_id"], str(job.pk))
        self.assertEqual(first.data["data"]["estado"], "aceptado")
        self.assertNotIn("storage_key", first.data["data"])
        second = self.post()
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["data"], second.data["data"])
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(len(self.blobs()), 1)
        self.assertFalse(list(self.root.glob("*.part")))

    def test_authenticates_before_parsing_or_writing_audio(self):
        for authorization in (None, "Bearer professional.jwt.token", "Agent unknown." + "s" * 43,
                              "Agent agent-3." + "x" * 43, "Agent invalid", "Agent " + TOKEN + " extra"):
            with self.subTest(authorization=bool(authorization)):
                self.client.credentials(**({"HTTP_AUTHORIZATION": authorization} if authorization else {}))
                with patch("backend.apps.capture.uploads.FragmentMultiPartParser.parse") as parse:
                    response = self.post()
                self.assert_error(response, 401, "AUTH_REQUIRED" if authorization is None else "AUTH_INVALID_TOKEN")
                self.assertEqual(response["WWW-Authenticate"], "Agent")
                parse.assert_not_called()
        self.assertFalse(FragmentJob.objects.exists())

    @override_settings(CAPTURE_AGENTS={})
    def test_no_configured_agents_denies_every_request(self):
        self.assert_error(self.post(), 401, "AUTH_INVALID_TOKEN")

    def test_revoking_credential_applies_to_next_request(self):
        self.assertEqual(self.post().status_code, 201)
        with override_settings(CAPTURE_AGENTS={}):
            self.assert_error(self.post(), 401, "AUTH_INVALID_TOKEN")

    def test_agent_can_only_upload_for_its_bound_box_and_session(self):
        self.assert_error(self.post(box="box-4"), 403, "AUTH_FORBIDDEN")
        CaptureSession.objects.filter(pk=self.session.session_id).update(box="box-4")
        self.assert_error(self.post(), 404, "SESSION_NOT_FOUND")
        self.assert_error(self.post(session_id=str(uuid4())), 404, "SESSION_NOT_FOUND")
        self.assertFalse(FragmentJob.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_session_must_be_active_or_finalizing_and_capture_time_in_window(self):
        for state in ("iniciada", "completada", "fallida"):
            CaptureSession.objects.filter(pk=self.session.session_id).update(state=state)
            self.assert_error(self.post(), 409, "SESSION_NOT_ACCEPTING_SEQUENCES")
        CaptureSession.objects.filter(pk=self.session.session_id).update(state="activa")
        self.assert_error(self.post(captured_at=(NOW - timedelta(seconds=1)).isoformat()),
                          409, "SEQUENCE_OUTSIDE_CAPTURE_WINDOW")

    def test_finalizing_accepts_last_fragment_but_rejects_sequences_beyond_declared_final(self):
        self.ack_stop(self.stop(), last_sequence=0)
        first = wav_bytes(b"\0\0" * 160000)
        extra = wav_bytes(b"\0\0" * 32000)
        with patch("django.utils.timezone.now", return_value=NOW + timedelta(seconds=36)):
            self.assertEqual(self.post(content=first).status_code, 201)
            response = self.post(content=extra, secuencia="1", session_start_sample=144000,
                                 session_end_sample=176000, new_audio_start_sample=160000,
                                 captured_at=(NOW + timedelta(seconds=19)).isoformat())
            self.assert_error(response, 409, "SESSION_NOT_ACCEPTING_SEQUENCES")
            self.assertEqual(self.post(content=first).status_code, 200)
        self.assertEqual(FragmentJob.objects.count(), 1)

    def test_conflict_preserves_original_job_and_audio(self):
        self.post()
        original = FragmentJob.objects.get()
        self.assert_error(self.post(content=wav_bytes(b"\x01\x00" * 160)), 409, "SEQUENCE_CONFLICT")
        self.assertEqual(FragmentJob.objects.get().pk, original.pk)
        self.assertEqual(self.blobs()[0].read_bytes(), wav_bytes())

    def test_validates_files_with_safe_errors(self):
        cases = [(dict(content=b""), 422, "EMPTY_FRAGMENT"),
                 (dict(content=b"PRIVATE audio bytes"), 422, "INVALID_FRAGMENT_FILE"),
                 (dict(content=wav_bytes()[:-2]), 422, "INVALID_FRAGMENT_FILE"),
                 (dict(checksum="0" * 64), 422, "CHECKSUM_MISMATCH"),
                 (dict(formato="mp3"), 415, "FRAGMENT_FORMAT_UNSUPPORTED")]
        for changes, status, code in cases:
            with self.subTest(code=code):
                self.assert_error(self.post(**changes), status, code)
        self.assertEqual(self.blobs(), [])

    @override_settings(CAPTURE_FRAGMENT_MAX_BYTES=100)
    def test_checks_streamed_size_even_when_multipart_body_fits_overhead_allowance(self):
        self.assert_error(self.post(), 413, "FRAGMENT_TOO_LARGE")
        self.assertFalse(FragmentJob.objects.exists())

    def test_inclusive_maximum_and_file_name_or_mime_do_not_determine_format(self):
        content = wav_bytes()
        with override_settings(CAPTURE_FRAGMENT_MAX_BYTES=len(content)):
            response = self.post(archivo=SimpleUploadedFile("PRIVATE.txt", content, "text/plain"))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["size_bytes"], len(content))

    @override_settings(CAPTURE_FRAGMENT_MAX_BYTES=100)
    def test_rejects_total_request_size_before_creating_an_incoming_file(self):
        with patch("backend.apps.capture.storage.FragmentStorage.incoming") as incoming:
            response = self.post(content=b"a" * (66 * 1024))
        self.assert_error(response, 413, "FRAGMENT_TOO_LARGE")
        incoming.assert_not_called()

    def test_metadata_fields_are_required_strict_unique_and_never_echoed(self):
        for field in self.payload():
            data = self.payload()
            del data[field]
            self.assert_error(self.client.post(URL, data, format="multipart"), 400, "VALIDATION_ERROR")
        for changes in (dict(checksum="PRIVATE"), dict(secuencia="-1"), dict(secuencia="1.0"),
                        dict(secuencia="9223372036854775807"), dict(box="box-0"),
                        dict(session_id="PRIVATE"), dict(captured_at="2026-10-19T12:00:10"),
                        dict(captured_at="PRIVATE"), dict(checksum="A" * 64),
                        dict(checksum=" " + "a" * 64), dict(secuencia="0\n"), dict(secuencia=" 0"),
                        dict(PRIVATE_field="PRIVATE"), dict(secuencia=["0", "0"])):
            with self.subTest(keys=tuple(changes)):
                self.assert_error(self.post(**changes), 400, "VALIDATION_ERROR")
        self.assertEqual(self.blobs(), [])

    def test_rejects_multiple_files_and_cleans_the_first(self):
        files = [SimpleUploadedFile("PRIVATE-1.wav", wav_bytes()), SimpleUploadedFile("PRIVATE-2.wav", wav_bytes())]
        self.assert_error(self.post(archivo=files), 400, "VALIDATION_ERROR")
        self.assertFalse(FragmentJob.objects.exists())

    def test_unsupported_media_type_and_malformed_multipart_are_safe(self):
        self.assert_error(self.client.post(URL, {"PRIVATE": "PRIVATE"}, format="json"),
                          415, "UNSUPPORTED_MEDIA_TYPE")
        self.assert_error(self.client.generic("POST", URL, b"PRIVATE", content_type="multipart/form-data"),
                          400, "VALIDATION_ERROR")

    def test_incomplete_multipart_does_not_create_job_and_removes_upload(self):
        body = encode_multipart(BOUNDARY, self.payload())
        body = body[:body.index(b"\r\n--" + BOUNDARY.encode(), body.index(b"RIFF"))]
        self.assert_error(self.client.generic("POST", URL, body, content_type=MULTIPART_CONTENT),
                          400, "VALIDATION_ERROR")
        self.assertFalse(FragmentJob.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_missing_closing_boundary_rejects_even_when_file_and_metadata_are_complete(self):
        body = encode_multipart(BOUNDARY, self.payload())
        body = body[:body.rindex(b"--" + BOUNDARY.encode() + b"--")]
        self.assert_error(self.client.generic("POST", URL, body, content_type=MULTIPART_CONTENT),
                          400, "VALIDATION_ERROR")
        self.assertFalse(FragmentJob.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_persistence_or_storage_failure_does_not_confirm_and_never_exposes_payload(self):
        for failure in (OperationalError("PRIVATE database"), IntegrityError("PRIVATE database")):
            with patch("backend.apps.capture.ingestion.FragmentJob.objects.create", side_effect=failure):
                with patch("backend.common.audit.AuditWriter.emit") as emit:
                    response = self.post()
            self.assert_error(response, 503 if isinstance(failure, OperationalError) else 500,
                              "PERSISTENCE_UNAVAILABLE" if isinstance(failure, OperationalError) else "INTERNAL_ERROR")
            self.assertNotIn("PRIVATE", str(emit.call_args_list))
        with patch("backend.apps.capture.storage.FragmentStorage.incoming", side_effect=OSError("PRIVATE disk")):
            self.assert_error(self.post(), 503, "FRAGMENT_STORAGE_UNAVAILABLE")
        self.assertFalse(AcceptedSequence.objects.exists())
        self.assertFalse(FragmentJob.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_audit_contains_only_technical_fields(self):
        with patch("backend.common.audit.AuditWriter.emit") as emit:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.post().status_code, 201)
        events = [call.args[0] for call in emit.call_args_list]
        self.assertEqual(len(events), 2)
        self.assertNotIn("PRIVATE", str(events))
        self.assertNotIn(TOKEN, str(events))
        self.assertNotIn("checksum", str(events))
        self.assertNotIn("storage_key", str(events))
        self.assertEqual(CaptureEvent.objects.filter(action="capture.fragment.queued").count(), 1)

    def test_route_has_no_trailing_slash_and_accepts_only_post(self):
        self.assert_error(self.client.get(URL), 405, "METHOD_NOT_ALLOWED")
        self.assertIn("POST", self.client.get(URL)["Allow"])
        self.assertEqual(self.client.post(URL + "/", {}, format="multipart").status_code, 404)

    def test_old_internal_routes_and_fragment_aliases_return_404(self):
        for path in (
            "/api/v1/internal/fragments", "/api/v1/internal/fragments/v2", URL + "/v2",
            f"/api/v1/internal/audio-tests/{uuid4()}/fragments",
            f"/api/v1/internal/audio-tests/{uuid4()}", "/api/v1/internal/pcs/vincular",
            "/api/v1/internal/agent-updates/windows-x64", "/api/v1/internal/smile-configuration",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 404)


class InterruptedUploadHandlerTests(IngestionFixtures, TestCase):
    def test_interrupted_upload_removes_private_file(self):
        handler = FragmentUploadHandler(None, self.storage)
        handler.new_file("archivo", "PRIVATE.wav", "audio/wav", None)
        handler.receive_data_chunk(b"partial", 0)
        self.assertEqual(len(list(self.root.glob("*.part"))), 1)
        handler.upload_interrupted()
        self.assertFalse(list(self.root.glob("*.part")))

    def test_size_limit_uses_actual_bytes_not_declared_file_size(self):
        self.storage.max_bytes = 10
        handler = FragmentUploadHandler(None, self.storage)
        handler.new_file("archivo", "PRIVATE.wav", "audio/wav", 1)
        try:
            from .storage import FragmentError
            with self.assertRaises(FragmentError) as caught:
                handler.receive_data_chunk(b"a" * 11, 0)
            self.assertEqual(caught.exception.status, 413)
        finally:
            handler.close()
