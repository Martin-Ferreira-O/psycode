"""Permisos reales de pantalla/API y CSRF de las operaciones con credenciales."""
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APITestCase, APIClient
from backend.apps.accounts.models import User
from backend.apps.capture.models import AgentRegistration, PCPairingCode
from backend.apps.capture.pc_registry import create_agent
from backend.apps.agenda.models import SmileRoom
from django.utils import timezone


INSTALLER_NAME = 'PsycodeAgent-Setup-1.2.1-x64.exe'
INSTALLER_URL = '/api/v1/pcs/instalador/windows-x64/1.2.1'
INSTALLER_BYTES = b'MZ instalador sintetico'
CHECKSUM_BYTES = f'{sha256(INSTALLER_BYTES).hexdigest()}  {INSTALLER_NAME}\n'.encode('ascii')


class PCPanelTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin-pcs', email='admin-pcs@example.test', password='Synthetic-PCS-2026!', role='admin')
        self.supervisor = User.objects.create_user(username='supervisor-pcs', email='supervisor-pcs@example.test', password='Synthetic-PCS-2026!')
        self.room = SmileRoom.objects.create(source='smile', box='box-8', name='BOX 8', smile_box_id='77', last_seen_at=timezone.now())
        self.pc, _ = create_agent(name='PC sintético', box='box-3')

    def publish_installer(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(PC_WINDOWS_INSTALLER_DIR=str(root)))
        release = root / '1.2.1'
        release.mkdir()
        (release / INSTALLER_NAME).write_bytes(INSTALLER_BYTES)
        (release / (INSTALLER_NAME + '.sha256')).write_bytes(CHECKSUM_BYTES)
        (root / 'current').symlink_to(release.name)
        return release

    def test_screen_and_all_endpoints_reject_supervisor_anonymous_and_inactive_admin(self):
        self.publish_installer()
        routes = [('/api/v1/pcs/panel', 'get'), ('/api/v1/pcs', 'get'), ('/api/v1/pcs/salas', 'get'), ('/api/v1/pcs/alta', 'post'), ('/api/v1/pcs', 'post'),
                  (INSTALLER_URL, 'get'), (INSTALLER_URL + '/sha256', 'get')]
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

    @override_settings(PC_WINDOWS_INSTALLER_DIR='')
    def test_admin_can_use_panel_without_a_published_installer(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/v1/pcs/panel')
        self.assertContains(response, 'Crear nuevo PC')
        self.assertContains(response, '/static/web/js/pcs.js')
        self.assertContains(response, 'dialogoHistorialPC')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('csrftoken', response.cookies)
        self.assertContains(response, 'El instalador de Windows x64 no está disponible.', count=2)
        self.assertNotContains(response, 'Descargar instalador para Windows x64')
        self.assertContains(self.client.get(INSTALLER_URL), 'no está disponible', status_code=404)
        self.assertEqual(self.client.get('/gestion-pcs').url, '/api/v1/pcs/panel')

    def test_browser_can_download_before_and_after_enrollment_and_still_pair(self):
        self.publish_installer()
        client = APIClient(enforce_csrf_checks=True)
        client.get('/', secure=True)
        csrf = client.cookies['csrftoken'].value
        login = client.post('/api/v1/auth/login', {'usuario': self.admin.username, 'password': 'Synthetic-PCS-2026!'},
                            format='json', secure=True, HTTP_ORIGIN='https://testserver', HTTP_X_PSYCODE_BROWSER='1', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(login.status_code, 200)
        panel = client.get('/api/v1/pcs/panel', secure=True)
        self.assertContains(panel, 'Descargar instalador para Windows x64', count=2)
        self.assertContains(panel, 'Versión 1.2.1', count=2)
        self.assertContains(panel, f'href="{INSTALLER_URL}"', count=2)
        for url, filename, expected in [(INSTALLER_URL, INSTALLER_NAME, INSTALLER_BYTES),
                                        (INSTALLER_URL + '/sha256', INSTALLER_NAME + '.sha256', CHECKSUM_BYTES)]:
            response = client.get(url, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Disposition'], f'attachment; filename="{filename}"')
            self.assertIn('no-store', response['Cache-Control'])
            self.assertEqual(b''.join(response.streaming_content), expected)
        self.assertFalse(PCPairingCode.objects.exists())
        self.assertEqual(AgentRegistration.objects.count(), 1)
        self.assertEqual(client.post('/api/v1/pcs/alta', {'name': 'PC inseguro'}, format='json').status_code, 403)
        good = client.post('/api/v1/pcs/alta', {'name': 'PC permitido', 'room_id': str(self.room.pk)}, format='json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(good.status_code, 201)
        self.assertNotIn('api_key', good.data['data'])
        self.assertRegex(good.data['data']['pairing_code'], r'^[A-HJ-NP-Z2-9]{5}$')
        self.assertIn('no-store', good['Cache-Control'])

        enrollment = good.data['data']
        grant = PCPairingCode.objects.get(agent_id=enrollment['agent_id'])
        self.assertEqual(b''.join(client.get(INSTALLER_URL, secure=True).streaming_content), INSTALLER_BYTES)
        self.assertEqual(PCPairingCode.objects.get(agent_id=grant.agent_id).code_hash, grant.code_hash)
        self.assertFalse(AgentRegistration.objects.get(pk=grant.agent_id).is_active)

        machine = APIClient()
        payload = {'code': enrollment['pairing_code'], 'installation_id': str(uuid4()), 'secret': 'x' * 43}
        prepared = machine.post('/api/v1/internal/pcs/vincular', payload, format='json', secure=True)
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(prepared.data['data']['agent_id'], enrollment['agent_id'])
        confirmed = machine.post('/api/v1/internal/pcs/confirmar', {'installation_id': payload['installation_id']},
                                 format='json', secure=True, HTTP_AUTHORIZATION='Agent ' + prepared.data['data']['api_key'])
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(AgentRegistration.objects.get(pk=grant.agent_id).is_active)

    def test_missing_checksum_does_not_block_a_new_enrollment_after_expiry(self):
        release = self.publish_installer()
        (release / (INSTALLER_NAME + '.sha256')).unlink()
        self.client.force_authenticate(self.admin)
        self.assertContains(self.client.get('/api/v1/pcs/panel'), 'El instalador de Windows x64 no está disponible.')
        self.assertEqual(self.client.get(INSTALLER_URL).status_code, 404)

        response = self.client.post('/api/v1/pcs/alta', {'name': 'PC nuevo', 'room_id': str(self.room.pk)}, format='json')
        self.assertEqual(response.status_code, 201)
        pc_id = response.data['data']['agent_id']
        PCPairingCode.objects.filter(agent_id=pc_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        replacement = self.client.post('/api/v1/pcs/alta', {'name': 'PC nuevo', 'room_id': str(self.room.pk)}, format='json')
        self.assertEqual(replacement.status_code, 201)
        self.assertNotEqual(replacement.data['data']['agent_id'], pc_id)
        self.assertFalse(AgentRegistration.objects.filter(pk=pc_id).exists())
        self.assertEqual(AgentRegistration.objects.count(), 2)

    def test_replacing_current_switches_the_version_without_serving_stale_links(self):
        release = self.publish_installer()
        previous = release.with_name('1.2.0')
        previous.mkdir()
        name = 'PsycodeAgent-Setup-1.2.0-x64.exe'
        binary = b'MZ version anterior'
        (previous / name).write_bytes(binary)
        (previous / (name + '.sha256')).write_text(f'{sha256(binary).hexdigest()}  {name}\n', encoding='ascii')
        current = release.parent / 'current'
        next_link = current.with_name('current.next')
        next_link.symlink_to(previous.name)
        next_link.replace(current)

        self.client.force_authenticate(self.admin)
        self.assertContains(self.client.get('/api/v1/pcs/panel'), 'Versión 1.2.0', count=2)
        self.assertEqual(self.client.get(INSTALLER_URL).status_code, 404)
        self.assertEqual(b''.join(self.client.get(INSTALLER_URL.replace('1.2.1', '1.2.0')).streaming_content), binary)
