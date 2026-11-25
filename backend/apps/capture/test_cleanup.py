import os
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, close_old_connections, connections
from django.test import TestCase, TransactionTestCase, override_settings

from .cleanup import clean_orphan_fragments
from .models import FragmentJob
from .test_ingestion import IngestionFixtures, wav_bytes
from .tests import NOW


class FragmentCleanupTests(IngestionFixtures, TestCase):
    def clean(self):
        return clean_orphan_fragments(self.storage, older_than_seconds=3600,
                                      now=NOW + timedelta(days=30))

    def orphan(self):
        with self.storage.stage(self._upload(), self._checksum()) as stored:
            stored.keep = True
            return self.root / stored.key

    @staticmethod
    def _upload():
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile("fragment.wav", wav_bytes())

    @staticmethod
    def _checksum():
        import hashlib
        return hashlib.sha256(wav_bytes()).hexdigest()

    def test_removes_old_orphans_and_keeps_all_jobs_regardless_of_state(self):
        self.receive()
        path = self.blobs()[0]
        os.utime(path, (0, 0))
        orphan = self.orphan()
        os.utime(orphan, (0, 0))
        result = self.clean()
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.protected, 1)
        self.assertFalse(orphan.exists())
        for state in FragmentJob.State.values:
            FragmentJob.objects.update(state=state)
            self.assertEqual(self.clean().protected, 1)
            self.assertTrue(path.exists())
        self.assertEqual(self.clean().removed, 0)

    def test_does_not_remove_a_staging_file_or_incoming_upload_with_a_live_lease(self):
        with self.storage.stage(self._upload(), self._checksum()) as staged:
            incoming = self.storage.incoming()
            try:
                os.utime(self.root / staged.key, (0, 0))
                os.utime(incoming.name, (0, 0))
                result = self.clean()
                self.assertEqual(result.removed, 0)
                self.assertEqual(result.busy, 2)
            finally:
                incoming.close()

    def test_does_not_remove_recent_files_unmanaged_files_or_symlinks(self):
        orphan = self.orphan()
        unrelated = self.root / "PRIVATE-not-managed.txt"
        unrelated.write_text("fixture")
        link = self.root / ("a" * 32 + ".blob")
        try:
            link.symlink_to(unrelated)
        except OSError as exc:
            if os.name != "nt" or exc.winerror != 1314:
                raise
            self.skipTest("Crear symlinks en Windows requiere Developer Mode o privilegios.")
        result = clean_orphan_fragments(self.storage, older_than_seconds=3600)
        self.assertEqual(result.removed, 0)
        self.assertTrue(orphan.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(link.is_symlink())

    def test_database_failure_never_treats_a_file_as_unreferenced(self):
        orphan = self.orphan()
        os.utime(orphan, (0, 0))
        with patch("backend.apps.capture.cleanup.FragmentJob.objects.filter", side_effect=OperationalError("PRIVATE")):
            with self.assertRaises(OperationalError):
                self.clean()
        self.assertTrue(orphan.exists())

    def test_another_cleanup_does_not_block_or_delete_files(self):
        with self.storage.allocation_lock(cleanup=True):
            result = self.clean()
        self.assertEqual(result.busy, 1)
        self.assertEqual(result.removed, 0)

    def test_command_reports_only_counts_and_has_safe_errors(self):
        orphan = self.orphan()
        os.utime(orphan, (0, 0))
        with override_settings(CAPTURE_FRAGMENT_ROOT=self.root):
            output = StringIO()
            call_command("cleanup_capture_uploads", stdout=output)
            self.assertIn("Archivos eliminados: 1", output.getvalue())
            self.assertNotIn(str(self.root), output.getvalue())
            with self.assertRaises(CommandError):
                call_command("cleanup_capture_uploads", older_than_seconds=0)
            with patch("backend.apps.capture.management.commands.cleanup_capture_uploads.clean_orphan_fragments",
                       side_effect=OperationalError("PRIVATE")):
                with self.assertRaises(CommandError) as caught:
                    call_command("cleanup_capture_uploads")
            self.assertEqual(str(caught.exception), "PERSISTENCE_UNAVAILABLE")

    def test_process_crash_leaves_an_orphan_that_the_next_cleanup_removes(self):
        code = """
import os, sys
from backend.apps.capture.storage import FragmentStorage
storage = FragmentStorage(sys.argv[1], 1024)
stream = storage.incoming()
stream.write(b'partial fixture')
stream.flush()
os.fsync(stream.fileno())
os.utime(stream.name, (0, 0))
os._exit(0)
"""
        subprocess.run([sys.executable, "-c", code, str(self.root)], check=True, timeout=10)
        self.assertEqual(len(list(self.root.glob("*.part"))), 1)
        self.assertEqual(self.clean().removed, 1)
        self.assertFalse(list(self.root.glob("*.part")))


class ConcurrentCleanupTests(IngestionFixtures, TransactionTestCase):
    def test_cleanup_cannot_enter_while_publication_temporarily_releases_file_lease(self):
        from .filesystem import publish_file

        ready, release = Event(), Event()

        def publishing(source, destination):
            ready.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Test timed out")
            publish_file(source, destination)

        def send():
            close_old_connections()
            try:
                return self.receive()
            finally:
                connections.close_all()

        with patch("backend.apps.capture.storage.publish_file", side_effect=publishing):
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(send)
                try:
                    self.assertTrue(ready.wait(timeout=10))
                    path, = self.root.glob("incoming-*.part")
                    os.utime(path, (0, 0))
                    result = clean_orphan_fragments(self.storage, older_than_seconds=1)
                    self.assertEqual(result.removed, 0)
                    self.assertEqual(result.busy, 1)
                finally:
                    release.set()
                self.assertTrue(pending.result(timeout=10)[1])
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(self.blobs()[0].read_bytes(), wav_bytes())

    def test_cleanup_racing_with_a_slow_upload_cannot_remove_it(self):
        ready, release = Event(), Event()

        class SlowUpload:
            def chunks(self, chunk_size):
                yield wav_bytes()
                ready.set()
                if not release.wait(timeout=10):
                    raise RuntimeError("Test timed out")

        def send():
            close_old_connections()
            try:
                return self.receive(upload=SlowUpload())
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(send)
            try:
                self.assertTrue(ready.wait(timeout=10))
                os.utime(next(self.root.glob("incoming-*.part")), (0, 0))
                result = clean_orphan_fragments(self.storage, older_than_seconds=1)
                self.assertEqual(result.busy, 1)
                self.assertEqual(result.removed, 0)
            finally:
                release.set()
            _, created = pending.result(timeout=10)
        self.assertTrue(created)
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(self.blobs()[0].read_bytes(), wav_bytes())
        os.utime(self.blobs()[0], (0, 0))
        self.assertEqual(clean_orphan_fragments(self.storage, older_than_seconds=1).protected, 1)
