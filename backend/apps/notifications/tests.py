import subprocess
from unittest.mock import Mock, patch

from django.core import mail
from django.test import SimpleTestCase, override_settings

from backend.apps.alerts.audit import AlertAudit
from backend.apps.alerts.exceptions import AlertAlreadyExists
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.alerts.tests.test_persistence import FakeDatabase, alta_pendiente
from backend.common.errors import PersistenceUnavailable
from .clients import EmailClient
from .domain import NotificationPayload, AttemptResult
from .services import NotificationService


class NotificationsTestCase(SimpleTestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.store = AlertsRepository(self.db)
        self.alert = alta_pendiente(descripcion='transcripción confidencial')
        self.store.insert_alert(self.alert)
        self.primary, self.backup, self.teams = Mock(), Mock(), Mock()
        self.primary.send.return_value = AttemptResult('email', True, 12)
        self.backup.send.return_value = AttemptResult('email', True, 7)
        self.service = NotificationService(email_client=self.primary, backup_email_client=self.backup,
                                           teams_client=self.teams, enabled=True, store=self.store)
        self.payload = NotificationPayload('ALTO', 'Riesgo suicida', 'Box 03', '14:37')

    def notify(self, **kwargs):
        return self.service.notify_alert(kwargs.get('ident', self.alert.alerta_id),
                                         kwargs.get('payload', self.payload))

    def test_primary_success_never_calls_backup_or_teams(self):
        result = self.notify()
        self.assertTrue(result.enviado)
        self.assertEqual(len(result.intentos), 1)
        self.primary.send.assert_called_once()
        self.backup.send.assert_not_called()
        self.teams.send.assert_not_called()
        event = self.db['audit_events'].docs[-1]
        self.assertEqual(event['channel'], 'email')
        self.assertEqual(event['outcome'], 'success')
        self.assertFalse(event['contingencia'])
        self.assertEqual(event['actor'], 'Sistema')

    def test_primary_failure_timeout_and_exception_use_backup_in_order(self):
        for failure in [AttemptResult('email', False, 10, 'NOTIFICATION_REJECTED'),
                        TimeoutError('private@example.com'), RuntimeError('token=secret')]:
            with self.subTest(failure=type(failure).__name__):
                self.primary.reset_mock()
                self.backup.reset_mock()
                calls = Mock()
                calls.attach_mock(self.primary, 'primary')
                calls.attach_mock(self.backup, 'backup')
                self.primary.send.side_effect = failure if isinstance(failure, Exception) else None
                self.primary.send.return_value = failure
                result = self.notify()
                self.assertTrue(result.enviado)
                self.assertEqual([c[0] for c in calls.mock_calls], ['primary.send', 'backup.send'])
                events = self.db['audit_events'].docs[-2:]
                self.assertEqual([e['outcome'] for e in events], ['failure', 'success'])
                self.assertTrue(events[-1]['contingencia'])
                self.assertEqual(len(result.intentos), 2)
                self.assertNotIn('secret', str(events))
                self.assertNotIn('private@example.com', str(events))

    def test_both_fail_preserves_alert(self):
        self.primary.send.return_value = AttemptResult('email', False, 10, 'NOTIFICATION_TIMEOUT')
        self.backup.send.return_value = AttemptResult('email', False, 10, 'NOTIFICATION_CONNECTION_FAILED')
        result = self.notify()
        self.assertFalse(result.enviado)
        self.assertEqual(result.motivo_omision, 'FALLO_DOBLE_CANALES')
        self.assertEqual(self.store.get_alert(self.alert.alerta_id), self.alert)
        self.assertEqual(len(self.db['audit_events'].docs), 3)

    def test_omissions_and_unstored_alert_never_send(self):
        for risk in ('NULO', 'SIN RIESGO', 'NINGUNO', ''):
            self.assertEqual(self.notify(payload=NotificationPayload(risk, 'Ninguno', 'Box 01', '10:00')).motivo_omision,
                             'NULO_O_SIN_RIESGO')
        for ident in ('', 'ALT-001', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'):
            self.assertEqual(self.notify(ident=ident).motivo_omision, 'ALERTA_NO_ALMACENADA')
        with patch.object(self.store, 'get_alert', side_effect=PersistenceUnavailable()):
            self.assertEqual(self.notify().motivo_omision, 'ALERTA_NO_ALMACENADA')
        self.service.enabled = False
        self.assertEqual(self.notify().motivo_omision, 'NOTIFICATIONS_DISABLED')
        self.primary.send.assert_not_called()
        self.backup.send.assert_not_called()

    def test_confirmed_payload_excludes_description_and_caller_free_text(self):
        self.notify(payload=NotificationPayload('ALTO', 'private@example.com', 'token=secret', 'transcripción'))
        payload = self.primary.send.call_args.args[0]
        message = payload.formatear_cuerpo_correo() + payload.formatear_html_correo()
        for forbidden in ('private@example.com', 'token=secret', 'confidencial', self.alert.sesion_id):
            self.assertNotIn(forbidden, message)

    def test_audit_failure_does_not_prevent_backup(self):
        self.primary.send.return_value = AttemptResult('email', False, 0, 'NOTIFICATION_TIMEOUT')
        audit = AlertAudit(Mock(side_effect=PersistenceUnavailable()))
        self.service.audit = audit
        with self.assertLogs('psycode.audit', level='INFO') as logs:
            self.assertTrue(self.notify().enviado)
        self.assertIn('AUDIT_UNAVAILABLE', str(logs.output))

    def test_unexpected_notifier_failure_does_not_reverse_registration(self):
        store = AlertsRepository(FakeDatabase())
        notifier = Mock()
        notifier.notify_alert.side_effect = RuntimeError('secret')
        service = AlertsService(store, notifier)
        alert = service.register_alert(alerta_id=self.alert.alerta_id, box='box-3',
            tipo_riesgo='riesgo_suicida', nivel_severidad=2, fecha_hora=self.alert.fecha_hora,
            sesion_id=self.alert.sesion_id, origen='test')
        self.assertEqual(store.get_alert(alert.alerta_id), alert)
        self.assertEqual(store._db()['audit_events'].docs[-1]['error_code'], 'NOTIFICATION_INTERNAL_ERROR')

    def test_registration_notifies_only_after_successful_insert_and_not_duplicate(self):
        notifier = Mock()
        store = AlertsRepository(FakeDatabase())
        service = AlertsService(store, notifier)
        data = dict(alerta_id=self.alert.alerta_id, box=self.alert.box, tipo_riesgo=self.alert.tipo_riesgo,
                    nivel_severidad=2, fecha_hora=self.alert.fecha_hora, sesion_id=self.alert.sesion_id, origen='test')
        notifier.notify_alert.side_effect = lambda ident, payload: store.get_alert(ident)
        service.register_alert(**data)
        notifier.notify_alert.assert_called_once()
        with self.assertRaises(AlertAlreadyExists):
            service.register_alert(**data)
        notifier.notify_alert.assert_called_once()
        notifier.reset_mock()
        with patch.object(store, 'insert_alert', side_effect=PersistenceUnavailable()):
            with self.assertRaises(PersistenceUnavailable):
                service.register_alert(**data)
        notifier.notify_alert.assert_not_called()


class EmailClientTests(SimpleTestCase):
    def setUp(self):
        self.payload = NotificationPayload('ALTO', 'riesgo_suicida', 'box-3', '2026-10-17T14:00:00Z')

    def test_local_mail_uses_separate_configured_recipients(self):
        self.assertTrue(EmailClient().send(self.payload).exitoso)
        self.assertEqual(mail.outbox[-1].to, ['primary@example.test'])
        self.assertTrue(EmailClient(backup=True).send(self.payload).exitoso)
        self.assertEqual(mail.outbox[-1].to, ['backup@example.test'])

    def test_not_configured_and_zero_messages_sent_are_failures(self):
        self.assertEqual(EmailClient([]).send(self.payload).error, 'NOTIFICATION_NOT_CONFIGURED')
        with patch('backend.apps.notifications.clients.send_mail', return_value=0):
            self.assertEqual(EmailClient().send(self.payload).error, 'NOTIFICATION_REJECTED')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_DELIVERY_TIMEOUT=2)
    def test_smtp_process_is_bounded_and_errors_are_codes(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('smtp', 2)) as run:
            self.assertEqual(EmailClient().send(self.payload).error, 'NOTIFICATION_TIMEOUT')
            self.assertEqual(run.call_args.kwargs['timeout'], 2)
            self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)
        for code, expected in [(0, None), (2, 'NOTIFICATION_TIMEOUT'), (3, 'NOTIFICATION_CONNECTION_FAILED'),
                               (4, 'NOTIFICATION_REJECTED'), (1, 'NOTIFICATION_INTERNAL_ERROR')]:
            with patch('subprocess.run', return_value=Mock(returncode=code)):
                self.assertEqual(EmailClient().send(self.payload).error, expected)


class LocalSMTPTests(SimpleTestCase):
    """Ejercita el proceso real SMTP contra un servidor local sin credenciales."""
    def test_primary_rejected_then_backup_accepted(self):
        import socketserver
        import threading

        recipients, messages = [], []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b'220 localhost test SMTP\r\n')
                while line := self.rfile.readline():
                    command = line.upper()
                    if command.startswith(b'EHLO') or command.startswith(b'HELO'):
                        self.wfile.write(b'250 localhost\r\n')
                    elif command.startswith(b'MAIL') or command.startswith(b'RSET'):
                        self.wfile.write(b'250 OK\r\n')
                    elif command.startswith(b'RCPT'):
                        recipients.append(line.decode().strip())
                        self.wfile.write(b'550 rejected\r\n' if b'primary@' in line else b'250 OK\r\n')
                    elif command.startswith(b'DATA'):
                        self.wfile.write(b'354 send data\r\n')
                        body = []
                        while (data := self.rfile.readline()) not in (b'.\r\n', b''):
                            body.append(data)
                        messages.append(b''.join(body))
                        self.wfile.write(b'250 queued\r\n')
                    elif command.startswith(b'QUIT'):
                        self.wfile.write(b'221 bye\r\n')
                        return
                    else:
                        self.wfile.write(b'250 OK\r\n')

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True

        with Server(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                        EMAIL_HOST='127.0.0.1', EMAIL_PORT=server.server_address[1],
                        EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='', EMAIL_USE_TLS=False,
                        EMAIL_USE_SSL=False, EMAIL_DELIVERY_TIMEOUT=5, EMAIL_TIMEOUT=2):
                    db = FakeDatabase()
                    store = AlertsRepository(db)
                    alert = alta_pendiente(descripcion='sensitive transcript')
                    store.insert_alert(alert)
                    result = NotificationService(store=store, enabled=True).notify_alert(alert.alerta_id,
                        NotificationPayload('MEDIO', 'riesgo_suicida', 'box-3', '10:00'))
                    self.assertTrue(result.enviado)
                    self.assertEqual(result.intentos[0].error, 'NOTIFICATION_REJECTED')
                    self.assertEqual(len(result.intentos), 2)
                self.assertEqual(len(messages), 1)
                self.assertIn('primary@example.test', recipients[0])
                self.assertIn('backup@example.test', recipients[1])
                self.assertNotIn(b'sensitive transcript', messages[0])
                self.assertEqual(len(db['audit_events'].docs), 3)
            finally:
                server.shutdown()
                thread.join(timeout=2)
