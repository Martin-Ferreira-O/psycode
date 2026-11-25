import hashlib
import os
import struct
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import TestCase, TransactionTestCase

from .domain import CaptureError
from .ingestion import FragmentIngestionService
from .models import AcceptedSequence, CaptureEvent, CaptureSession, FragmentJob
from .storage import FragmentError, FragmentStorage
from . import tests as lifecycle_tests
from .tests import CaptureFixtures, NOW


def wav_bytes(samples=b"\x00\x00" * 160):
    fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


class IngestionFixtures(CaptureFixtures):
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = FragmentStorage(self.root, 25 * 1024 * 1024)
        self.ingestion = FragmentIngestionService(self.storage)
        self.session = self.active()

    def receive(self, *, content=None, **changes):
        content = wav_bytes() if content is None else content
        args = dict(box="box-3", session_id=self.session.session_id, number=0,
                    format="wav", checksum=hashlib.sha256(content).hexdigest(),
                    captured_at=NOW + timedelta(seconds=10),
                    upload=SimpleUploadedFile("sensitive-client-name.wav", content),
                    now=NOW + timedelta(seconds=20))
        args.update(changes)
        return self.ingestion.receive(**args)

    def blobs(self):
        return list(self.root.glob("*.blob"))


class FragmentIngestionTests(IngestionFixtures, TestCase):
    def test_new_fragment_saves_private_file_pending_job_sequence_and_events(self):
        result, created = self.receive()
        self.assertTrue(created)
        job = FragmentJob.objects.get()
        self.assertEqual(result.job_id, job.pk)
        self.assertEqual(job.state, "pendiente")
        self.assertEqual(job.sequence.number, 0)
        self.assertEqual(CaptureSession.objects.get().next_sequence, 1)
        self.assertEqual(self.blobs()[0].read_bytes(), wav_bytes())
        if os.name != "nt":
            self.assertEqual(self.blobs()[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.fragment.queued").count(), 1)
        self.assertNotIn("sensitive", job.storage_key)

    def test_identical_retry_after_restart_returns_original_receipt_without_effects(self):
        first, _ = self.receive()
        count = CaptureEvent.objects.count()
        self.ingestion = FragmentIngestionService(FragmentStorage(self.root, self.storage.max_bytes))
        second, created = self.receive(now=NOW + timedelta(seconds=25))
        self.assertFalse(created)
        self.assertEqual(first, second)
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(AcceptedSequence.objects.count(), 1)
        self.assertEqual(CaptureEvent.objects.count(), count)
        self.assertEqual(len(self.blobs()), 1)

    def test_different_checksum_or_capture_time_conflicts_without_changing_original(self):
        first, _ = self.receive()
        for changes in (dict(content=wav_bytes(b"\x01\x00" * 160)),
                        dict(captured_at=NOW + timedelta(seconds=11))):
            with self.subTest(changes=tuple(changes)), self.assertRaises(FragmentError) as caught:
                self.receive(**changes)
            self.assertEqual(caught.exception.code, "SEQUENCE_CONFLICT")
        self.assertEqual(FragmentJob.objects.get().pk, first.job_id)
        self.assertEqual(self.blobs()[0].read_bytes(), wav_bytes())

    def test_accepts_finalizing_then_completes_and_retries_even_after_closure(self):
        self.ack_stop(self.stop(), last_sequence=0)
        first, created = self.receive(now=NOW + timedelta(seconds=36))
        self.assertTrue(created)
        self.assertEqual(CaptureSession.objects.get().state, "completada")
        second, created = self.receive(now=NOW + timedelta(seconds=40))
        self.assertEqual(first, second)
        self.assertFalse(created)

    def test_final_sequence_caps_even_consecutive_later_uploads(self):
        self.ack_stop(self.stop(), last_sequence=0)
        self.assert_code("SEQUENCE_OUT_OF_ORDER", self.receive, number=1, now=NOW + timedelta(seconds=36))
        self.receive(now=NOW + timedelta(seconds=36))
        self.assert_code("SESSION_NOT_ACCEPTING_SEQUENCES", self.receive, number=1,
                         now=NOW + timedelta(seconds=37))
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(len(self.blobs()), 1)

    def test_job_failure_rolls_back_sequence_session_and_events_and_removes_file(self):
        count = CaptureEvent.objects.count()
        with patch("backend.apps.capture.ingestion.FragmentJob.objects.create", side_effect=IntegrityError("private")):
            with self.assertRaises(IntegrityError):
                self.receive()
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(AcceptedSequence.objects.exists())
        self.assertEqual(CaptureSession.objects.get().next_sequence, 0)
        self.assertEqual(CaptureEvent.objects.count(), count)
        self.assertEqual(self.blobs(), [])

    def test_event_failure_rolls_back_job_too(self):
        with patch("backend.apps.capture.ingestion._event", side_effect=IntegrityError("private")):
            with self.assertRaises(IntegrityError):
                self.receive()
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(AcceptedSequence.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_rejects_wrong_box_and_invalid_states_but_recovers_disconnected_session(self):
        with self.assertRaises(FragmentError) as caught:
            self.receive(box="box-4")
        self.assertEqual(caught.exception.code, "SESSION_NOT_FOUND")
        for state in ("iniciada", "fallida", "completada"):
            CaptureSession.objects.filter(pk=self.session.session_id).update(state=state)
            self.assert_code("SESSION_NOT_ACCEPTING_SEQUENCES", self.receive)
        CaptureSession.objects.filter(pk=self.session.session_id).update(state="activa")
        result, created = self.receive(now=NOW + timedelta(minutes=3))
        self.assertTrue(created)
        self.assertEqual(CaptureSession.objects.get().state, "activa")
        self.assertEqual(FragmentJob.objects.get().pk, result.job_id)
        self.assertEqual(len(self.blobs()), 1)

    def test_rejects_gaps_and_invalid_capture_timestamps(self):
        self.assert_code("SEQUENCE_OUT_OF_ORDER", self.receive, number=1)
        self.assert_code("SEQUENCE_OUTSIDE_CAPTURE_WINDOW", self.receive, captured_at=NOW - timedelta(seconds=1))
        self.assert_code("SEQUENCE_OUTSIDE_CAPTURE_WINDOW", self.receive, captured_at=NOW + timedelta(seconds=21))
        self.assertEqual(self.blobs(), [])

    def test_validates_actual_size_checksum_and_wav_structure(self):
        self.storage.max_bytes = len(wav_bytes()) - 1
        with self.assertRaises(FragmentError) as caught:
            self.receive()
        self.assertEqual(caught.exception.code, "FRAGMENT_TOO_LARGE")
        self.storage.max_bytes = 25 * 1024 * 1024
        cases = [(dict(content=b""), "EMPTY_FRAGMENT"),
                 (dict(checksum="0" * 64), "CHECKSUM_MISMATCH"),
                 (dict(content=b"not-a-wave"), "INVALID_FRAGMENT_FILE"),
                 (dict(content=wav_bytes()[:-1]), "INVALID_FRAGMENT_FILE"),
                 (dict(content=wav_bytes() + b"extra"), "INVALID_FRAGMENT_FILE"),
                 (dict(content=wav_bytes(b"")), "INVALID_FRAGMENT_FILE"),
                 (dict(content=wav_bytes(b"\x00")), "INVALID_FRAGMENT_FILE"),
                 (dict(format="mp3"), "FRAGMENT_FORMAT_UNSUPPORTED")]
        for args, code in cases:
            with self.subTest(code=code), self.assertRaises(FragmentError) as caught:
                self.receive(**args)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.blobs(), [])
        self.assertFalse(AcceptedSequence.objects.exists())

    def test_rejects_other_pcm_profiles_compression_and_forged_chunks(self):
        original = wav_bytes()
        for offset, packed in ((20, struct.pack("<H", 3)), (22, struct.pack("<H", 2)),
                               (24, struct.pack("<I", 44100)), (34, struct.pack("<H", 8))):
            content = original[:offset] + packed + original[offset + len(packed):]
            with self.subTest(offset=offset), self.assertRaises(FragmentError) as caught:
                self.receive(content=content)
            self.assertEqual(caught.exception.code, "FRAGMENT_FORMAT_UNSUPPORTED")
        content = original[:40] + struct.pack("<I", 1000000) + original[44:]
        with self.assertRaises(FragmentError) as caught:
            self.receive(content=content)
        self.assertEqual(caught.exception.code, "INVALID_FRAGMENT_FILE")
        self.assertEqual(self.blobs(), [])

    def test_same_number_is_independent_between_sessions_but_each_has_one_job(self):
        self.receive()
        authorization = replace(self.authorization, box="box-4")
        other = self.service.apply_authorization(authorization, now=NOW)
        command, = self.service.commands("box-4", now=NOW)
        self.service.acknowledge("box-4", command.command_id, now=NOW)
        self.receive(box="box-4", session_id=other.session_id)
        self.assertEqual(FragmentJob.objects.count(), 2)
        self.assertEqual(AcceptedSequence.objects.count(), 2)
        self.assertEqual(len(self.blobs()), 2)
        job = FragmentJob.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            FragmentJob.objects.create(sequence=job.sequence, storage_key="0" * 32 + ".blob",
                                       checksum=job.checksum, size=job.size)

    def test_does_not_attach_a_job_to_a_sequence_registered_by_the_legacy_port(self):
        self.accept(self.session)
        with self.assertRaises(FragmentError) as caught:
            self.receive()
        self.assertEqual(caught.exception.code, "SEQUENCE_ALREADY_REGISTERED")
        self.assertFalse(FragmentJob.objects.exists())

    def test_file_failure_cannot_create_a_job(self):
        with patch("backend.apps.capture.storage.os.fsync", side_effect=OSError("sensitive")):
            with self.assertRaises(FragmentError) as caught:
                self.receive()
        self.assertEqual(caught.exception.code, "FRAGMENT_STORAGE_UNAVAILABLE")
        self.assertNotIn("sensitive", str(caught.exception))
        self.assertFalse(FragmentJob.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_publication_failure_before_or_after_move_never_confirms_or_leaves_a_job(self):
        from .filesystem import publish_file

        def moved_then_failed(source, destination):
            publish_file(source, destination)
            raise OSError("private publication error")

        for failure in (OSError("private publication error"), moved_then_failed):
            with self.subTest(after_move=callable(failure)):
                with patch("backend.apps.capture.storage.publish_file", side_effect=failure):
                    with self.assertRaises(FragmentError) as caught:
                        self.receive()
                self.assertEqual(caught.exception.code, "FRAGMENT_STORAGE_UNAVAILABLE")
                self.assertFalse(FragmentJob.objects.exists())
                self.assertFalse(AcceptedSequence.objects.exists())
                self.assertEqual(self.blobs(), [])
                self.assertFalse(list(self.root.glob("*.part")))


class FragmentConcurrencyTests(IngestionFixtures, TransactionTestCase):
    race = lifecycle_tests.CaptureConcurrencyTests.race

    def test_concurrent_identical_retries_have_one_file_one_job_and_one_sequence(self):
        results = self.race(*[self.receive] * 4)
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({result for result, _ in results}), 1)
        self.assertEqual(len(self.blobs()), 1)
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(AcceptedSequence.objects.count(), 1)
        self.assertEqual(CaptureSession.objects.get().next_sequence, 1)

    def test_concurrent_different_checksums_only_accept_one_payload(self):
        def send(content):
            try:
                return self.receive(content=content)[1]
            except FragmentError as exc:
                return exc.code
        results = self.race(lambda: send(wav_bytes()), lambda: send(wav_bytes(b"\x01\x00" * 160)))
        self.assertCountEqual(results, [True, "SEQUENCE_CONFLICT"])
        job = FragmentJob.objects.get()
        self.assertEqual(hashlib.sha256(self.blobs()[0].read_bytes()).hexdigest(), job.checksum)

    def test_returned_receipt_is_committed_and_queue_survives_service_restart(self):
        result, _ = self.receive()
        saved = FragmentJob.objects.get(pk=result.job_id)
        self.assertEqual(saved.state, "pendiente")
        self.assertEqual(saved.sequence.session_id, self.session.session_id)
        self.assertEqual((self.root / saved.storage_key).read_bytes(), wav_bytes())

    def test_cannot_acknowledge_inside_a_transaction_that_can_later_rollback(self):
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.receive()
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(AcceptedSequence.objects.exists())
        self.assertEqual(self.blobs(), [])

    def test_uncertain_commit_keeps_file_and_retry_returns_committed_receipt(self):
        original = connection.commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            original()
            if calls == 3:
                raise OperationalError("Simulated lost commit acknowledgement")

        with patch.object(connection, "commit", side_effect=commit):
            with self.assertRaises(OperationalError):
                self.receive()
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(len(self.blobs()), 1)
        result, created = self.receive()
        self.assertFalse(created)
        self.assertEqual(result.job_id, FragmentJob.objects.get().pk)

    def test_failed_commit_leaves_only_an_orphan_for_safe_cleanup(self):
        original = connection.commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OperationalError("Simulated rejected commit")
            original()

        with patch.object(connection, "commit", side_effect=commit):
            with self.assertRaises(OperationalError):
                self.receive()
        self.assertFalse(FragmentJob.objects.exists())
        self.assertFalse(AcceptedSequence.objects.exists())
        self.assertEqual(CaptureSession.objects.get().next_sequence, 0)
        self.assertEqual(len(self.blobs()), 1)
