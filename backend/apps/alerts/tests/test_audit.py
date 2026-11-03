import json
import os
import unittest
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import patch

from django.test import SimpleTestCase
from pymongo.errors import AutoReconnect, WriteError
from backend.apps.alerts.mongo import close_client

from backend.apps.alerts.audit import AlertAudit
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.alerts.tests.test_persistence import FakeDatabase, alta_pendiente
from backend.apps.alerts.demo import EVALUADOR_ID
from backend.apps.analysis.audit import AnalysisAudit


class AuditPersistenceTests(SimpleTestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.repo = AlertsRepository(self.db)

    def test_creation_and_evaluation_share_logger_ids_and_have_actors(self):
        alert = alta_pendiente()
        with patch('backend.common.audit.logging.getLogger') as logger:
            self.repo.insert_alert(alert)
            AlertsService(self.repo).record_evaluation(alert.alerta_id, 'correcta', EVALUADOR_ID, 'profesional')
        events = self.db['audit_events'].docs
        self.assertEqual([e['action'] for e in events], ['alerts.register', 'alerts.evaluate'])
        self.assertEqual(events[0]['actor'], 'Sistema')
        self.assertEqual(events[0]['sesion_id'], alert.sesion_id)
        self.assertEqual(events[1]['actor_id'], EVALUADOR_ID)
        self.assertEqual(events[1]['actor'], 'Usuario')
        logged = [json.loads(c.args[0]) for c in logger.return_value.info.call_args_list]
        self.assertEqual([e['event_id'] for e in logged], [e['event_id'] for e in events])
        self.assertTrue(all(e['timestamp'].tzinfo for e in events))
        self.assertNotIn('profesional', json.dumps(logged))

    def test_audit_failure_preserves_alert_and_original_log(self):
        self.repo.ensure_schema()
        with patch.object(self.db['audit_events'], 'insert_one', side_effect=AutoReconnect('secret')):
            with self.assertLogs('psycode.audit', level='INFO') as logs:
                self.repo.insert_alert(alta_pendiente())
        self.assertEqual(len(self.db['alerts'].docs), 1)
        self.assertNotIn('secret', ' '.join(logs.output))
        event_id = json.loads(logs.records[0].message)['event_id']
        self.assertIn(event_id, logs.records[1].message)

    def test_technical_failure_has_correlation_and_no_free_text(self):
        audit = AnalysisAudit(lambda: self.db['audit_events'])
        alert = alta_pendiente()
        audit.failure('JEV_FAILED', sesion_id=alert.sesion_id, sequence=4)
        event = self.db['audit_events'].docs[0]
        self.assertEqual(event['sequence'], 4)
        self.assertEqual(event['sesion_id'], alert.sesion_id)
        self.assertIsNone(event['alerta_id'])
        with self.assertRaises(ValueError):
            audit.failure('token=secret')
        with self.assertRaises(TypeError):
            AlertAudit(lambda: self.db['audit_events']).record('alerts.flow', 'failure', email='private@example.com')

    def test_events_require_alert_and_human_evaluation_actor(self):
        audit = AlertAudit(lambda: self.db['audit_events'])
        with self.assertRaises(ValueError):
            audit.record('alerts.register', 'success')
        with self.assertRaises(ValueError):
            audit.record('alerts.evaluate', 'success', alerta_id=alta_pendiente().alerta_id)
        self.assertEqual(self.db['audit_events'].docs, [])


@unittest.skipUnless(os.getenv('PSYCODE_TEST_MONGODB_URI'), 'requiere MongoDB real')
class MongoAuditIntegrationTests(SimpleTestCase):
    def setUp(self):
        close_client()
        self.repo = AlertsRepository()
        self.repo.ensure_schema()
        # BSON redondea a milisegundos; usar instantes distintos para probar rangos
        # sin confundirlos con el desempate documentado por event_id.
        start, ticks = datetime.now(timezone.utc), count()
        clock = patch('backend.apps.alerts.audit.timezone.now',
                      side_effect=lambda: start + timedelta(milliseconds=next(ticks)))
        clock.start()
        self.addCleanup(clock.stop)
        self.alert = alta_pendiente(alerta_id=str(uuid4()), sesion_id=str(uuid4()))
        self.repo.insert_alert(self.alert)

    def tearDown(self):
        self.repo._db()['alerts'].delete_many({'alerta_id': self.alert.alerta_id})
        self.repo._events().delete_many({'$or': [{'alerta_id': self.alert.alerta_id},
                                                {'sesion_id': self.alert.sesion_id}]})
        close_client()

    def filters(self, **overrides):
        data = dict(alerta_id=self.alert.alerta_id, order='asc', limit=100, offset=0)
        data.update(overrides)
        return data

    def test_full_lifecycle_queries_pagination_and_schema(self):
        from backend.apps.notifications.services import NotificationService
        from backend.apps.notifications.domain import NotificationPayload, AttemptResult
        from backend.apps.notifications.recipients import RecipientResult
        from unittest.mock import Mock
        primary, backup = Mock(), Mock()
        primary.send.return_value = AttemptResult('email', False, 3, 'NOTIFICATION_TIMEOUT')
        primary.send.side_effect = [primary.send.return_value, AttemptResult('email', True, 2)]
        notifier = NotificationService(email_client=primary, backup_email_client=backup,
                                       store=self.repo, enabled=True, recipient_resolver=Mock(
                                           resolve=Mock(return_value=RecipientResult(
                                               'supervisores_activos', ('first@example.test', 'second@example.test')))))
        self.assertTrue(notifier.notify_alert(self.alert.alerta_id,
            NotificationPayload('MEDIO', 'riesgo_suicida', 'box-3', '10:00')).enviado)
        AlertsService(self.repo).record_evaluation(self.alert.alerta_id, 'correcta', EVALUADOR_ID, 'profesional')
        events, total = self.repo.list_events(self.filters())
        self.assertEqual(total, 5)
        self.assertEqual([e['action'] for e in events],
                         ['alerts.register', 'notifications.send', 'notifications.send',
                          'notifications.result', 'alerts.evaluate'])
        failed, total = self.repo.list_events(self.filters(action='notifications.send', outcome='failure'))
        self.assertEqual(total, 1)
        self.assertEqual(failed[0]['error_code'], 'NOTIFICATION_TIMEOUT')
        reverse, _ = self.repo.list_events(self.filters(order='desc', offset=1, limit=2))
        self.assertEqual([e['event_id'] for e in reverse], [events[3]['event_id'], events[2]['event_id']])
        within, _ = self.repo.list_events(self.filters(fecha_desde=events[1]['timestamp'],
                                                     fecha_hasta=events[2]['timestamp']))
        self.assertEqual(len(within), 2)
        outside, _ = self.repo.list_events(self.filters(fecha_desde=events[-1]['timestamp'] + timedelta(seconds=1)))
        self.assertEqual(outside, [])
        invalid_actor = dict(events[0], event_id=str(uuid4()), actor='Usuario', actor_id=None)
        with self.assertRaises(WriteError):
            self.repo._events().insert_one(invalid_actor)
        invalid_alert = dict(events[0], event_id=str(uuid4()), alerta_id=None)
        with self.assertRaises(WriteError):
            self.repo._events().insert_one(invalid_alert)
        for forbidden in ('audio', 'transcripcion', 'email', 'token', 'password', 'paciente'):
            invalid = dict(events[0], event_id=str(uuid4()), **{forbidden: 'must-not-store'})
            with self.assertRaises(WriteError):
                self.repo._events().insert_one(invalid)

    def test_technical_failure_persists_with_session_and_sequence(self):
        AnalysisAudit(self.repo._events).failure('FLOW_INTERRUPTED',
            sesion_id=self.alert.sesion_id, sequence=9)
        events, total = self.repo.list_events(self.filters(alerta_id=None, action='alerts.flow'))
        event = next(e for e in events if e['sesion_id'] == self.alert.sesion_id)
        self.assertEqual(event['sequence'], 9)
        self.assertEqual(event['actor'], 'Sistema')
