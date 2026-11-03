from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from backend.apps.capture.services import CaptureSessionService


class Command(BaseCommand):
    help = "Finaliza autorizaciones vencidas y cierra sesiones de captura abandonadas. No inicia capturas."

    def add_arguments(self, parser):
        parser.add_argument("--start-timeout", type=int, default=120, help="Segundos para confirmar inicio")
        parser.add_argument("--heartbeat-timeout", type=int, default=120, help="Segundos sin actividad")
        parser.add_argument("--finalization-timeout", type=int, default=300, help="Segundos para confirmar cierre")

    def handle(self, *args, **options):
        values = {key: options[key] for key in ("start_timeout", "heartbeat_timeout", "finalization_timeout")}
        if any(value <= 0 for value in values.values()):
            raise CommandError("Los tiempos de espera deben ser positivos")
        service = CaptureSessionService(**{key: timedelta(seconds=value) for key, value in values.items()})
        self.stdout.write(f"Sesiones actualizadas: {service.recover()}")
