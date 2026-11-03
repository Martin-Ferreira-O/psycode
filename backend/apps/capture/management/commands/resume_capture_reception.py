"""Habilita recuperación adicional por decisión explícita del operador."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from backend.apps.capture.domain import CaptureError
from backend.apps.capture.services import CaptureSessionService


class Command(BaseCommand):
    help = "Extiende recepción de pendientes sin habilitar captura ni borrar archivos."

    def add_arguments(self, parser):
        parser.add_argument("--box", required=True)
        parser.add_argument("--session-id", required=True)
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **options):
        if not 1 <= options["days"] <= 30:
            raise CommandError("--days debe estar entre 1 y 30.")
        from django.utils import timezone
        now = timezone.now()
        try:
            CaptureSessionService().resume_reception(
                options["box"], options["session_id"], now=now,
                until=now + timedelta(days=options["days"]),
            )
        except CaptureError as exc:
            raise CommandError(exc.code) from None
        self.stdout.write("Recepción habilitada; autorización de captura sin cambios.")
