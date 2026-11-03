from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from backend.apps.accounts.models import AuthRateLimit, PasswordResetRateLimit


class Command(BaseCommand):
    help = "Elimina contadores de autenticación vencidos, sin identidades ni secretos."

    def handle(self, *args, **options):
        now = timezone.now()
        auth, _ = AuthRateLimit.objects.filter(expires_at__lte=now).delete()
        reset, _ = PasswordResetRateLimit.objects.filter(
            window_started_at__lte=now - timedelta(seconds=settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS),
        ).delete()
        self.stdout.write(f"Contadores vencidos eliminados: {auth + reset}")
