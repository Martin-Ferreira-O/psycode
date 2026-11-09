import json
from django.core.management.base import BaseCommand, CommandError
from backend.apps.capture.encryption import encryption_status


class Command(BaseCommand):
    help = "Verifica cifrado del volumen y permisos/custodia local de claves sin leerlas."

    def handle(self, *args, **options):
        report = encryption_status()
        self.stdout.write(json.dumps(report))
        if not report["verified"]:
            raise CommandError("ENCRYPTION_UNVERIFIED")
