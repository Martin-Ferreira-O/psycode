import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from .models import FragmentJob
from .processing import FragmentJobProcessor
from .retention import cleanup
from .test_ingestion import IngestionFixtures, wav_bytes
from .test_processing import FakeAnalysis
from .tests import NOW


class RetentionConcurrencyTests(IngestionFixtures, TransactionTestCase):
    def test_cleanup_with_slow_reception_does_not_remove_or_block_upload(self):
        ready, release = Event(), Event()
        class SlowUpload:
            def chunks(self, chunk_size):
                yield wav_bytes()
                ready.set()
                if not release.wait(10):
                    raise RuntimeError('timeout')
        def receive():
            close_old_connections()
            try:
                return self.receive(upload=SlowUpload())
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(receive)
            try:
                self.assertTrue(ready.wait(10))
                part = next(self.root.glob('incoming-*.part'))
                os.utime(part, (0, 0))
                run = cleanup(self.storage, now=NOW + timedelta(days=30))
                self.assertEqual(run.removed, 0)
                self.assertEqual(run.protected, 1)
                self.assertTrue(part.exists())
            finally:
                release.set()
            self.assertTrue(future.result(10)[1])
        self.assertEqual(len(self.blobs()), 1)

    def test_cleanup_during_analysis_retains_file_and_web_result(self):
        self.receive()
        ready, release = Event(), Event()
        analysis = FakeAnalysis()
        original = analysis.process
        def delayed(*args, **kwargs):
            ready.set()
            if not release.wait(10):
                raise RuntimeError('timeout')
            return original(*args, **kwargs)
        analysis.process = delayed
        processor = FragmentJobProcessor(self.storage, analysis)
        def process():
            close_old_connections()
            try:
                return processor.process_next()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(process)
            try:
                self.assertTrue(ready.wait(10))
                run = cleanup(self.storage, now=NOW + timedelta(days=30))
                self.assertEqual(run.removed, 0)
                self.assertEqual(len(self.blobs()), 1)
            finally:
                release.set()
            self.assertEqual(future.result(10), FragmentJob.State.COMPLETED)
        self.assertEqual(FragmentJob.objects.get().result, FragmentJob.Result.NO_RISK_DETECTED)
        self.assertEqual(len(self.blobs()), 1)
