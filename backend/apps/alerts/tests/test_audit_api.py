from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase
from pymongo.errors import AutoReconnect
from rest_framework.test import APIClient

from backend.apps.accounts.models import User
from backend.apps.alerts.audit import AlertAudit
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.tests.test_persistence import FakeDatabase
from backend.common.errors import PersistenceUnavailable


class AuditApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = SimpleNamespace(is_authenticated=True, is_active=True,
                            is_superuser=False, role='admin')
        self.patch = patch('backend.apps.alerts.audit_api.AlertsRepository')
        self.repo = self.patch.start().return_value
        self.addCleanup(self.patch.stop)
        db = FakeDatabase()
        self.event = AlertAudit(lambda: db['audit_events']).record('alerts.register', 'success', alerta_id=str(uuid4()))
        self.repo.list_events.return_value = ([dict(self.event, email='private@example.com')], 1)

    def test_permissions(self):
        self.assertEqual(self.client.get('/api/v1/audit-events').status_code, 401)
        for role, active, expected in [('unknown', True, 403), ('admin', False, 403),
                                       ('admin', True, 200), ('supervisor', True, 403)]:
            self.user.role, self.user.is_active = role, active
            self.client.force_authenticate(self.user)
            self.assertEqual(self.client.get('/api/v1/audit-events').status_code, expected)

    def test_filters_pagination_and_safe_projection(self):
        self.client.force_authenticate(self.user)
        params = {'alerta_id': self.event['alerta_id'], 'action': 'alerts.register',
                  'outcome': 'success', 'fecha_desde': '2026-01-01T00:00:00Z',
                  'fecha_hasta': '2026-12-31T23:59:59Z', 'limit': 10, 'offset': 20, 'order': 'desc'}
        response = self.client.get('/api/v1/audit-events', params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['limit'], 10)
        self.assertEqual(response.data['data']['offset'], 20)
        self.assertEqual(response.data['data']['total'], 1)
        self.assertNotIn('email', response.data['data']['items'][0])
        filters = self.repo.list_events.call_args.args[0]
        self.assertEqual(filters['alerta_id'], params['alerta_id'])
        self.assertEqual(filters['outcome'], 'success')
        self.assertIsNotNone(filters['fecha_desde'].tzinfo)

    def test_invalid_filters(self):
        self.client.force_authenticate(self.user)
        for query in ['limit=0', 'limit=101', 'offset=-1', 'alerta_id=no', 'action=auth.login',
                      'outcome=invalid', 'order=invalid', 'fecha_desde=no', 'email=private',
                      'limit=1&limit=2', 'fecha_desde=2026-12-01&fecha_hasta=2026-01-01']:
            response = self.client.get('/api/v1/audit-events?' + query)
            self.assertEqual(response.status_code, 400, query)
        self.repo.list_events.assert_not_called()

    def test_notification_summary_filter_and_historical_compatibility(self):
        metadata = dict(id=str(uuid4()), mode='supervisores_activos', phase='resumen',
                        reason='FALLO_PARCIAL', status='FALLO_PARCIAL', primary_successes=2,
                        primary_failures=1, backup_successes=1, backup_failures=0,
                        email='private@example.test')
        old = dict(self.event, action='notifications.send')
        new = dict(self.event, action='notifications.result', outcome='failure', notification=metadata)
        self.repo.list_events.return_value = ([old, new], 2)
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/v1/audit-events', {'action': 'notifications.result'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.repo.list_events.call_args.args[0]['action'], 'notifications.result')
        items = response.data['data']['items']
        self.assertIsNone(items[0]['notification'])
        self.assertEqual(items[1]['notification']['primary_failures'], 1)
        self.assertNotIn('email', items[1]['notification'])

    def test_unavailable_and_read_only(self):
        self.client.force_authenticate(self.user)
        self.repo.list_events.side_effect = PersistenceUnavailable()
        self.assertEqual(self.client.get('/api/v1/audit-events').status_code, 503)
        self.assertEqual(self.client.post('/api/v1/audit-events', {}).status_code, 405)


class AuditQueryTests(SimpleTestCase):
    def test_mongo_filters_and_stable_sort(self):
        repo = AlertsRepository()
        col = MagicMock()
        cursor = col.find.return_value.sort.return_value.skip.return_value.limit.return_value
        cursor.__iter__.return_value = iter([])
        col.count_documents.return_value = 4
        filters = {'alerta_id': str(uuid4()), 'action': 'notifications.send', 'outcome': 'failure',
                   'fecha_desde': 1, 'fecha_hasta': 2, 'order': 'asc', 'offset': 2, 'limit': 1}
        with patch.object(repo, '_events', return_value=col):
            self.assertEqual(repo.list_events(filters), ([], 4))
        query = {'alerta_id': filters['alerta_id'], 'action': 'notifications.send', 'outcome': 'failure',
                 'timestamp': {'$gte': 1, '$lte': 2}}
        col.find.assert_called_once_with(query, {'_id': 0})
        col.count_documents.assert_called_once_with(query)
        col.find.return_value.sort.assert_called_once_with([('timestamp', 1), ('event_id', 1)])
        col.find.return_value.sort.return_value.skip.assert_called_once_with(2)
        col.find.return_value.sort.return_value.skip.return_value.limit.assert_called_once_with(1)
        with patch.object(repo, '_events', side_effect=AutoReconnect('secret')):
            with self.assertRaises(PersistenceUnavailable):
                repo.list_events(filters)

class AuditActorResolutionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_superuser=False,
            role='admin',
        )
        self.client.force_authenticate(self.admin)

        repo_patch = patch('backend.apps.alerts.audit_api.AlertsRepository')
        self.repo = repo_patch.start().return_value
        self.addCleanup(repo_patch.stop)

        db = FakeDatabase()
        self.event = AlertAudit(
            lambda: db['audit_events']
        ).record(
            'alerts.register',
            'success',
            alerta_id=str(uuid4()),
        )

    def make_event(self, actor_id):
        event = dict(
            self.event,
            event_id=str(uuid4()),
            actor_id=None if actor_id is None else str(actor_id),
        )
        event.pop('actor', None)
        return event

    def test_existing_user_returns_username_and_uuid(self):
        user = User.objects.create_user(
            username='profesional',
            email='profesional@example.test',
            password='TestPassword123!',
        )

        self.repo.list_events.return_value = (
            [self.make_event(user.id)],
            1,
        )

        response = self.client.get('/api/v1/audit-events')

        self.assertEqual(response.status_code, 200)
        actor = response.data['data']['items'][0]

        self.assertEqual(actor['actor'], 'profesional')
        self.assertEqual(str(actor['actor_id']), str(user.id))

    def test_deleted_user_preserves_original_identity(self):
        user = User.objects.create_user(
            username='profesional',
            email='profesional@example.test',
            password='TestPassword123!',
        )
        original_id = user.id
        user.delete()

        User.objects.create_user(
            username='profesional',
            email='nuevo@example.test',
            password='TestPassword123!',
        )

        self.repo.list_events.return_value = (
            [self.make_event(original_id)],
            1,
        )

        response = self.client.get('/api/v1/audit-events')

        self.assertEqual(response.status_code, 200)
        actor = response.data['data']['items'][0]

        self.assertEqual(
            actor['actor'],
            f'Usuario ({original_id})',
        )
        self.assertEqual(str(actor['actor_id']), str(original_id))

    def test_system_event_requires_no_user_query(self):
        self.repo.list_events.return_value = (
            [self.make_event(None)],
            1,
        )

        with self.assertNumQueries(0):
            response = self.client.get('/api/v1/audit-events')

        self.assertEqual(response.status_code, 200)
        actor = response.data['data']['items'][0]

        self.assertEqual(actor['actor'], 'Sistema')
        self.assertIsNone(actor['actor_id'])

    def test_multiple_events_use_single_user_query(self):
        first = User.objects.create_user(
            username='usuario_uno',
            email='uno@example.test',
            password='TestPassword123!',
        )
        second = User.objects.create_user(
            username='usuario_dos',
            email='dos@example.test',
            password='TestPassword123!',
        )

        events = [
            self.make_event(first.id),
            self.make_event(second.id),
            self.make_event(first.id),
            self.make_event(None),
        ]

        self.repo.list_events.return_value = (events, len(events))

        with self.assertNumQueries(1):
            response = self.client.get('/api/v1/audit-events')

        self.assertEqual(response.status_code, 200)

        actors = [
            item['actor']
            for item in response.data['data']['items']
        ]

        self.assertEqual(
            actors,
            ['usuario_uno', 'usuario_dos', 'usuario_uno', 'Sistema'],
        )