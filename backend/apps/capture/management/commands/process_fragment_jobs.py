from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from backend.config.composition import fragment_job_processor
from backend.apps.capture.process_runtime import singleton


class Command(BaseCommand):
    help = "Procesa trabajos pendientes de fragmentos mediante Speechmatics y JEV."

    def add_arguments(self, parser):
        parser.add_argument("--max-jobs", type=int, default=100)
        parser.add_argument("--continuous", action="store_true")
        parser.add_argument("--idle-seconds", type=float, default=1.0)

    def handle(self, *args, **options):
        max_jobs = options["max_jobs"]

        if max_jobs <= 0 or options["idle_seconds"] <= 0:
            raise CommandError("El máximo de trabajos debe ser positivo.")

        try:
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
        