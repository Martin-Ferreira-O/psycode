from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.apps.capture.services import CaptureSessionService


class Command(BaseCommand):
    help = "Recupera sesiones sin inicio entregado y diagnostica capturas pendientes de confirmación."

    def add_arguments(self, parser):
        parser.add_argument("--check-drain", action="store_true",
                            help="Solo imprime cuántas capturas requieren confirmación antes del despliegue")
        parser.add_argument("--start-timeout", type=int, default=settings.CAPTURE_START_TIMEOUT_SECONDS, help="Segundos para advertir inicio sin confirmar")
        parser.add_argument("--heartbeat-timeout", type=int, default=settings.CAPTURE_INACTIVITY_TIMEOUT_SECONDS, help="Segundos sin actividad para diagnóstico")
        parser.add_argument("--finalization-timeout", type=int, default=settings.CAPTURE_FINALIZATION_TIMEOUT_SECONDS, help="Segundos para advertir detención sin confirmar")

    def handle(self, *args, **options):
        values = {key: options[key] for key in ("start_timeout", "heartbeat_timeout", "finalization_timeout")}
        if any(value <= 0 for value in values.values()):
            raise CommandError("Los tiempos de espera deben ser positivos")
        service = CaptureSessionService(**{key: timedelta(seconds=value) for key, value in values.items()})
        if options["check_drain"]:
            self.stdout.write(str(service.count_pending_drain()))
            return
        self.stdout.write(f"Sesiones actualizadas: {service.recover()}")
