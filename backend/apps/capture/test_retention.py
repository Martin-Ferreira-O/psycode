import errno
import os
import signal
import threading
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone

from .filesystem import lock_file, open_private
from .models import CaptureEvent, CaptureSession, FragmentJob, StorageCleanupRun, StorageDeletion
from .retention import cleanup, inventory
from .storage import FragmentStorage
from .test_ingestion import IngestionFixtures
from .tests import NOW


class RetentionTests(IngestionFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.receive()
        self.job = FragmentJob.objects.select_related('sequence__session').get()
        self.received = self.job.sequence.accepted_at
        self.after = self.received + timedelta(hours=25)

    def finish(self):
        FragmentJob.objects.update(state=FragmentJob.State.COMPLETED, checkpoint={'history': [{'text': 'sintetico'}]})

    def close(self):
        CaptureSession.objects.update(actual_end=self.received, final_sequence=0, state='completada')

    def test_minimum_is_central_reception_not_mtime_capture_or_completion(self):
        self.finish()
        os.utime(self.blobs()[0], (0, 0))
        cleanup(self.storage, now=self.received + timedelta(hours=24) - timedelta(microseconds=1))
        self.assertEqual(len(self.blobs()), 1)
        run = cleanup(self.storage, now=self.received + timedelta(hours=24))
        self.assertEqual(run.removed, 1)
        self.assertEqual(run.freed_bytes, self.job.size)
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertEqual(StorageDeletion.objects.get().state, 'deleted')

    def test_recoverable_and_active_states_are_protected(self):
        self.close()
        for state in FragmentJob.State.values:
            if state == FragmentJob.State.COMPLETED:
                continue
            FragmentJob.objects.update(state=state)
            self.assertEqual(cleanup(self.storage, now=self.after).removed, 0)
            self.assertEqual(len(self.blobs()), 1)

    def test_active_analysis_never_expires(self):
        self.close()
        FragmentJob.objects.update(state=FragmentJob.State.PROCESSING)
        self.assertEqual(cleanup(self.storage, now=self.after + timedelta(days=30)).removed, 0)

    def test_recoverable_session_expires_as_unit_and_cannot_resume(self):
        self.close()
        FragmentJob.objects.update(state=FragmentJob.State.REVIEW, checkpoint={'utterances': ['sintetico']})
        run = cleanup(self.storage, now=self.received + timedelta(days=7))
        self.assertEqual(run.removed, 1)
        job = FragmentJob.objects.get()
        self.assertIsNotNone(job.sensitive_expired_at)
        self.assertEqual(job.last_error_code, 'RETENTION_EXPIRED')
        self.assertEqual(job.checkpoint, {})
        with self.assertRaises(CommandError):
            call_command('process_fragment_jobs', resume_job=job.pk)

    def test_open_reception_keeps_context_and_pending_jobs(self):
        FragmentJob.objects.update(checkpoint={'utterances': ['sintetico']})
        run = cleanup(self.storage, now=self.received + timedelta(days=30))
        self.assertEqual(run.removed, 0)
        self.assertTrue(FragmentJob.objects.get().checkpoint)

    def test_closed_successful_session_scrubs_context_but_keeps_audio_until_24h(self):
        self.finish()
        self.close()
        count = CaptureEvent.objects.count()
        run = cleanup(self.storage, now=self.received + timedelta(minutes=1))
        self.assertEqual(run.checkpoints, 1)
        self.assertEqual(FragmentJob.objects.get().checkpoint, {})
        self.assertEqual(len(self.blobs()), 1)
        self.assertEqual(CaptureEvent.objects.count(), count)
        self.assertEqual(CaptureSession.objects.count(), 1)

    def test_late_recoverable_fragment_preserves_completed_context(self):
        self.finish()
        CaptureSession.objects.update(actual_end=self.received, final_sequence=1)
        cleanup(self.storage, now=self.after)
        self.assertTrue(FragmentJob.objects.get().checkpoint)

    def test_failed_delete_is_durable_and_retried_after_restart(self):
        self.finish()
        with patch('backend.apps.capture.retention.os.unlink', side_effect=PermissionError(errno.EACCES, 'PRIVATE')):
            run = cleanup(self.storage, now=self.after)
        self.assertEqual(run.outcome, 'partial')
        debt = StorageDeletion.objects.get()
        self.assertEqual(debt.error_code, 'STORAGE_DELETE_FAILED')
        self.assertEqual(debt.attempts, 1)
        restarted = FragmentStorage(self.root, self.storage.max_bytes)
        self.assertEqual(cleanup(restarted, now=self.after).removed, 0)
        self.assertEqual(cleanup(restarted, now=debt.retry_at).removed, 1)
        debt.refresh_from_db()
        self.assertEqual(debt.state, 'deleted')

    def test_sql_failure_before_intent_does_not_remove_bytes(self):
        self.finish()
        with patch('backend.apps.capture.retention.StorageDeletion.objects.get_or_create', side_effect=OperationalError('PRIVATE')):
            with self.assertRaises(OperationalError):
                cleanup(self.storage, now=self.after)
        self.assertEqual(len(self.blobs()), 1)
        self.assertEqual(StorageCleanupRun.objects.get().outcome, 'failure')

    def test_sql_failure_after_unlink_is_reconciled_idempotently(self):
        self.finish()
        with patch('backend.apps.capture.retention.StorageDeletion.objects.filter', side_effect=OperationalError('PRIVATE')):
            with self.assertRaises(OperationalError):
                cleanup(self.storage, now=self.after)
        self.assertEqual(self.blobs(), [])
        self.assertEqual(StorageDeletion.objects.get().state, 'pending')
        run = cleanup(self.storage, now=self.after)
        self.assertEqual(run.freed_bytes, 0)
        self.assertEqual(StorageDeletion.objects.get().state, 'deleted')

    def test_busy_worker_lease_protects_even_a_completed_job(self):
        self.finish()
        with self.storage.lease(self.job.storage_key):
            self.assertEqual(cleanup(self.storage, now=self.after).removed, 0)
            self.assertEqual(inventory(self.storage, now=self.after)['reasons']['archivo_en_uso'], 1)
        self.assertEqual(cleanup(self.storage, now=self.after).removed, 1)

    def test_staging_upload_is_protected_by_file_lock(self):
        upload = self.storage.incoming()
        try:
            os.utime(upload.name, (0, 0))
            self.assertEqual(cleanup(self.storage, now=self.after).removed, 0)
            self.assertTrue(os.path.exists(upload.name))
        finally:
            upload.close()

    def test_inventory_counts_and_preview_revalidates_changed_state(self):
        self.finish()
        view = inventory(self.storage, now=self.after)
        self.assertEqual(view['reclaimable_bytes'], self.job.size)
        self.assertEqual(view['protected_bytes'], 0)
        FragmentJob.objects.update(state=FragmentJob.State.PROCESSING)
        run = cleanup(self.storage, now=self.after, candidates=view['candidates'], source='manual')
        self.assertEqual(run.removed, 0)
        self.assertEqual(run.protected, 1)

    def test_preview_does_not_delete_new_or_replaced_files(self):
        self.finish()
        view = inventory(self.storage, now=self.after)
        self.blobs()[0].write_bytes(b'changed')
        other = self.root / ('a' * 32 + '.blob')
        other.write_bytes(b'orphan')
        os.utime(other, (0, 0))
        self.assertEqual(cleanup(self.storage, now=self.after, candidates=view['candidates']).removed, 0)
        self.assertEqual(len(self.blobs()), 2)

    def test_stale_runs_are_marked_interrupted_and_reported(self):
        StorageCleanupRun.objects.create(started_at=self.received, source='automatic')
        cleanup(self.storage, now=self.after)
        self.assertEqual(StorageCleanupRun.objects.order_by('started_at').first().outcome, 'interrupted')
        report = inventory(self.storage, now=self.after + timedelta(hours=1))
        self.assertGreater(report['delay_seconds'], 0)
        self.assertGreater(report['audit_pending'], 0)

    def test_no_third_party_files_are_candidates(self):
        foreign = self.root / 'third-party.wav'
        foreign.write_bytes(b'fixture')
        cleanup(self.storage, now=self.after)
        self.assertTrue(foreign.exists())

    def test_audit_outbox_retries_same_identity_and_only_technical_counts(self):
        from unittest.mock import Mock
        from .storage_audit import flush_storage_audit
        self.finish()
        run = cleanup(self.storage, now=self.after)
        collection = Mock()
        collection.update_one.side_effect = RuntimeError('PRIVATE')
        self.assertEqual(flush_storage_audit(collection), 0)
        self.assertIsNone(StorageCleanupRun.objects.get().audit_sent_at)
        first = collection.update_one.call_args.args[1]['$setOnInsert']
        self.assertNotIn('sintetico', str(first))
        self.assertEqual(first['storage']['freed_bytes'], self.job.size)
        collection.update_one.side_effect = None
        self.assertEqual(flush_storage_audit(collection), 1)
        second = collection.update_one.call_args.args[1]['$setOnInsert']
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertEqual(second['event_id'], str(run.pk))
        self.assertEqual(flush_storage_audit(collection), 0)

    def test_audit_outbox_omits_only_empty_automatic_successes(self):
        from unittest.mock import Mock
        from .storage_audit import flush_storage_audit

        def finished_run(**overrides):
            values = dict(source='automatic', outcome='success')
            values.update(overrides)
            return StorageCleanupRun.objects.create(started_at=self.received, finished_at=self.after, **values)

        empty = finished_run()
        published = [finished_run(source='manual'), finished_run(outcome='failure'),
                     finished_run(protected=1), finished_run(provider_deleted=1)]
        collection = Mock()
        with patch('backend.apps.capture.storage_audit.AuditWriter.emit') as emit:
            self.assertEqual(flush_storage_audit(collection), len(published))
            self.assertEqual(flush_storage_audit(collection), 0)
        self.assertCountEqual([call.args[0]['event_id'] for call in emit.call_args_list],
                              [str(run.pk) for run in published])
        self.assertEqual(collection.update_one.call_count, len(published))
        empty.refresh_from_db()
        self.assertIsNotNone(empty.audit_sent_at)

    def test_continuous_cleanup_waits_when_sql_is_unavailable(self):
        waits = []

        def wait(self, timeout=None):
            waits.append(timeout)
            self.set()
            return True

        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            with patch.object(StorageCleanupRun.objects, 'order_by', side_effect=OperationalError('private')):
                with patch.object(threading.Event, 'wait', wait):
                    call_command('cleanup_sensitive_storage', '--continuous', stdout=StringIO(), stderr=StringIO())
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        self.assertEqual(waits, [30])
