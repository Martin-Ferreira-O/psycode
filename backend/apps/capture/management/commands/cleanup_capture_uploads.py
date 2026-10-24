from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from backend.apps.capture.cleanup import clean_orphan_fragments
from backend.config.composition import fragment_storage


class Command(BaseCommand):
    help = "Elimina cargas huérfanas antiguas; conserva archivos bloqueados o referenciados por trabajos."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-seconds", type=int, default=None)

    def handle(self, *args, **options):
        age = options["older_than_seconds"]
        age = settings.CAPTURE_ORPHAN_MAX_AGE_SECONDS if age is None else age
        if age <= 0:
            raise CommandError("La antigüedad debe ser positiva.")
        try:
            result = clean_orphan_fragments(fragment_storage(), older_than_seconds=age)
        except DatabaseError:
            raise CommandError("PERSISTENCE_UNAVAILABLE") from None
        except OSError:
            raise CommandError("FRAGMENT_STORAGE_UNAVAILABLE") from None
        self.stdout.write(f"Archivos eliminados: {result.removed}; protegidos: {result.protected}; ocupados: {result.busy}.")
