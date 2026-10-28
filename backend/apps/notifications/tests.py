import subprocess
from unittest.mock import Mock, patch

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from backend.apps.alerts.audit import AlertAudit
from backend.apps.alerts.exceptions import AlertAlreadyExists
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.alerts.tests.test_persistence import FakeDatabase, alta_pendiente
from backend.common.errors import PersistenceUnavailable
from .clients import EmailClient
from .domain import NotificationPayload, AttemptResult
from .services import NotificationService
from backend.apps.operational.models import OperationalConfiguration
from django.contrib.auth import get_user_model


class NotificationsTestCase(TestCase):
    def setUp(self):
        config = OperationalConfiguration.load()
        config.primary_email = 'primary@example.test'
        config.save()
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

    def test_primary_failure_timeout_and_exception_never_use_backup(self):
        for failure in [AttemptResult('email', False, 10, 'NOTIFICATION_REJECTED'),
                        TimeoutError('private@example.com'), RuntimeError('token=secret')]:
            with self.subTest(failure=type(failure).__name__):
                self.primary.reset_mock()
                self.primary.send.side_effect = failure if isinstance(failure, Exception) else None
                self.primary.send.return_value = failure
                result = self.notify()
                self.assertFalse(result.enviado)
                self.assertEqual(result.estado, 'FALLO_TOTAL')
                self.assertEqual(len(result.intentos), 1)
                self.backup.send.assert_not_called()
                events = self.db['audit_events'].docs
                self.assertNotIn('secret', str(events))
                self.assertNotIn('private@example.com', str(events))
                self.assertEqual(self.store.get_alert(self.alert.alerta_id), self.alert)

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

    def test_audit_failure_preserves_delivery_result(self):
        self.primary.send.return_value = AttemptResult('email', False, 0, 'NOTIFICATION_TIMEOUT')
        audit = AlertAudit(Mock(side_effect=PersistenceUnavailable()))
        self.service.audit = audit
        with self.assertLogs('psycode.audit', level='INFO') as logs:
            self.assertEqual(self.notify().estado, "FALLO_TOTAL")
        self.backup.send.assert_not_called()
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

    def enable_supervisors(self):
        config = OperationalConfiguration.load()
        config.notification_mode = 'supervisores_activos'
        config.save()
        for name in ('first', 'second', 'third'):
            get_user_model().objects.create_user(username=name, email=f'{name}@example.test')
        return ['first@example.test', 'second@example.test', 'third@example.test']

    def test_all_supervisors_are_attempted_for_every_success_failure_combination(self):
        from itertools import product
        addresses = self.enable_supervisors()
        for outcomes in product((False, True), repeat=3):
            with self.subTest(outcomes=outcomes):
                self.primary.send.reset_mock()
                self.primary.send.side_effect = [
                    AttemptResult('email', success, 1, None if success else 'NOTIFICATION_REJECTED')
                    for success in outcomes
                ]
                result = self.notify()
                expected = ('EXITO_TOTAL' if all(outcomes)
                            else 'FALLO_PARCIAL' if any(outcomes) else 'FALLO_TOTAL')
                self.assertEqual(result.estado, expected)
                self.assertEqual(result.enviado, any(outcomes))
                self.assertEqual(len(result.intentos), 3)
                self.assertEqual([call.kwargs['destinatarios'] for call in
                                  self.primary.send.call_args_list], [[email] for email in addresses])
                self.backup.send.assert_not_called()
                config = OperationalConfiguration.load()
                self.assertEqual(config.notification_mode, 'supervisores_activos')

    def test_exception_for_one_supervisor_does_not_stop_remaining_deliveries(self):
        self.enable_supervisors()
        for failure in (TimeoutError('secret@example.test'), RuntimeError('secret@example.test')):
            with self.subTest(failure=type(failure).__name__):
                self.primary.send.reset_mock()
                self.primary.send.side_effect = [failure, AttemptResult('email', True, 1),
                                               AttemptResult('email', True, 1)]
                result = self.notify()
                self.assertEqual(result.estado, 'FALLO_PARCIAL')
                self.assertEqual(self.primary.send.call_count, 3)
                self.assertNotIn('secret@example.test', str(result))
                self.assertNotIn('secret@example.test', str(self.db['audit_events'].docs))

    def test_supervisors_receive_separate_messages_without_other_addresses(self):
        addresses = self.enable_supervisors()
        self.service.email_client = EmailClient(['old@example.test'])
        result = self.notify()
        self.assertEqual(result.estado, 'EXITO_TOTAL')
        self.assertEqual(len(mail.outbox), 3)
        for message, address in zip(mail.outbox, addresses):
            self.assertEqual(message.to, [address])
            self.assertEqual(message.cc, [])
            self.assertEqual(message.bcc, [])
            serialized = message.message().as_string()
            for other in set(addresses) - {address} | {'old@example.test'}:
                self.assertNotIn(other, serialized)
        self.assertNotIn('@example.test', str(self.db['audit_events'].docs))

    @override_settings(NOTIFICATION_EMAIL_TO='obsolete@example.test',
                       NOTIFICATION_EMAIL_BACKUP_TO='legacy-backup@example.test')
    def test_distribution_uses_only_saved_address_and_reflects_updates(self):
        get_user_model().objects.create_user(username='supervisor', email='supervisor@example.test')
        self.service.email_client = EmailClient(['obsolete@example.test'])
        for address in ('configured@example.test', 'updated@example.test'):
            config = OperationalConfiguration.load()
            config.primary_email = address
            config.save()
            self.assertEqual(self.notify().estado, 'EXITO_TOTAL')
            self.assertEqual(mail.outbox[-1].to, [address])
        self.assertEqual(len(mail.outbox), 2)
        self.backup.send.assert_not_called()

    @override_settings(NOTIFICATION_EMAIL_TO='obsolete@example.test')
    def test_missing_or_empty_configuration_never_uses_environment(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    OperationalConfiguration.objects.all().delete()
                else:
                    config = OperationalConfiguration.load()
                    config.primary_email = ''
                    config.save()
                result = self.notify()
                self.assertEqual(result.estado, 'SIN_DESTINATARIOS_VALIDOS')
                self.assertEqual(result.motivo_omision, 'SIN_DESTINATARIOS_VALIDOS')
                self.assertEqual(result.intentos, [])
                self.primary.send.assert_not_called()
                self.backup.send.assert_not_called()

    def test_alert_levels_and_confirmed_content_are_preserved(self):
        self.service.email_client = EmailClient()
        for level, expected in ((1, 'BAJO'), (2, 'MEDIO'), (3, 'ALTO')):
            with self.subTest(level=level):
                from dataclasses import replace
                from backend.apps.alerts.domain import semaforo_desde_severidad
                self.alert = replace(self.alert, nivel_severidad=level,
                                     semaforo=semaforo_desde_severidad(level))
                # La fuente de verdad es la alerta confirmada en el repositorio.
                with patch.object(self.store, 'get_alert', return_value=self.alert):
                    self.assertTrue(self.notify().enviado)
                body = mail.outbox[-1].body
                self.assertIn(expected, body)
                self.assertIn(self.alert.box, body)
                self.assertNotIn('confidencial', body)


class EmailClientTests(SimpleTestCase):
    def setUp(self):
        self.payload = NotificationPayload('ALTO', 'riesgo_suicida', 'box-3', '2026-10-17T14:00:00Z')

    def test_local_mail_uses_separate_configured_recipients(self):
        self.assertTrue(EmailClient(["primary@example.test"]).send(self.payload).exitoso)
        self.assertEqual(mail.outbox[-1].to, ['primary@example.test'])
        self.assertTrue(EmailClient(backup=True).send(self.payload).exitoso)
        self.assertEqual(mail.outbox[-1].to, ['backup@example.test'])

    def test_not_configured_and_zero_messages_sent_are_failures(self):
        self.assertEqual(EmailClient([]).send(self.payload).error, 'NOTIFICATION_NOT_CONFIGURED')
        with patch('backend.apps.notifications.clients.send_mail', return_value=0):
            self.assertEqual(EmailClient(["primary@example.test"]).send(self.payload).error, 'NOTIFICATION_REJECTED')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_DELIVERY_TIMEOUT=2)
    def test_smtp_process_is_bounded_and_errors_are_codes(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('smtp', 2)) as run:
            self.assertEqual(EmailClient(["primary@example.test"]).send(self.payload).error, 'NOTIFICATION_TIMEOUT')
            self.assertEqual(run.call_args.kwargs['timeout'], 2)
            self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)
        for code, expected in [(0, None), (2, 'NOTIFICATION_TIMEOUT'), (3, 'NOTIFICATION_CONNECTION_FAILED'),
                               (4, 'NOTIFICATION_REJECTED'), (1, 'NOTIFICATION_INTERNAL_ERROR')]:
            with patch('subprocess.run', return_value=Mock(returncode=code)):
                self.assertEqual(EmailClient(["primary@example.test"]).send(self.payload).error, expected)


class LocalSMTPTests(TestCase):
    """Ejercita el proceso real SMTP contra un servidor local sin credenciales."""
    def test_rejected_supervisor_does_not_prevent_next_smtp_delivery(self):
        config = OperationalConfiguration.load()
        config.notification_mode = 'supervisores_activos'
        config.save()
        for name in ('primary', 'remaining'):
            get_user_model().objects.create_user(username=name, email=f'{name}@example.test')
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
                    self.assertEqual(result.estado, 'FALLO_PARCIAL')
                    self.assertEqual(result.intentos[0].error, 'NOTIFICATION_REJECTED')
                    self.assertEqual(len(result.intentos), 2)
                self.assertEqual(len(messages), 1)
                self.assertIn('primary@example.test', recipients[0])
                self.assertIn('remaining@example.test', recipients[1])
                self.assertNotIn(b'sensitive transcript', messages[0])
                self.assertEqual(len(db['audit_events'].docs), 3)
            finally:
                server.shutdown()
                thread.join(timeout=2)


class RecipientResolutionTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from backend.apps.operational.models import OperationalConfiguration, NotificationMode
        from .recipients import RecipientResolver

        self.users = get_user_model().objects
        self.config = OperationalConfiguration.load()
        self.config.notification_mode = NotificationMode.ACTIVE_SUPERVISORS
        self.config.primary_email = 'distribution@example.test'
        self.config.save()
        self.resolver = RecipientResolver()

    def create_user(self, username, **kwargs):
        return self.users.create_user(username=username, email=f'{username}@example.test', **kwargs)

    def test_only_enabled_supervisors_without_requiring_a_login(self):
        supervisor = self.create_user('supervisor')
        self.create_user('disabled', is_active=False)
        self.create_user('admin', role='admin')
        self.create_user('superuser', is_superuser=True)
        self.assertIsNone(supervisor.last_login)
        self.assertFalse(supervisor.refresh_sessions.exists())
        result = self.resolver.resolve()
        self.assertEqual(result.emails, (supervisor.email,))
        self.assertIsNone(result.reason)

    def test_each_resolution_reflects_email_role_and_status_changes(self):
        user = self.create_user('supervisor')
        self.assertEqual(self.resolver.resolve().emails, (user.email,))
        user.email = 'changed@example.test'
        user.save()
        self.assertEqual(self.resolver.resolve().emails, ('changed@example.test',))
        user.role = 'admin'
        user.save()
        self.assertEqual(self.resolver.resolve().emails, ())
        user.role = 'supervisor'
        user.is_active = False
        user.save()
        self.assertEqual(self.resolver.resolve().emails, ())
        user.is_active = True
        user.save()
        self.assertEqual(self.resolver.resolve().emails, ('changed@example.test',))

    def test_invalid_registered_emails_are_excluded(self):
        for index, email in enumerate(('', 'invalid', 'bad\r\n@example.test')):
            user = self.create_user(f'invalid{index}')
            # Simular datos heredados que no pasaron por la validación del modelo.
            self.users.filter(pk=user.pk).update(email=email)
        self.assertEqual(self.resolver.resolve().reason, 'SIN_DESTINATARIOS_VALIDOS')

    def test_duplicate_addresses_are_compared_without_case_or_spaces(self):
        from unittest.mock import patch
        with patch.object(self.users.__class__, 'filter') as query:
            query.return_value.order_by.return_value.values_list.return_value = [
                'supervisor@example.test', ' SUPERVISOR@example.test ', 'supervisor@example.test',
            ]
            self.assertEqual(self.resolver.resolve().emails, ('supervisor@example.test',))

    def test_preparation_resolves_again_and_empty_result_never_uses_backup(self):
        db = FakeDatabase()
        store = AlertsRepository(db)
        alert = alta_pendiente()
        store.insert_alert(alert)
        primary, backup = Mock(), Mock()
        primary.send.return_value = AttemptResult('email', True, 1)
        service = NotificationService(store=store, email_client=primary,
                                      backup_email_client=backup, enabled=True)
        payload = NotificationPayload('ALTO', 'riesgo_suicida', 'box-3', '10:00')
        user = self.create_user('supervisor')
        self.assertTrue(service.notify_alert(alert.alerta_id, payload).enviado)
        self.assertEqual(primary.send.call_args.kwargs["destinatarios"], [user.email])
        user.email = 'new@example.test'
        user.save()
        self.assertTrue(service.notify_alert(alert.alerta_id, payload).enviado)
        self.assertEqual(primary.send.call_args.kwargs["destinatarios"], [user.email])
        user.is_active = False
        user.save()
        primary.reset_mock()
        result = service.notify_alert(alert.alerta_id, payload)
        self.assertFalse(result.enviado)
        self.assertEqual(result.motivo_omision, 'SIN_DESTINATARIOS_VALIDOS')
        self.assertEqual(result.intentos, [])
        primary.send.assert_not_called()
        backup.send.assert_not_called()
        self.config.refresh_from_db()
        self.assertEqual(self.config.notification_mode, 'supervisores_activos')

    def test_mode_changes_are_used_on_the_next_resolution(self):
        self.create_user('supervisor')
        self.config.notification_mode = 'lista_distribucion'
        self.config.save()
        self.assertEqual(self.resolver.resolve().emails, ('distribution@example.test',))
