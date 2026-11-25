import json
from itertools import product
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from backend.apps.alerts.audit import AlertAudit
from backend.apps.alerts.audit_api import AuditEventSerializer
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.tests.test_persistence import FakeDatabase, alta_pendiente
from .domain import AttemptResult, NotificationPayload
from .recipients import RecipientResult
from .services import NotificationService


class NotificationAuditTests(SimpleTestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.store = AlertsRepository(self.db)
        self.alert = alta_pendiente(descripcion='CONTENIDO_CLINICO_PRIVADO')
        self.store.insert_alert(self.alert)
        self.primary, self.backup = Mock(), Mock()
        self.resolver = Mock()
        self.service = NotificationService(
            email_client=self.primary, backup_email_client=self.backup,
            enabled=True, store=self.store, recipient_resolver=self.resolver,
        )
        self.payload = NotificationPayload('MEDIO', 'riesgo_suicida', 'box-3', '10:00')

    def events(self):
        return [item for item in self.db['audit_events'].docs if item['action'].startswith('notifications.')]

    def notify(self):
        return self.service.notify_alert(self.alert.alerta_id, self.payload)

    def test_counts_and_correlation_for_both_modes_all_failures_and_backup_states(self):
        for mode, size in [('lista_distribucion', 1), ('supervisores_activos', 3)]:
            for outcomes in product((False, True), repeat=size):
                for enabled, backup_success in product((False, True), repeat=2):
                    with self.subTest(mode=mode, outcomes=outcomes, enabled=enabled, backup_success=backup_success):
                        self.db['audit_events'].docs.clear()
                        self.resolver.resolve.return_value = RecipientResult(
                            mode, tuple(f'privado-{n}@example.test' for n in range(size)),
                            backup_enabled=enabled, backup_email='encargado@example.test',
                        )
                        self.primary.send.side_effect = [
                            AttemptResult('email', accepted, 3, None if accepted else 'NOTIFICATION_REJECTED')
                            for accepted in outcomes
                        ]
                        self.backup.send.return_value = AttemptResult(
                            'email', backup_success, 2, None if backup_success else 'NOTIFICATION_TIMEOUT')
                        result = self.notify()
                        events = self.events()
                        attempts, summary = events[:-1], events[-1]
                        used_backup = enabled and not all(outcomes)
                        self.assertEqual(len(attempts), size + used_backup)
                        self.assertEqual(summary['action'], 'notifications.result')
                        self.assertEqual(summary['contingencia'], used_backup)
                        self.assertEqual({e['alerta_id'] for e in events}, {self.alert.alerta_id})
                        self.assertEqual({e['sesion_id'] for e in events}, {self.alert.sesion_id})
                        self.assertEqual(len({e['notification']['id'] for e in events}), 1)
                        self.assertEqual({e['notification']['mode'] for e in events}, {mode})
                        self.assertEqual([e['notification']['attempt'] for e in attempts], list(range(1, len(attempts) + 1)))
                        self.assertEqual([e['outcome'] for e in attempts[:size]],
                                         ['success' if success else 'failure' for success in outcomes])
                        self.assertTrue(all(e['notification']['phase'] == 'principal' and not e['contingencia'] for e in attempts[:size]))
                        meta = summary['notification']
                        self.assertEqual(meta['primary_successes'], sum(outcomes))
                        self.assertEqual(meta['primary_failures'], size - sum(outcomes))
                        self.assertEqual(meta['backup_successes'], int(used_backup and backup_success))
                        self.assertEqual(meta['backup_failures'], int(used_backup and not backup_success))
                        self.assertEqual(meta['status'], result.estado)
                        self.assertEqual(summary['outcome'], 'success' if all(outcomes) else 'failure')
                        if used_backup:
                            reason = 'FALLO_PARCIAL' if any(outcomes) else 'FALLO_TOTAL'
                            self.assertEqual(attempts[-1]['notification']['phase'], 'respaldo')
                            self.assertEqual(attempts[-1]['notification']['reason'], reason)
                            self.assertEqual(meta['reason'], reason)
                        serialized = json.dumps(events, default=str)
                        for forbidden in ['@', 'CONTENIDO_CLINICO_PRIVADO', 'encargado']:
                            self.assertNotIn(forbidden, serialized)

    def test_no_valid_recipients_is_recorded_even_if_backup_recovers_delivery(self):
        for mode in (None, 'lista_distribucion', 'supervisores_activos'):
            for enabled, accepted in product((False, True), repeat=2):
                with self.subTest(mode=mode, enabled=enabled, accepted=accepted):
                    self.db['audit_events'].docs.clear()
                    self.primary.reset_mock()
                    self.resolver.resolve.return_value = RecipientResult(
                        mode, (), 'SIN_DESTINATARIOS_VALIDOS', enabled, 'respaldo@example.test')
                    self.backup.send.return_value = AttemptResult(
                        'email', accepted, 2, None if accepted else 'NOTIFICATION_REJECTED')
                    self.notify()
                    events = self.events()
                    summary = events[-1]
                    self.assertEqual(summary['notification']['reason'], 'SIN_DESTINATARIOS_VALIDOS')
                    self.assertEqual(summary['notification']['primary_successes'], 0)
                    self.assertEqual(summary['notification']['primary_failures'], 0)
                    used_backup = mode == 'supervisores_activos' and enabled
                    self.assertEqual(summary['contingencia'], used_backup)
                    self.assertEqual(summary['outcome'], 'failure' if used_backup else 'skipped')
                    self.assertEqual(len(events), 2 if used_backup else 1)
                    self.primary.send.assert_not_called()

    def test_repeated_notifications_of_same_alert_have_distinct_ids_and_identical_logs(self):
        self.resolver.resolve.return_value = RecipientResult('lista_distribucion', ('privado@example.test',))
        self.primary.send.side_effect = RuntimeError('token=SECRETO_PRIVADO email=privado@example.test')
        with self.assertLogs('psycode.audit', level='INFO') as captured:
            self.notify()
            self.notify()
        events = self.events()
        self.assertEqual(len({e['notification']['id'] for e in events}), 2)
        logged = [json.loads(record.message) for record in captured.records]
        self.assertEqual([e['notification'] for e in events], [e['notification'] for e in logged])
        self.assertNotIn('SECRETO_PRIVADO', str(logged))
        self.assertNotIn('@', str(logged))
        self.assertNotIn('CONTENIDO_CLINICO_PRIVADO', str(logged))

    def test_metadata_rejects_free_text_extra_fields_and_invalid_counts_before_logging(self):
        valid = dict(id=str(uuid4()), mode='lista_distribucion', phase='resumen', reason=None,
                     status='EXITO_TOTAL', primary_successes=1, primary_failures=0,
                     backup_successes=0, backup_failures=0)
        invalids = [dict(valid, **{name: 'privado@example.test'})
                    for name in ('id', 'mode', 'phase', 'reason', 'status', 'email')]
        invalids += [dict(valid, primary_successes=value) for value in (-1, True, '1')]
        audit = AlertAudit(lambda: self.db['audit_events'])
        with patch('backend.apps.alerts.audit.AuditWriter.emit') as emit:
            for invalid in invalids:
                with self.assertRaises(ValueError):
                    audit.record('notifications.result', 'success', alerta_id=self.alert.alerta_id,
                                 notification=invalid)
            emit.assert_not_called()

    def test_serializer_preserves_historical_events_and_excludes_unexpected_nested_fields(self):
        historical = dict(self.db['audit_events'].docs[0], action='notifications.send')
        historical.pop('sesion_id')
        historical.pop('sequence')
        historical.pop('actor')
        output = AuditEventSerializer(historical).data
        self.assertIsNone(output['notification'])
        self.assertIsNone(output['sesion_id'])
        self.assertEqual(output['actor'], 'Sistema')
        self.resolver.resolve.return_value = RecipientResult('lista_distribucion', (), 'SIN_DESTINATARIOS_VALIDOS')
        self.notify()
        event = self.events()[-1]
        event['notification']['email'] = 'privado@example.test'
        event['token'] = 'SECRETO_PRIVADO'
        data = AuditEventSerializer(event).data
        self.assertEqual(data['notification']['status'], 'SIN_DESTINATARIOS_VALIDOS')
        self.assertNotIn('@', str(data))
        self.assertNotIn('SECRETO_PRIVADO', str(data))
