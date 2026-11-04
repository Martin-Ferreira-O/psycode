from datetime import timedelta
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from backend.apps.capture.models import CaptureSession, FragmentJob
from backend.apps.capture.process_runtime import singleton
from backend.config.composition import fragment_job_processor


class Command(BaseCommand):
    help = "Procesa fragmentos, informa retrasos o reanuda trabajos revisados."

    def add_arguments(self, parser):
        parser.add_argument("--max-jobs", type=int, default=100)
        parser.add_argument("--continuous", action="store_true")
        parser.add_argument("--idle-seconds", type=float, default=1.0)
        action = parser.add_mutually_exclusive_group()
        action.add_argument("--report-processing", action="store_true")
        action.add_argument("--resume-job", type=UUID)
        parser.add_argument("--confirm-provider-not-accepted", action="store_true",
                            help="Autoriza un nuevo envío tras verificar que el anterior no fue aceptado.")
        parser.add_argument("--accept-missing-context", action="store_true",
                            help="Continúa con contexto vacío si un tramo histórico confirmado carece de él.")
        parser.add_argument("--confirm-notification-reviewed", action="store_true",
                            help="Confirma que la entrega incierta ya fue revisada por un operador.")

    def handle(self, *args, **options):
        max_jobs = options["max_jobs"]
        if max_jobs <= 0 or options["idle_seconds"] <= 0:
            raise CommandError("El máximo de trabajos y la espera deben ser positivos.")
        try:
            if options["report_processing"]:
                self.report_processing()
                return
            if options["resume_job"]:
                self.resume_job(options)
                return
            processor = fragment_job_processor()
            processed = 0
            with singleton("fragment-worker") as (stop, owner):
                while not stop.is_set() and (options["continuous"] or processed < max_jobs):
                    processor.close_finished_contexts()
                    state = processor.process_next()
                    if state is None:
                        if not options["continuous"]:
                            break
                        stop.wait(options["idle_seconds"])
                        continue
                    processed += 1
        except DatabaseError:
            raise CommandError("PERSISTENCE_UNAVAILABLE") from None

        self.stdout.write(f"Trabajos procesados: {processed}.")

    @transaction.atomic
    def resume_job(self, options):
        job = FragmentJob.objects.select_for_update().filter(
            pk=options["resume_job"], state=FragmentJob.State.REVIEW,
        ).first()
        if job is None:
            raise CommandError("El trabajo no está en revisión.")
        data = job.checkpoint
        if job.last_error_code == "ANALYSIS_CONTEXT_LOST":
            if not options["accept_missing_context"] or not FragmentJob.objects.filter(
                sequence__session_id=job.sequence.session_id, sequence__number=job.sequence.number - 1,
                state=FragmentJob.State.COMPLETED,
            ).exists():
                raise CommandError("Se requiere un tramo anterior confirmado y aceptar la ausencia de contexto.")
            data["accept_missing_context"] = True
        if "jev_pending" in data and "jev_response" not in data:
            if not options["confirm_provider_not_accepted"]:
                raise CommandError("Verifique la aceptación de JEV antes de autorizar el reenvío.")
            data.setdefault("jev_requests", []).append(data.pop("jev_pending")["request_id"])
        speech = data.get("speechmatics", {})
        if (speech.get("state") in {"submitting", "uncertain"}
                and options["confirm_provider_not_accepted"]):
            speech.update(state="new", job_id=None)
        for alert_id, state in data.get("delivery", {}).items():
            if state == "sending" and options["confirm_notification_reviewed"]:
                data["delivery"][alert_id] = "done"
        job.state = FragmentJob.State.PENDING
        job.attempts = 0
        job.retry_at = None
        job.save(update_fields=["checkpoint", "state", "attempts", "retry_at"])
        self.stdout.write(f"Trabajo {job.pk} en cola.")

    def report_processing(self):
        now = timezone.now()
        for job in FragmentJob.objects.filter(state=FragmentJob.State.REVIEW).select_related("sequence"):
            pending = job.checkpoint.get("jev_pending", {})
            request = f" solicitud={pending['request_id']}" if pending else ""
            self.stdout.write(
                f"Revisión requerida: trabajo={job.pk} sesión={job.sequence.session_id} "
                f"secuencia={job.sequence.number} código={job.last_error_code}{request}"
            )
        complete = Q(sequences__fragment_job__state=FragmentJob.State.COMPLETED)
        sessions = CaptureSession.objects.filter(actual_end__isnull=False).annotate(
            completed_count=Count("sequences__fragment_job", filter=complete),
            last_result=Max("sequences__fragment_job__finished_at", filter=complete),
        )
        for session in sessions.iterator():
            ready = (session.final_sequence is not None
                     and session.next_sequence == session.final_sequence + 1
                     and session.completed_count == session.next_sequence)
            finished = max(session.actual_end, session.last_result) if ready and session.last_result else session.actual_end
            elapsed = (finished if ready else now) - session.actual_end
            if elapsed >= timedelta(hours=2):
                status = "RETRASO"
            elif elapsed >= timedelta(hours=1):
                status = "OBJETIVO_1_A_2_HORAS" if ready else "PENDIENTE_MAS_DE_1_HORA"
            else:
                status = "MENOS_DE_1_HORA" if ready else "PENDIENTE"
            self.stdout.write(f"{status} sesión={session.pk} segundos={int(elapsed.total_seconds())}")
