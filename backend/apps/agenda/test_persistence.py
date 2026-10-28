import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient
from backend.apps.capture.authentication import AgentIdentity
from backend.apps.capture.storage import FragmentError
from backend.apps.capture.test_api import AGENTS, TOKEN
from . import persistence
from .models import AgendaCollection
from .services import AgendaService, AgendaNotLoaded

SOURCES={'smile':{'collector_id':'agent-3','boxes':['box-3','box-4']}}

def workbook(box='box-3',empty=False):
    w=Workbook();s=w.active;s['A2']='CLINICA FISICA: '+box
    s.append([])
    for col,title in enumerate(('FECHA','HORA','DUR','ESTATUS','PACIENTE','SUPERVISOR'),1):s.cell(7,col,title)
    if not empty:
        for col,value in enumerate(('27/10/2026','09:00','01:00','CONFIRMADA','SYNTHETIC','SYNTHETIC'),1):s.cell(8,col,value)
    out=io.BytesIO();w.save(out);return out.getvalue()

@override_settings(CAPTURE_AGENDA_SOURCES=SOURCES,CAPTURE_AGENTS=AGENTS)
class DurableAgendaTests(TestCase):
    def setUp(self):
        self.identity=AgentIdentity('agent-3','box-3')
        self.raw=workbook()

    def metadata(self,operation,**changes):
        m=dict(collection_id=operation['collection_id'],source='smile',agenda_date='2026-10-27',
               obtained_at=datetime.now(timezone.utc).isoformat(),boxes=['box-3'],format_version='smile.excel.v1',
               checksum=hashlib.sha256(self.raw).hexdigest(),outcome='valid')
        m.update(changes);return m

    def receive(self,m):
        return persistence.receive(self.identity,m,io.BytesIO(self.raw))

    def test_retry_stale_and_restart_preserve_complete_source(self):
        old=persistence.issue(self.identity,'smile');new=persistence.issue(self.identity,'smile')
        m=self.metadata(new);first,created=self.receive(m)
        second,created=self.receive(m)
        self.assertFalse(created);self.assertEqual(first,second)
        with self.assertRaises(FragmentError) as caught:self.receive(self.metadata(old))
        self.assertEqual(caught.exception.code,'AGENDA_REPORT_STALE')
        self.assertEqual(bytes(AgendaCollection.objects.get(collection_id=new['collection_id']).report),self.raw)
        agenda=persistence.refresh(AgendaService())
        self.assertEqual(len(agenda.records),1)
        self.assertIs(persistence.refresh(agenda),agenda)
        self.assertTrue(agenda.is_busy('box-3',datetime(2026,10,27,12,30,tzinfo=timezone.utc)))
        with self.assertRaises(AgendaNotLoaded):agenda.is_busy('box-4',datetime.now(timezone.utc))

    def test_valid_empty_partial_and_failed_are_distinct(self):
        self.receive(self.metadata(persistence.issue(self.identity,'smile')))
        for outcome in ('partial','failed'):
            self.receive(self.metadata(persistence.issue(self.identity,'smile'),outcome=outcome))
            self.assertEqual(len(persistence.refresh(AgendaService()).records),1)
        self.raw=workbook(empty=True)
        self.receive(self.metadata(persistence.issue(self.identity,'smile')))
        agenda=persistence.refresh(AgendaService());self.assertEqual(agenda.records,())
        self.assertFalse(agenda.is_busy('box-3',datetime.now(timezone.utc)))

    def test_identity_scope_checksum_and_invalid_report(self):
        with self.assertRaises(FragmentError):persistence.issue(AgentIdentity('other','box-3'),'smile')
        op=persistence.issue(self.identity,'smile')
        for change in (dict(boxes=['box-5']),dict(checksum='0'*64)):
            with self.assertRaises(FragmentError):self.receive(self.metadata(op,**change))
        self.raw=b'not excel'
        with self.assertRaises(FragmentError):self.receive(self.metadata(op))
        self.assertIsNone(AgendaCollection.objects.get(collection_id=op['collection_id']).received_at)

    def test_excel_date_must_match_declared_report_date(self):
        operation = persistence.issue(self.identity, 'smile')
        with self.assertRaises(FragmentError) as caught:
            self.receive(self.metadata(operation, agenda_date='2026-10-28'))
        self.assertEqual(caught.exception.code, 'AGENDA_REPORT_INVALID')
        self.assertFalse(AgendaCollection.objects.filter(received_at__isnull=False).exists())

    def test_http_report_requires_a_file_and_preserves_previous_revision(self):
        self.receive(self.metadata(persistence.issue(self.identity, 'smile')))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Agent '+TOKEN)
        with TemporaryDirectory() as root, override_settings(CAPTURE_FRAGMENT_ROOT=root):
            response = client.post('/api/v1/internal/agenda-reports', {
                'archivo': 'not-a-file',
                'metadata': json.dumps(self.metadata(persistence.issue(self.identity, 'smile'))),
            }, format='multipart')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(len(persistence.refresh(AgendaService()).records), 1)

    def test_http_collection_report_auth_and_durable_receipt(self):
        with TemporaryDirectory() as root,override_settings(CAPTURE_FRAGMENT_ROOT=root):
            c=APIClient();c.credentials(HTTP_AUTHORIZATION='Agent '+TOKEN)
            op=c.post('/api/v1/internal/agenda-collections',{'source':'smile'},format='json')
            self.assertEqual(op.status_code,201,op.data)
            metadata=self.metadata(op.data['data'])
            def post():return c.post('/api/v1/internal/agenda-reports',
                {'archivo':SimpleUploadedFile('synthetic.xlsx',self.raw),'metadata':json.dumps(metadata)},format='multipart')
            first=post();self.assertEqual(first.status_code,201,first.data)
            self.assertEqual(post().status_code,200)
            c.credentials()
            self.assertEqual(post().status_code,401)

    def test_native_smile_contract_preserves_all_fields_and_empty_scope(self):
        from pathlib import Path
        self.raw=(Path(__file__).resolve().parents[3]/'contracts/smile-native-synthetic.json').read_bytes()
        metadata=self.metadata(persistence.issue(self.identity,'smile'),format_version='smile.json.v1')
        self.receive(metadata)
        agenda=persistence.refresh(AgendaService())
        self.assertEqual(len(agenda.records),1)
        saved=bytes(AgendaCollection.objects.get(collection_id=metadata['collection_id']).report)
        self.assertEqual(json.loads(saved)[0]['smile_cita_id'],'SYNTHETIC-001')
        self.assertEqual(json.loads(saved)[0]['codigo_estado'],'SYNTHETIC')
        self.assertTrue(agenda.is_busy('box-3',datetime(2026,10,27,12,30,tzinfo=timezone.utc)))
        self.raw=b'[]'
        self.receive(self.metadata(persistence.issue(self.identity,'smile'),format_version='smile.json.v1'))
        self.assertEqual(persistence.refresh(agenda).records,())

    def test_native_smile_wrong_box_id_repeated_id_invalid_status_and_partial_fail_closed(self):
        row=dict(smile_cita_id='synthetic',box=3,smile_box_id='8',fecha='2026-10-27',hora_inicio='09:00',
                 duracion_minutos=60,estado='CONFIRMADA',codigo_estado='synthetic')
        for rows in ([{**row,'smile_box_id':'9'}],[row,row],[{**row,'estado':'unknown'}],[{**row,'box':4}]):
            with self.subTest(rows=rows):
                self.raw=json.dumps(rows).encode()
                with self.assertRaises(FragmentError):
                    self.receive(self.metadata(persistence.issue(self.identity,'smile'),format_version='smile.json.v1'))
