"""Contrato de vinculación y salas dinámicas, sin secretos ni servicios reales."""
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework.exceptions import AuthenticationFailed

from backend.apps.accounts.models import User, AuthRateLimit
from .authentication import authenticate_agent_header
from .models import AgentRegistration, PCPairingCode
from backend.apps.agenda.models import SmileRoom
from .pc_registry import create_agent
from .pairing import issue_pairing_code
from .websocket import RemoteControl
from uuid import uuid4


class PairingTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='pair-admin', email='pair@example.test', password='Synthetic-only-2026!', role='admin')
        self.client.force_authenticate(self.admin)
        self.exchange = APIClient()
        self.url = '/api/v1/internal/pcs/vincular'
        self.room = SmileRoom.objects.create(source='smile', box='box-8', name='BOX DE ATENCIÓN 8', smile_box_id='77', last_seen_at=timezone.now())

    def enroll(self, name='Box 8'):
        response = self.client.post('/api/v1/pcs/alta', {'name': name, 'room_id': str(self.room.pk)}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['data']

    def redeem(self, code, **kwargs):
        return self.exchange.post(self.url, {'code': code}, format='json', secure=True, **kwargs)

    def test_code_is_short_hashed_expiring_and_no_machine_secret_is_exposed_to_admin(self):
        data = self.enroll()
        self.assertEqual(data['box'], 'box-8')
        self.assertRegex(data['pairing_code'], r'^[A-HJ-NP-Z2-9]{5}$')
        self.assertNotIn('api_key', data)
        grant = PCPairingCode.objects.get()
        self.assertNotEqual(grant.code_hash, data['pairing_code'])
        self.assertEqual(len(grant.code_hash), 64)
        self.assertLessEqual((grant.expires_at - timezone.now()).total_seconds(), 300)
        listed = self.client.get('/api/v1/pcs').data['data'][0]
        self.assertEqual(listed['credential_state'], 'pending_pairing')
        self.assertTrue(listed['initial_installation'])
        self.assertEqual(listed['installation_expires_at'], grant.expires_at)
        self.assertNotIn(data['pairing_code'], str(listed))
        self.assertFalse(AgentRegistration.objects.get().is_active)

    def test_redeem_once_generates_authenticating_key_and_preserves_identity(self):
        data = self.enroll()
        response = self.redeem(data['pairing_code'])
        self.assertEqual(response.status_code, 200, response.data)
        pc = response.data['data']
        identity = authenticate_agent_header(('Agent ' + pc['api_key']).encode())
        self.assertEqual(identity.agent_id, data['agent_id'])
        self.assertEqual(identity.box, 'box-8')
        self.assertNotIn('api_key', self.client.get('/api/v1/pcs').data['data'][0])
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 400)
        self.assertIn('no-store', response['Cache-Control'])

    def test_expired_enrollment_releases_room_for_a_new_pc(self):
        data = self.enroll()
        PCPairingCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 400)
        self.assertEqual(self.client.post(f"/api/v1/pcs/{data['agent_id']}/vinculacion").status_code, 409)
        self.assertEqual(self.client.get('/api/v1/pcs').data['data'], [])
        self.assertFalse(AgentRegistration.objects.filter(pk=data['agent_id']).exists())
        self.assertFalse(PCPairingCode.objects.exists())
        room = next(row for row in self.client.get('/api/v1/pcs/salas').data['data'] if row['box'] == self.room.box)
        self.assertIsNone(room['existing_pc_id'])
        fresh = self.enroll()
        self.assertNotEqual(fresh['agent_id'], data['agent_id'])
        self.assertEqual(self.redeem('AAAAA').status_code, 400)
        self.assertEqual(self.redeem(fresh['pairing_code']).status_code, 200)

    def test_direct_enrollment_replaces_expired_draft_without_refresh(self):
        old = self.enroll()
        PCPairingCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        fresh = self.enroll()
        self.assertNotEqual(fresh['agent_id'], old['agent_id'])
        self.assertFalse(AgentRegistration.objects.filter(pk=old['agent_id']).exists())

    def test_cancelling_initial_installation_deletes_only_the_provisional_pc(self):
        data = self.enroll()
        path = f"/api/v1/pcs/{data['agent_id']}/cancelar-instalacion"
        self.assertEqual(self.client.post(path).status_code, 200)
        self.assertFalse(AgentRegistration.objects.filter(pk=data['agent_id']).exists())
        self.assertTrue(SmileRoom.objects.filter(pk=self.room.pk).exists())
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 400)

        installed = self.enroll()
        self.assertEqual(self.redeem(installed['pairing_code']).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/pcs/{installed['agent_id']}/cancelar-instalacion").status_code, 409)
        self.assertTrue(AgentRegistration.objects.get(pk=installed['agent_id']).is_active)

    def test_expired_reinstallation_keeps_the_existing_pc_and_credential(self):
        agent, key = create_agent(name='PC instalado', box=self.room.box)
        issue_pairing_code(agent.pk)
        PCPairingCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        listed = self.client.get('/api/v1/pcs').data['data'][0]
        self.assertEqual(listed['agent_id'], str(agent.pk))
        self.assertFalse(listed['initial_installation'])
        self.assertFalse(listed['installation_pending'])
        self.assertEqual(authenticate_agent_header(('Agent ' + key).encode()).registry_id, str(agent.pk))

    def test_revocation_cancels_pending_code(self):
        data = self.enroll()
        response = self.client.post(f"/api/v1/pcs/{data['agent_id']}/revocar", {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 400)

    def test_reenrollment_preserves_current_connection_until_code_is_redeemed(self):
        agent, key = create_agent(name='Sala anterior', box='box-19')
        agent.smile_room = SmileRoom.objects.create(source='smile', box='box-19', name='BOX 19', smile_box_id='91', last_seen_at=timezone.now())
        agent.save(update_fields=['smile_room'])
        control = RemoteControl(authenticate_agent_header(('Agent ' + key).encode()), uuid4())
        control.open()
        response = self.client.post(f'/api/v1/pcs/{agent.pk}/vinculacion', {}, format='json')
        self.assertEqual(response.status_code, 200)
        control.poll()
        fresh = self.redeem(response.data['data']['pairing_code'])
        with self.assertRaises(AuthenticationFailed):
            control.poll()
        self.assertEqual(fresh.data['data']['agent_id'], str(agent.pk))
        self.assertNotEqual(fresh.data['data']['api_key'], key)

    @override_settings(PC_PAIRING_IP_LIMIT=2, PC_PAIRING_GLOBAL_LIMIT=20)
    def test_rate_limit_ip_and_digest_only_counters(self):
        for _ in range(2):
            self.assertEqual(self.redeem('AAAAA', REMOTE_ADDR='192.0.2.7').status_code, 400)
        response = self.redeem('AAAAA', REMOTE_ADDR='192.0.2.7')
        self.assertEqual(response.status_code, 429)
        self.assertNotIn('192.0.2.7', str(list(AuthRateLimit.objects.values())))

    @override_settings(PC_PAIRING_IP_LIMIT=20, PC_PAIRING_GLOBAL_LIMIT=2)
    def test_distributed_ips_still_hit_global_limit(self):
        for index in range(2):
            self.assertEqual(self.redeem('AAAAA', REMOTE_ADDR=f'192.0.2.{index}').status_code, 400)
        self.assertEqual(self.redeem('BBBBB', REMOTE_ADDR='192.0.2.50').status_code, 429)

    def test_https_required_and_malformed_input_is_not_reflected(self):
        self.assertEqual(self.exchange.post(self.url, {'code': 'AAAAA'}, format='json').status_code, 400)
        response = self.redeem('<PRIVATE>')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('<PRIVATE>', str(response.data))

    def test_room_selection_is_required_and_name_does_not_choose_room(self):
        missing = self.client.post('/api/v1/pcs/alta', {'name': 'Box 91'}, format='json')
        self.assertEqual(missing.status_code, 400)
        first = self.enroll('Box 91')
        self.assertEqual(first['box'], 'box-8')
        again = self.client.post('/api/v1/pcs/alta', {'name': 'Sala confirmada', 'room_id': str(self.room.pk)}, format='json')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['data']['agent_id'], first['agent_id'])
        self.assertEqual(self.redeem(first['pairing_code']).status_code, 400)
        self.assertEqual(AgentRegistration.objects.count(), 1)
        legacy = self.client.post('/api/v1/pcs', {'name': 'Otro PC', 'box': first['box']}, format='json')
        self.assertEqual(legacy.status_code, 409)

    def test_verified_room_can_also_be_selected_by_box_from_the_installer_form(self):
        response = self.client.post('/api/v1/pcs/alta', {'name': 'Equipo consulta', 'box': self.room.box}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AgentRegistration.objects.get().smile_room_id, self.room.pk)

    def test_retired_room_blocks_exchange_but_optional_room_link_does_not(self):
        data = self.enroll()
        self.room.available = False; self.room.save()
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 400)
        self.room.available = True; self.room.save()
        AgentRegistration.objects.update(smile_room=None)
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 200)

    def test_admin_only_and_supervisor_is_rejected(self):
        data = self.enroll()
        supervisor = User.objects.create_user(username='pair-supervisor', email='pairsupervisor@example.test', role='supervisor')
        self.client.force_authenticate(supervisor)
        for path in ('/api/v1/pcs/alta', f"/api/v1/pcs/{data['agent_id']}/vinculacion"):
            self.assertEqual(self.client.post(path, {'name': 'Sala'}, format='json').status_code, 403)
        self.client = APIClient()
        self.assertEqual(self.client.post('/api/v1/pcs/alta', {}, format='json').status_code, 401)

    def test_key_generation_failure_does_not_consume_code(self):
        data = self.enroll()
        with patch('backend.apps.capture.pairing._generate_credential', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                from .pairing import redeem_pairing_code
                redeem_pairing_code(data['pairing_code'])
        self.assertIsNone(PCPairingCode.objects.get().consumed_at)
        self.assertEqual(self.redeem(data['pairing_code']).status_code, 200)


from concurrent.futures import ThreadPoolExecutor
from django.test import TransactionTestCase
from django.db import close_old_connections
from .pairing import create_pairable_agent, redeem_pairing_code
from backend.common.errors import ServiceError


class PairingConcurrencyTests(TransactionTestCase):
    def room(self, box, external):
        return SmileRoom.objects.create(source='smile', box=box, name=box, smile_box_id=external, last_seen_at=timezone.now())

    def worker(self, function, *args, **kwargs):
        close_old_connections()
        try:
            return function(*args, **kwargs)
        finally:
            close_old_connections()

    def test_two_concurrent_redemptions_have_only_one_winner(self):
        agent, code, _ = create_pairable_agent(name='Box 81', room_id=self.room('box-81','81').pk)
        def attempt():
            try:
                self.worker(redeem_pairing_code, code)
                return 'accepted'
            except ServiceError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ['accepted', 'PAIRING_INVALID'])
        self.assertIsNotNone(PCPairingCode.objects.get(agent=agent).consumed_at)

    def test_concurrent_room_allocation_does_not_create_duplicates(self):
        rooms = [self.room(f'box-{n+1}',str(n+1)) for n in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, create_pairable_agent, name=f'Sala concurrente {n}', room_id=rooms[n].pk) for n in range(2)]
            boxes = [future.result()[0].box for future in futures]
        self.assertEqual(len(set(boxes)), 2)

    def test_concurrent_preparations_cannot_install_different_credentials(self):
        agent, code, _ = create_pairable_agent(name='Box 82', room_id=self.room('box-82', '82').pk)
        def attempt(index):
            try:
                self.worker(redeem_pairing_code, code, installation_id=uuid4(), secret=str(index) * 43)
                return 'accepted'
            except ServiceError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertCountEqual(results, ['accepted', 'PAIRING_INVALID'])
        agent.refresh_from_db()
        self.assertFalse(agent.is_active)

    def test_concurrent_enrollment_for_same_room_reuses_single_identity(self):
        room=self.room('box-91','91')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.worker,create_pairable_agent,name=f'PC {n}',room_id=room.pk) for n in range(2)]
            ids=[future.result()[0].pk for future in futures]
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(AgentRegistration.objects.filter(box=room.box).count(),1)
