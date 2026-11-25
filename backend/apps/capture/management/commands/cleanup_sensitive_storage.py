import json
import threading

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils import timezone

from backend.apps.capture.models import StorageCleanupRun
from backend.apps.capture.retention import INTERVAL, cleanup, inventory, serialize_run
from backend.apps.capture.storage_audit import flush_storage_audit
from backend.config.composition import fragment_storage


class Command(BaseCommand):
    help = "Aplica retención fija, reintenta borrados y publica su bitácora."

    def add_arguments(self, parser):
        parser.add_argument("--preview", action="store_true")
        parser.add_argument("--continuous", action="store_true")

    def handle(self, *args, **options):
        if options["preview"] and options["continuous"]:
            raise CommandError("La vista previa es una consulta única.")
        storage = fragment_storage()
        stop = threading.Event()
        if options["continuous"]:
            import signal
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *args: stop.set())
        while not stop.is_set():
            try:
                if options["continuous"]:
                    last = StorageCleanupRun.objects.order_by("-started_at").first()
                    if last:
                        remaining = (last.started_at + INTERVAL - timezone.now()).total_seconds()
                        if remaining > 0:
                            stop.wait(min(30, remaining))
                            continue
                if options["preview"]:
                    report = inventory(storage)
                    report.pop("candidates")
                else:
                    report = serialize_run(cleanup(storage))
                    flush_storage_audit()
                self.stdout.write(json.dumps(report))
            except BlockingIOError:
                self.stdout.write("CLEANUP_BUSY")
                if options["continuous"]:
                    stop.wait(30)
                    continue
            except (DatabaseError, OSError):
                if not options["continuous"]:
                    raise CommandError("STORAGE_CLEANUP_UNAVAILABLE") from None
                self.stderr.write("STORAGE_CLEANUP_UNAVAILABLE")
                stop.wait(30)
                continue
            if not options["continuous"]:
                break
            stop.wait(1)
