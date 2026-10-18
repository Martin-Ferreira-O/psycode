import json
from unittest.mock import patch

from django.test import SimpleTestCase
from pymongo.errors import AutoReconnect

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
