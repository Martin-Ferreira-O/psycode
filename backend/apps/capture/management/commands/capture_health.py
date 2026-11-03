import json
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone
from backend.apps.capture.models import AgentStatus, CaptureSession, FragmentJob, RuntimeLease
from backend.apps.agenda.models import AgendaBoxRevision, AgendaCollection

class Command(BaseCommand):
    help = 'Salud operacional sin audio, contenido de reportes ni credenciales.'
    def handle(self,*args,**options):
        def counts(model):return dict(model.objects.values_list('state').annotate(n=Count('pk')))
        report={
            'observed_at':timezone.now().isoformat(),
            'sessions':counts(CaptureSession),'jobs':counts(FragmentJob),
            'leases':list(RuntimeLease.objects.values('name','expires_at')),
            'agents':list(AgentStatus.objects.values('box','seen_at','diagnostics')),
            'agenda':list(AgendaBoxRevision.objects.values('box','collection_id','collection__received_at')),
            'agenda_failures':AgendaCollection.objects.filter(outcome__in=['partial','failed']).count()}
        self.stdout.write(json.dumps(report,default=str,ensure_ascii=False))
