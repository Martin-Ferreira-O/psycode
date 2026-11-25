from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core import signing
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from backend.apps.accounts.models import User
from .models import FragmentJob, StorageCleanupRun
from .storage_views import SALT
from .test_ingestion import IngestionFixtures


class StorageApiTests(IngestionFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username='admin-storage', email='admin@storage.test', password='Synthetic-2026!', role='admin')
        self.supervisor = User.objects.create_user(username='supervisor-storage', email='supervisor@storage.test', password='Synthetic-2026!')
        self.api = APIClient()
        self.override = override_settings(CAPTURE_FRAGMENT_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def auth(self, user=None):
        self.api.force_authenticate(user=user or self.admin)

    def test_all_routes_reject_anonymous_supervisor_and_inactive_admin(self):
        routes = [('/api/v1/almacenamiento/panel', 'get'), ('/api/v1/almacenamiento', 'get'),
                  ('/api/v1/almacenamiento/vista-previa', 'post'), ('/api/v1/almacenamiento/liberar', 'post')]
        for user, expected in [(None, 401), (self.supervisor, 403)]:
            self.api = APIClient()
            if user:
                self.api.force_authenticate(user=user)
            for url, method in routes:
                self.assertEqual(getattr(self.api, method)(url).status_code, expected)
        self.admin.is_active = False
        self.api.force_authenticate(user=self.admin)
        for url, method in routes:
            self.assertEqual(getattr(self.api, method)(url).status_code, 403)

    def test_admin_gets_panel_and_uncached_metadata_without_file_keys(self):
        self.auth()
        response = self.api.get('/api/v1/almacenamiento/panel')
        self.assertContains(response, 'Almacenamiento del servidor')
        response = self.api.get('/api/v1/almacenamiento')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('candidates', response.data['data'])
        self.assertIn('encryption', response.data['data'])
        self.assertNotIn(str(self.root), str(response.data))

    def test_signed_preview_cleanup_and_replay_are_safe(self):
        self.auth()
        self.receive()
        FragmentJob.objects.update(state=FragmentJob.State.COMPLETED)
        before = self.api.post('/api/v1/almacenamiento/vista-previa', {}, format='json')
        self.assertEqual(before.status_code, 200)
        self.assertEqual(len(self.blobs()), 1)
        preview = before.data['data']
        self.assertEqual(preview['preview_files'], 1)
        with patch('backend.apps.capture.storage_views.flush_storage_audit'):
            result = self.api.post('/api/v1/almacenamiento/liberar', {'preview_token': preview['preview_token']}, format='json')
            self.assertEqual(result.status_code, 200, result.data)
            self.assertEqual(result.data['data']['freed_bytes'], FragmentJob.objects.get().size)
            repeated = self.api.post('/api/v1/almacenamiento/liberar', {'preview_token': preview['preview_token']}, format='json')
            self.assertEqual(repeated.data['data']['freed_bytes'], 0)
        self.assertEqual(self.blobs(), [])
        self.assertTrue(StorageCleanupRun.objects.filter(source='manual', actor_id=self.admin.pk).exists())

    def test_requires_current_preview_bound_to_same_actor(self):
        self.auth()
        self.assertEqual(self.api.post('/api/v1/almacenamiento/liberar', {}, format='json').status_code, 400)
        for token in ['forged', signing.dumps({'actor': str(self.supervisor.pk), 'files': []}, salt=SALT)]:
            self.assertEqual(self.api.post('/api/v1/almacenamiento/liberar', {'preview_token': token}, format='json').status_code, 409)
        token = signing.dumps({'actor': str(self.admin.pk), 'files': []}, salt=SALT)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 301):
            self.assertEqual(self.api.post('/api/v1/almacenamiento/liberar', {'preview_token': token}, format='json').status_code, 409)
        self.assertEqual(StorageCleanupRun.objects.count(), 0)

    def test_permission_change_after_preview_is_rechecked(self):
        self.auth()
        preview = self.api.post('/api/v1/almacenamiento/vista-previa', {}, format='json').data['data']
        self.api.force_authenticate(user=self.supervisor)
        result = self.api.post('/api/v1/almacenamiento/liberar', {'preview_token': preview['preview_token']}, format='json')
        self.assertEqual(result.status_code, 403)
        self.assertEqual(StorageCleanupRun.objects.count(), 0)

    def test_cookie_post_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get('/')
        csrf = client.cookies['csrftoken'].value
        result = client.post('/api/v1/auth/login', {'usuario': self.admin.username, 'password': 'Synthetic-2026!'}, format='json', HTTP_X_PSYCODE_BROWSER='1', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(client.post('/api/v1/almacenamiento/vista-previa', {}, format='json').status_code, 403)

    def test_browser_cookie_accesses_protected_html_panel(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get('/')
        csrf = client.cookies['csrftoken'].value
        response = client.post('/api/v1/auth/login', {'usuario': self.admin.username, 'password': 'Synthetic-2026!'},
                               format='json', HTTP_X_PSYCODE_BROWSER='1', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.cookies['psycode_access']['path'], '/api/v1/')
        self.assertEqual(client.get('/api/v1/almacenamiento/panel').status_code, 200)
