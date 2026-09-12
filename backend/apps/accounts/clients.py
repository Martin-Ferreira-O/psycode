"""Entrega aislada y acotada; no deja un hilo enviando después del timeout."""
import json
import os
import subprocess
import sys

from django.conf import settings

from backend.common.errors import ServiceError


class EmailClient:
    def send_password_reset(self, email, link):
        payload = {"email": email, "link": link}
        # No pasar token ni dirección en argumentos de proceso o logs.
        try:
            result = subprocess.run(
                [sys.executable, "-m", "backend.apps.accounts.email_worker"],
                input=json.dumps(payload), text=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, cwd=settings.BASE_DIR,
                env={**os.environ, "DJANGO_SETTINGS_MODULE": "backend.config.settings"},
                timeout=settings.EMAIL_DELIVERY_TIMEOUT, check=False,
            )
            if result.returncode != 0:
                raise OSError("Entrega no aceptada")
        except (OSError, subprocess.TimeoutExpired):
            raise ServiceError("PASSWORD_RESET_DELIVERY_FAILED", "No fue posible enviar las instrucciones", 503) from None
