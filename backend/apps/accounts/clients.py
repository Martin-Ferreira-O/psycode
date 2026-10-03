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
        try:
            env = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "backend.config.settings",
                "PYTHONPATH": str(settings.BASE_DIR),
            }
            result = subprocess.run(
                [sys.executable, "-m", "backend.apps.accounts.email_worker"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=str(settings.BASE_DIR),
                env=env,
                timeout=settings.EMAIL_DELIVERY_TIMEOUT,
                check=False,
            )
            if result.returncode != 0:
                raise OSError("Entrega no aceptada")
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"\n[DEBUG ERROR EN EMAIL_CLIENT]: {e}\n")
            raise ServiceError("PASSWORD_RESET_DELIVERY_FAILED", "No fue posible enviar las instrucciones", 503) from None