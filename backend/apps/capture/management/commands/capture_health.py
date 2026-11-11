from backend.common.boxes import known_boxes
import json
from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q
from django.utils import timezone
from backend.apps.capture.models import (
    AUDIO_TEST_ORIGIN, OPEN_STATES, AgentConnectivityEvent, AgentStatus, CaptureSession, FragmentJob, RuntimeLease, SessionState,
)
from backend.apps.capture.services import CaptureSessionService
from backend.apps.agenda.models import AgendaBoxRevision, AgendaCollection

class Command(BaseCommand):
    help = 'Salud operacional sin audio, contenido de reportes ni credenciales.'
    def handle(self,*args,**options):
        def counts(model):return dict(model.objects.values_list('state').annotate(n=Count('pk')))
        now = timezone.now()
        service = CaptureSessionService()
        # Incluir captura/recepción sin resolver y sesiones cuya recepción ya
        # terminó pero aún tienen trabajos centrales pendientes.
        sessions = CaptureSession.objects.filter(
            Q(state__in=OPEN_STATES)
            | Q(state=SessionState.FAILED, actual_end__isnull=True)
            | Q(state=SessionState.FAILED, final_sequence__isnull=True)
            | Q(state=SessionState.FAILED, next_sequence__lte=F('final_sequence'))
            | Q(sequences__fragment_job__state__in=[
                FragmentJob.State.PENDING, FragmentJob.State.PROCESSING, FragmentJob.State.REVIEW,
            ])
        ).exclude(origin=AUDIO_TEST_ORIGIN).distinct().order_by('box', 'authorized_at', 'pk')
        lifecycles = [service.inspection(s.box, s.pk, now=now) for s in sessions]
        clinical_jobs = FragmentJob.objects.exclude(sequence__session__origin=AUDIO_TEST_ORIGIN)
        backlog = {
            'reception_pending': sum(s['reception'] == 'pending' for s in lifecycles),
            'reception_intervention': sum(s['reception'] == 'intervention_required' for s in lifecycles),
            'capture_stop_unconfirmed': sum(s['capture'] == 'stop_unconfirmed' for s in lifecycles),
            'processing_intervention_jobs': clinical_jobs.filter(state=FragmentJob.State.REVIEW).count(),
            'processing_pending_jobs': clinical_jobs.filter(
                state__in=[FragmentJob.State.PENDING, FragmentJob.State.PROCESSING]).count(),
            **{level: sum(s['backlog_alert'] == level for s in lifecycles) for level in ('notice', 'warning', 'critical')},
        }
        last_events = []
        for box in known_boxes():
            item = {'box': box}
            for channel in ('https', 'wss'):
                item[channel] = AgentConnectivityEvent.objects.filter(box=box, kind__in=[
                    channel + '.disconnected', channel + '.reconnected',
                ]).order_by('-occurred_at', '-received_at', '-pk').values(
                    'agent_id', 'kind', 'occurred_at', 'received_at', 'duration_ms', 'cause',
                ).first()
            last_events.append(item)
        diagnostic_fields = {'obs', 'capturing', 'pending', 'free_bytes', 'smile_last_sync', 'operational_code'}
        agents = [{'box': a.box, 'seen_at': a.seen_at,
                   'diagnostics': {k: v for k, v in a.diagnostics.items() if k in diagnostic_fields}}
                  for a in AgentStatus.objects.order_by('box')]
        report={
            'observed_at':now.isoformat(),
            'sessions':counts(CaptureSession),'jobs':counts(FragmentJob),
            'session_lifecycles':lifecycles, 'backlog_counts':backlog,
            'last_connection_events':last_events,
            'leases':list(RuntimeLease.objects.values('name','expires_at')),
            'agents':agents,
            'agenda':list(AgendaBoxRevision.objects.values('box','collection_id','collection__received_at')),
            'agenda_failures':AgendaCollection.objects.filter(outcome__in=['partial','failed']).count()}
        self.stdout.write(json.dumps(report,default=str,ensure_ascii=False))
