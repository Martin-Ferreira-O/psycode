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


import os
import subprocess

def _link_directory(link_path: Path, target_name: str):
    try:
        link_path.symlink_to(target_name)
    except OSError as exc:
        if os.name == 'nt' and getattr(exc, 'winerror', None) in {1314, 5}:
            target_dir = link_path.parent / target_name
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link_path), str(target_dir)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            raise

def _replace_directory_link(next_link: Path, current: Path):
    try:
        next_link.replace(current)
    except PermissionError:
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'rmdir', str(current)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            next_link.replace(current)
        else:
            raise


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
        _link_directory(root / 'current', release.name)
        return release

    def test_screen_and_all_endpoints_reject_supervisor_anonymous_and_inactive_admin(self):
        self.publish_installer()
        routes = [('/api/v1/pcs/panel', 'get'), ('/api/v1/pcs', 'get'), ('/api/v1/pcs/salas', 'get'), ('/api/v1/pcs/alta', 'post'), ('/api/v1/pcs', 'post'),
                  (INSTALLER_URL, 'get'), (INSTALLER_URL + '/sha256', 'get')]
        routes += [(f'/api/v1/pcs/{self.pc.pk}/{action}', method) for action, method in
                   [('nombre', 'post'), ('revocar', 'post'), ('renovar', 'post'), ('vinculacion', 'post'), ('cancelar-instalacion', 'post'), ('historial', 'get')]]
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
        self.assertContains(response, '/static/web/react/app.js')
        self.assertEqual(response.context["config"]["page"], "pcs")
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('csrftoken', response.cookies)
        self.assertIsNone(response.context["config"]["installerVersion"])
        self.assertIsNone(response.context["config"]["installerUrl"])
        self.assertIsNone(response.context["config"]["checksumUrl"])
        self.assertContains(self.client.get(INSTALLER_URL), 'no está disponible', status_code=404)
        self.assertEqual(self.client.get('/gestion-pcs').url, '/api/v1/pcs/panel')

    def test_admin_can_rename_pc_without_changing_registration(self):
        self.client.force_authenticate(self.admin)
        self.pc.smile_room = self.room
        self.pc.box = self.room.box
        self.pc.save(update_fields=['smile_room', 'box'])
        registration = AgentRegistration.objects.filter(pk=self.pc.pk)
        before = registration.values().get()

        response = self.client.post(f'/api/v1/pcs/{self.pc.pk}/nombre', {'name': '  PC Recepción  '}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], {'agent_id': str(self.pc.pk), 'name': 'PC Recepción'})
        after = registration.values().get()
        self.assertEqual(after.pop('name'), 'PC Recepción')
        self.assertGreaterEqual(after.pop('updated_at'), before.pop('updated_at'))
        before.pop('name')
        self.assertEqual(after, before)
        listed = self.client.get('/api/v1/pcs').data['data']
        self.assertEqual(next(pc['name'] for pc in listed if pc['agent_id'] == str(self.pc.pk)), 'PC Recepción')

    def test_rename_validates_name_and_requires_existing_pc(self):
        self.client.force_authenticate(self.admin)
        url = f'/api/v1/pcs/{self.pc.pk}/nombre'
        for body in [{}, {'name': '   '}, {'name': 'x' * 101}, {'name': 123}, {'name': 'Otro', 'box': 'box-4'}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post(url, body, format='json').status_code, 400)
        original = self.pc.name
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.name, original)
        self.assertEqual(self.client.post(f'/api/v1/pcs/{uuid4()}/nombre', {'name': 'Otro'}, format='json').status_code, 404)

    def test_browser_can_download_before_and_after_enrollment_and_still_pair(self):
        self.publish_installer()
        client = APIClient(enforce_csrf_checks=True)
        client.get('/', secure=True)
        csrf = client.cookies['csrftoken'].value
        login = client.post('/api/v1/auth/login', {'usuario': self.admin.username, 'password': 'Synthetic-PCS-2026!'},
                            format='json', secure=True, HTTP_ORIGIN='https://testserver', HTTP_X_PSYCODE_BROWSER='1', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(login.status_code, 200)
        panel = client.get('/api/v1/pcs/panel', secure=True)
        config = panel.context["config"]
        self.assertEqual(config["installerVersion"], "1.2.1")
        self.assertEqual(config["installerUrl"], INSTALLER_URL)
        self.assertEqual(config["checksumUrl"], f"{INSTALLER_URL}/sha256")
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
        self.assertEqual(client.post(f'/api/v1/pcs/{self.pc.pk}/nombre', {'name': 'PC inseguro'}, format='json').status_code, 403)
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
        self.assertIsNone(self.client.get('/api/v1/pcs/panel').context["config"]["installerVersion"])
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
        _link_directory(next_link, previous.name)
        _replace_directory_link(next_link, current)

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/v1/pcs/panel').context["config"]["installerVersion"], "1.2.0")
        self.assertEqual(self.client.get(INSTALLER_URL).status_code, 404)
        self.assertEqual(b''.join(self.client.get(INSTALLER_URL.replace('1.2.1', '1.2.0')).streaming_content), binary)
