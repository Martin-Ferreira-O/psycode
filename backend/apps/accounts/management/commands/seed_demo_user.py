from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.apps.accounts.models import User

DEMO_USERNAME = "martin.demo"
DEMO_EMAIL = "martin.demo@example.test"
DEMO_PASSWORD = "Psycode-Local-2026!"


class Command(BaseCommand):
    help = "Crea un profesional sintético exclusivamente para desarrollo local."

    def add_arguments(self, parser):
        parser.add_argument("--reset-password", action="store_true")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("El usuario de prueba solo se permite con DJANGO_DEBUG=true.")
        user = User.objects.filter(username=DEMO_USERNAME).first()
        if user is not None:
            if options["reset_password"]:
                if user.email != DEMO_EMAIL or user.is_staff or user.is_superuser:
                    raise CommandError("El usuario existente no es la cuenta sintética esperada.")
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
                self.stdout.write("Contraseña local de prueba restablecida.")
            else:
                self.stdout.write("El usuario de prueba ya existe; no se modificó.")
            return
        if User.objects.filter(email__iexact=DEMO_EMAIL).exists():
            raise CommandError("El correo de prueba ya pertenece a otro usuario.")
        User.objects.create_user(username=DEMO_USERNAME, email=DEMO_EMAIL, password=DEMO_PASSWORD,
                                 first_name="Martin", last_name="Demo")
        self.stdout.write(self.style.SUCCESS("Usuario local martin.demo creado; credenciales en README.md."))
