import io
import json
from datetime import datetime, timezone
from backend.apps.operational.models import OperationalConfiguration
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework.exceptions import AuthenticationFailed
from backend.apps.accounts.models import User
from backend.apps.capture.authentication import AgentIdentity, authenticate_agent_header, ensure_agent_identity_current
from backend.apps.capture.test_api import AGENTS, TOKEN
from backend.apps.capture.pairing import create_pairable_agent, redeem_pairing_code
from backend.apps.capture.pc_registry import create_agent
from backend.apps.capture.models import AgentRegistration
from backend.apps.capture.storage import FragmentError
from .catalogue import publish, source_scope
from .models import SmileRoom, AgendaCollection
from . import persistence
from .test_persistence import SOURCES, workbook
from .services import AgendaService

ROOMS = [dict(box='box-3', name='BOX DE ATENCIÓN 3', smile_box_id='77'),
         dict(box='box-18', name='BOX DE ATENCIÓN 18', smile_box_id='91')]

@override_settings( CAPTURE_AGENTS=AGENTS)
class CatalogueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        config = OperationalConfiguration.load()
        config.smile_legacy_sources = SOURCES
        config.save(update_fields=["smile_legacy_sources"])

    def setUp(self):
        self.identity = AgentIdentity('agent-3','box-3')

    def snapshot(self, rooms=None, operation=None, identity=None):
        identity = identity or self.identity
        operation = operation or persistence.issue(identity, 'smile')
        payload = dict(version='1.0', source='smile', collection_id=operation['collection_id'], rooms=ROOMS if rooms is None else rooms)
        return publish(identity, payload)

    def test_catalogue_scope_expands_only_after_explicit_binding_and_keeps_real_ids(self):
        result = self.snapshot()
        self.assertEqual(result['boxes'], ['box-3'])
        self.assertEqual(result['room_mapping'], {'box-3':'77'})
        room = SmileRoom.objects.get(box='box-18')
        pc, code, _ = create_pairable_agent(name='Un nombre libre', room_id=room.pk)
        self.assertEqual(pc.box, 'box-18')
        self.assertEqual(persistence.issue(self.identity, 'smile')['room_mapping'], {'box-3':'77','box-18':'91'})
        bound, key = redeem_pairing_code(code)
        self.assertEqual(authenticate_agent_header(('Agent '+key).encode()).box, 'box-18')
        with self.assertRaises(FragmentError): persistence.issue(AgentIdentity(str(bound.pk),'box-18',managed=True),'smile')

    def test_atomic_invalid_and_ambiguous_snapshots_preserve_previous_catalogue(self):
        self.snapshot()
        for rooms in ([], [ROOMS[0],ROOMS[0]], [{**ROOMS[0],'box':'box-99'}],
                      [{**ROOMS[0],'smile_box_id':'91'}], [{**ROOMS[0],'name':'BOX TELEMATICO 3'}]):
            with self.subTest(rooms=rooms), self.assertRaises(FragmentError): self.snapshot(rooms)
            self.assertEqual(SmileRoom.objects.filter(available=True).count(),2)
            self.assertEqual(SmileRoom.objects.get(box='box-3').smile_box_id,'77')

    def test_generation_is_server_ordered_idempotent_and_stale_cannot_restore_room(self):
        old = persistence.issue(self.identity,'smile')
        current = persistence.issue(self.identity,'smile')
        first = self.snapshot(operation=current)
        self.assertEqual(self.snapshot(operation=current),first)
        with self.assertRaises(FragmentError): self.snapshot([ROOMS[0]], operation=current)
        with self.assertRaises(FragmentError): self.snapshot(operation=old)
        self.snapshot([ROOMS[0]])
        self.assertFalse(SmileRoom.objects.get(box='box-18').available)

    def test_confirm_existing_pc_preserves_id_and_retires_legacy_http_and_active_socket_identity(self):
        legacy = authenticate_agent_header(('Agent '+TOKEN).encode())
        self.snapshot()
        old = AgentRegistration.objects.get(legacy_agent_id='agent-3')
        room = SmileRoom.objects.get(box='box-3')
        pc, code, _ = create_pairable_agent(name='PC confirmado', room_id=room.pk)
        self.assertEqual(old.pk,pc.pk)
        self.assertEqual(authenticate_agent_header(('Agent '+TOKEN).encode()).agent_id, 'agent-3')
        ensure_agent_identity_current(legacy)
        _, key = redeem_pairing_code(code)
        with self.assertRaises(AuthenticationFailed): authenticate_agent_header(('Agent '+TOKEN).encode())
        with self.assertRaises(AuthenticationFailed): ensure_agent_identity_current(legacy)
        replacement = authenticate_agent_header(('Agent '+key).encode())
        self.assertEqual(persistence.issue(replacement,'smile')['room_mapping'], {'box-3':'77'})
        self.assertEqual(AgentRegistration.objects.count(),1)

    def test_replacement_collector_can_replay_pending_original_collection_with_frozen_scope(self):
        old = persistence.issue(self.identity,'smile')
        raw = workbook()
        self.snapshot()
        room = SmileRoom.objects.get(box='box-3')
        _, code, _ = create_pairable_agent(name='PC nuevo',room_id=room.pk)
        _, key = redeem_pairing_code(code)
        replacement = authenticate_agent_header(('Agent '+key).encode())
        import hashlib
        metadata = dict(collection_id=old['collection_id'],source='smile',agenda_date='2026-10-27',
            obtained_at=datetime.now(timezone.utc).isoformat(),boxes=['box-3'],format_version='smile.excel.v1',
            checksum=hashlib.sha256(raw).hexdigest(),outcome='valid')
        self.assertTrue(persistence.receive(replacement,metadata,io.BytesIO(raw))[1])
        self.assertFalse(persistence.receive(replacement,metadata,io.BytesIO(raw))[1])

    def test_json_real_id_and_excel_header_must_match_room_without_overwriting_previous(self):
        op = self.snapshot()
        import hashlib
        raw = json.dumps([dict(smile_cita_id='synthetic',box=3,smile_box_id='77',fecha='2026-10-27',
             hora_inicio='09:00',duracion_minutos=60,estado='CONFIRMADA',codigo_estado='synthetic')]).encode()
        def metadata(operation, report, fmt):
            return dict(collection_id=operation['collection_id'],source='smile',agenda_date='2026-10-27',
                obtained_at=datetime.now(timezone.utc).isoformat(),boxes=['box-3'],format_version=fmt,
                checksum=hashlib.sha256(report).hexdigest(),outcome='valid')
        persistence.receive(self.identity,metadata(op,raw,'smile.json.v1'),io.BytesIO(raw))
        wrong = workbook('box-4')
        op = persistence.issue(self.identity,'smile')
        with self.assertRaises(FragmentError): persistence.receive(self.identity,metadata(op,wrong,'smile.excel.v1'),io.BytesIO(wrong))
        wrong = raw.replace(b'"77"',b'"8"')
        with self.assertRaises(FragmentError): persistence.receive(self.identity,metadata(op,wrong,'smile.json.v1'),io.BytesIO(wrong))
        self.assertEqual(len(persistence.refresh(AgendaService()).records),1)
        self.assertIsNone(AgendaCollection.objects.get(collection_id=op['collection_id']).received_at)

    def test_api_catalogue_requires_designated_collector_and_admin_listing_requires_admin(self):
        c=APIClient();path='/api/v2/internal/smile-room-catalogues'
        op=persistence.issue(self.identity,'smile')
        payload=dict(version='1.0',source='smile',collection_id=op['collection_id'],rooms=ROOMS)
        self.assertEqual(c.post(path,payload,format='json').status_code,401)
        c.credentials(HTTP_AUTHORIZATION='Agent '+TOKEN)
        self.assertEqual(c.post(path,payload,format='json').status_code,200)
        c.credentials()
        supervisor=User.objects.create_user(username='catalogue-supervisor',email='catalogue@example.test',role='supervisor')
        c.force_authenticate(supervisor)
        self.assertEqual(c.get('/api/v1/pcs/salas').status_code,403)
        supervisor.role='admin';supervisor.save();c.force_authenticate(supervisor)
        self.assertTrue({'box-3', 'box-18'} <= {row['box'] for row in c.get('/api/v1/pcs/salas').data['data']})

    def test_unavailable_room_denies_capture_even_with_clinical_fallback(self):
        from types import SimpleNamespace
        from backend.apps.operational.capture_authorization import CaptureAuthorizationService
        self.snapshot([ROOMS[0]])
        service = CaptureAuthorizationService(config_loader=lambda: SimpleNamespace(enabled_days=list(range(7)),open_time='00:00',close_time='23:59'))
        instant=datetime(2026,11,8,15,0,tzinfo=timezone.utc)
        self.assertTrue(service.evaluate_box('box-3',instant).authorized)
        SmileRoom.objects.filter(box='box-3').update(available=False)
        self.assertFalse(service.evaluate_box('box-3',instant).authorized)

    def test_pre_migration_pending_json_uses_original_legacy_scope(self):
        import hashlib
        from pathlib import Path
        old=persistence.issue(self.identity,'smile')
        AgendaCollection.objects.filter(collection_id=old['collection_id']).update(scope={})
        self.snapshot()
        raw=(Path(__file__).resolve().parents[3]/'contracts/smile-native-synthetic.json').read_bytes()
        metadata=dict(collection_id=old['collection_id'],source='smile',agenda_date='2026-10-27',
            obtained_at=datetime.now(timezone.utc).isoformat(),boxes=['box-3'],format_version='smile.json.v1',
            checksum=hashlib.sha256(raw).hexdigest(),outcome='valid')
        self.assertTrue(persistence.receive(self.identity,metadata,io.BytesIO(raw))[1])


    def test_historical_duplicate_pcs_require_review_without_mutation(self):
        from backend.common.errors import ServiceError
        self.snapshot()
        room=SmileRoom.objects.get(box='box-3')
        for name in ('PC A','PC B'):
            AgentRegistration.objects.create(name=name,box=room.box,token_sha256='a'*64)
        with self.assertRaises(ServiceError) as caught:
            create_pairable_agent(name='No elegir arbitrariamente',room_id=room.pk)
        self.assertEqual(caught.exception.code,'SMILE_ROOM_CONFLICT')
        self.assertEqual(AgentRegistration.objects.count(),2)
        self.assertFalse(AgentRegistration.objects.filter(smile_room__isnull=False).exists())
