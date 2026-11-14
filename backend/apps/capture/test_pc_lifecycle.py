"""Regresiones de operación permanente: red, identidad antigua y activación durable."""
from datetime import timedelta
import hashlib
from uuid import uuid4

from backend.apps.operational.models import OperationalConfiguration
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase, APIClient

from backend.apps.accounts.models import User
from .authentication import authenticate_agent_header
from .models import AgentRegistration, PCPairingCode, AgentConnectivityEvent
from .pairing import issue_pairing_code
from .websocket import RemoteControl

OLD = 'installed-pc.' + 's' * 43
AGENTS = {'installed-pc': {'box': 'box-3', 'token_sha256': hashlib.sha256(OLD.encode()).hexdigest()}}
SOURCES = {'smile': {'collector_id': 'installed-pc', 'boxes': ['box-3', 'box-4', 'box-5', 'box-6', 'box-7']}}


@override_settings(CAPTURE_AGENTS=AGENTS,  PC_PAIRING_IP_LIMIT=100)
class PermanentPCTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        config = OperationalConfiguration.load()
        config.smile_legacy_sources = SOURCES
        config.save(update_fields=["smile_legacy_sources"])

    def setUp(self):
        self.admin = User.objects.create_user(username='pcs-lifecycle', email='pcs-lifecycle@example.test', role='admin')
        self.client.force_authenticate(self.admin)
        self.machine = APIClient()

    def prepare(self, code, installation=None, secret='x' * 43):
        installation = installation or uuid4()
        response = self.machine.post('/api/v1/internal/pcs/vincular', {
            'code': code, 'installation_id': str(installation), 'secret': secret,
        }, format='json', secure=True)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def confirm(self, data):
        return self.machine.post('/api/v1/internal/pcs/confirmar', {'installation_id': data['installation_id']},
                                 format='json', secure=True, HTTP_AUTHORIZATION='Agent ' + data['api_key'])

    def test_existing_installation_is_visible_without_catalogue_or_reconfiguration(self):
        first = self.client.get('/api/v1/pcs').data['data']
        self.assertEqual(len(first), 1)
        pc = AgentRegistration.objects.get(pk=first[0]['agent_id'])
        self.assertTrue(pc.legacy_enabled)
        self.assertEqual(pc.token_sha256, AGENTS['installed-pc']['token_sha256'])
        identity = authenticate_agent_header(('Agent ' + OLD).encode())
        self.assertEqual(identity.agent_id, 'installed-pc')
        self.assertEqual(identity.registry_id, str(pc.pk))
        control = RemoteControl(identity, uuid4())
        control.open(); control.register_hello('synthetic-1')
        listed = self.client.get('/api/v1/pcs').data['data'][0]
        self.assertEqual(listed['connection'], 'online')
        self.assertEqual(listed['version'], 'synthetic-1')
        self.assertEqual(listed['agent_id'], first[0]['agent_id'])
        self.assertNotIn(OLD, str(listed))
        control.close()

    def test_configured_boxes_can_be_installed_without_smile_catalogue(self):
        rooms = self.client.get('/api/v1/pcs/salas').data['data']
        self.assertEqual({r['box'] for r in rooms}, set(SOURCES['smile']['boxes']))
        self.assertTrue(all(r['room_id'] is None and r['smile_box_id'] is None for r in rooms))
        result = self.client.post('/api/v1/pcs/alta', {'name': 'Consulta 4', 'box': 'box-4'}, format='json')
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.client.post('/api/v1/pcs/alta', {'name': 'Intruso', 'box': 'box-99'}, format='json').status_code, 400)
        data = self.prepare(result.data['data']['pairing_code'])
        self.assertEqual(self.confirm(data).status_code, 200)

    def test_prepare_and_lost_responses_do_not_revoke_until_confirmation(self):
        identity = authenticate_agent_header(('Agent ' + OLD).encode())
        control = RemoteControl(identity, uuid4()); control.open()
        agent, code, _ = issue_pairing_code(identity.registry_id)
        control.poll()
        data = self.prepare(code)
        self.assertNotEqual(data['api_key'], f"{agent.pk}." + 'x' * 43)  # Clave generada por el servidor.
        retried = self.prepare(code, installation=data['installation_id'])
        self.assertEqual(retried, data)
        self.assertEqual(authenticate_agent_header(('Agent ' + OLD).encode()).agent_id, 'installed-pc')
        control.poll()
        with self.assertRaises(AuthenticationFailed):
            authenticate_agent_header(('Agent ' + data['api_key']).encode())
        self.assertEqual(self.confirm(data).status_code, 200)
        with self.assertRaises(AuthenticationFailed):
            control.poll()
        with self.assertRaises(AuthenticationFailed):
            authenticate_agent_header(('Agent ' + OLD).encode())
        self.assertEqual(authenticate_agent_header(('Agent ' + data['api_key']).encode()).agent_id, str(agent.pk))
        PCPairingCode.objects.filter(agent=agent).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.confirm(data).status_code, 200)  # Confirmación perdida, aun después del vencimiento.
        agent.refresh_from_db()
        self.assertNotIn(data['api_key'], str(agent.__dict__))
        self.assertNotIn(data['api_key'], str(PCPairingCode.objects.get(agent=agent).__dict__))

    def test_consumed_code_is_bound_to_the_original_installation(self):
        identity = authenticate_agent_header(('Agent ' + OLD).encode())
        agent, code, _ = issue_pairing_code(identity.registry_id)
        data = self.prepare(code)
        rejected = self.machine.post('/api/v1/internal/pcs/vincular', {
            'code': code, 'installation_id': str(uuid4()), 'secret': 'z' * 43,
        }, format='json', secure=True)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.confirm(data).status_code, 200)

    def test_revocation_cancels_prepared_credentials_and_is_not_undone_by_sync(self):
        identity = authenticate_agent_header(('Agent ' + OLD).encode())
        _, code, _ = issue_pairing_code(identity.registry_id)
        data = self.prepare(code)
        self.assertEqual(self.client.post(f'/api/v1/pcs/{identity.registry_id}/revocar').status_code, 200)
        self.assertEqual(self.confirm(data).status_code, 400)
        self.client.get('/api/v1/pcs')
        with self.assertRaises(AuthenticationFailed):
            authenticate_agent_header(('Agent ' + OLD).encode())

    def test_cancelling_installation_keeps_the_current_credential_and_connection(self):
        identity = authenticate_agent_header(('Agent ' + OLD).encode())
        control = RemoteControl(identity, uuid4()); control.open()
        _, code, _ = issue_pairing_code(identity.registry_id)
        data = self.prepare(code)
        self.assertEqual(self.client.post(f'/api/v1/pcs/{identity.registry_id}/cancelar-instalacion').status_code, 200)
        self.assertEqual(self.confirm(data).status_code, 400)
        control.poll()
        control.close()

    def test_history_keeps_old_provenance_and_excludes_other_pc_in_same_box(self):
        identity = authenticate_agent_header(('Agent ' + OLD).encode())
        now = timezone.now()
        for agent_id in ['installed-pc', identity.registry_id, 'other-machine']:
            AgentConnectivityEvent.objects.create(agent_id=agent_id, event_id=uuid4(), box='box-3',
                session_id=None, kind='wss.disconnected', occurred_at=now, received_at=now,
                outage_id=uuid4(), duration_ms=None, cause='UNKNOWN')
        history = self.client.get(f'/api/v1/pcs/{identity.registry_id}/historial').data['data']
        self.assertEqual(history['pagination']['total'], 2)
        self.assertEqual(AgentConnectivityEvent.objects.filter(agent_id='installed-pc').count(), 1)

    @override_settings(CAPTURE_AGENTS={})
    def test_empty_installation_offers_initial_boxes_without_creating_or_authorizing_pcs(self):
        OperationalConfiguration.objects.update(smile_legacy_sources={})
        from backend.common.boxes import known_boxes
        self.assertEqual(known_boxes(), [])
        rooms = self.client.get('/api/v1/pcs/salas').data['data']
        self.assertEqual([row['box'] for row in rooms], ['box-3', 'box-4', 'box-5', 'box-6', 'box-7'])
        self.assertFalse(AgentRegistration.objects.exists())
        self.assertEqual(known_boxes(), [])
        created = self.client.post('/api/v1/pcs/alta', {'name': 'Consulta 5', 'box': 'box-5'}, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(AgentRegistration.objects.get().box, 'box-5')

    @override_settings(CAPTURE_AGENTS={})
    def test_two_existing_pcs_do_not_hide_other_initial_boxes(self):
        OperationalConfiguration.objects.update(smile_legacy_sources={})
        for number in (3, 4):
            AgentRegistration.objects.create(name=f'PC {number}', box=f'box-{number}', token_sha256='a' * 64)
        rooms = self.client.get('/api/v1/pcs/salas').data['data']
        free = [row['box'] for row in rooms if row['pc_id'] is None]
        self.assertEqual(free, ['box-5', 'box-6', 'box-7'])
