from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from backend.config.composition import fragment_job_processor


class Command(BaseCommand):
    help = "Procesa trabajos pendientes de fragmentos mediante Speechmatics y JEV."

    def add_arguments(self, parser):
        parser.add_argument("--max-jobs", type=int, default=100)

    def handle(self, *args, **options):
        max_jobs = options["max_jobs"]

        if max_jobs <= 0:
            raise CommandError("El máximo de trabajos debe ser positivo.")

        try:
            processor = fragment_job_processor()
            processed = 0

            while processed < max_jobs:
                state = processor.process_next()

                if state is None:
                    break

                processed += 1

        except DatabaseError:
            raise CommandError("PERSISTENCE_UNAVAILABLE") from None

        self.stdout.write(f"Trabajos procesados: {processed}.")
        