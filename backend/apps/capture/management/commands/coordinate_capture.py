from backend.common.boxes import known_boxes
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from backend.apps.agenda.services import AgendaService
from backend.apps.agenda.persistence import refresh
from backend.apps.capture import leases
from backend.apps.capture.models import CaptureSession, OPEN_STATES, RuntimeLease
from backend.apps.capture.process_runtime import singleton
from backend.config.composition import capture_session_service

class Command(BaseCommand):
    help = "Coordina autorizaciones y recuperación con agenda durable. SIGTERM solicita cortes."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=settings.CAPTURE_COORDINATOR_INTERVAL_SECONDS)
        parser.add_argument("--stop-all", action="store_true")

    def handle(self, *args, **options):
        if options["interval"] <= 0:
            raise CommandError("Intervalo inválido")
        agenda = AgendaService()
        service = capture_session_service(agenda,
            start_timeout=timedelta(seconds=settings.CAPTURE_START_TIMEOUT_SECONDS),
            heartbeat_timeout=timedelta(seconds=settings.CAPTURE_INACTIVITY_TIMEOUT_SECONDS),
            finalization_timeout=timedelta(seconds=settings.CAPTURE_FINALIZATION_TIMEOUT_SECONDS))
        with singleton("coordinator") as (stop, owner):
            while not stop.is_set():
                with transaction.atomic():
                    RuntimeLease.objects.select_for_update().get(name="coordinator")
                    if not leases.owned("coordinator", owner):
                        raise CommandError("PROCESS_LEASE_LOST")
                    refresh(agenda)
                    if options["stop_all"]:
                        self.stop_all(service)
                    else:
                        service.recover()
                        for box in known_boxes():
                            service.reconcile_box(box)
                if options["once"] or options["stop_all"]:
                    return
                stop.wait(options["interval"])
            # No nuevos inicios; receptores siguen atendiendo ACK/uploads.
            self.stop_all(service)

    @staticmethod
    def stop_all(service):
        with transaction.atomic():
            for session in CaptureSession.objects.select_for_update().filter(state__in=OPEN_STATES):
                service._stop(session, timezone.now())
