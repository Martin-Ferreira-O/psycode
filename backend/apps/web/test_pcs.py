"""Permisos reales de pantalla/API y CSRF de las operaciones con credenciales."""
from rest_framework.test import APITestCase, APIClient
from backend.apps.accounts.models import User
from backend.apps.capture.pc_registry import create_agent
from backend.apps.agenda.models import SmileRoom
from django.utils import timezone


class PCPanelTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin-pcs', email='admin-pcs@example.test', password='Synthetic-PCS-2026!', role='admin')
        self.supervisor = User.objects.create_user(username='supervisor-pcs', email='supervisor-pcs@example.test', password='Synthetic-PCS-2026!')
        self.room = SmileRoom.objects.create(source='smile', box='box-8', name='BOX 8', smile_box_id='77', last_seen_at=timezone.now())
        self.pc, _ = create_agent(name='PC sintético', box='box-3')

    def test_screen_and_all_endpoints_reject_supervisor_anonymous_and_inactive_admin(self):
        routes = [('/api/v1/pcs/panel', 'get'), ('/api/v1/pcs', 'get'), ('/api/v1/pcs/salas', 'get'), ('/api/v1/pcs/alta', 'post'), ('/api/v1/pcs', 'post')]
        routes += [(f'/api/v1/pcs/{self.pc.pk}/{action}', method) for action, method in
                   [('revocar', 'post'), ('renovar', 'post'), ('vinculacion', 'post'), ('cancelar-instalacion', 'post'), ('historial', 'get')]]
        for actor, expected in [(None, 401), (self.supervisor, 403)]:
            client = APIClient()
            if actor:
                client.force_authenticate(actor)
            for url, method in routes:
                with self.subTest(user=actor, url=url, method=method):
                    self.assertEqual(getattr(client, method)(url).status_code, expected)
        self.admin.is_active = False
        self.client.force_authenticate(self.admin)
        for url, method in routes:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403)

    def test_admin_gets_real_template_with_no_cache_and_csrf_cookie(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/v1/pcs/panel')
        self.assertContains(response, 'Crear nuevo PC')
        self.assertContains(response, '/static/web/js/pcs.js')
        self.assertContains(response, 'dialogoHistorialPC')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('csrftoken', response.cookies)
        self.assertEqual(self.client.get('/gestion-pcs').url, '/api/v1/pcs/panel')

    def test_browser_cookie_creates_pc_only_with_csrf_and_can_read_protected_panel(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get('/')
        csrf = client.cookies['csrftoken'].value
        login = client.post('/api/v1/auth/login', {'usuario': self.admin.username, 'password': 'Synthetic-PCS-2026!'},
                            format='json', HTTP_X_PSYCODE_BROWSER='1', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get('/api/v1/pcs/panel').status_code, 200)
        self.assertEqual(client.post('/api/v1/pcs/alta', {'name': 'PC inseguro'}, format='json').status_code, 403)
        good = client.post('/api/v1/pcs/alta', {'name': 'PC permitido', 'room_id': str(self.room.pk)}, format='json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(good.status_code, 201)
        self.assertNotIn('api_key', good.data['data'])
        self.assertRegex(good.data['data']['pairing_code'], r'^[A-HJ-NP-Z2-9]{5}$')
        self.assertIn('no-store', good['Cache-Control'])
