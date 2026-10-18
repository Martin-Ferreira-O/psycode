"""Adaptadores desacoplados de correo y Teams (fuera del flujo activo)."""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import List, Optional
from django.conf import settings
from django.core.mail import send_mail

from .domain import AttemptResult, NotificationPayload
from .ports import NotificationChannelClient

logger = logging.getLogger(__name__)


def _sanitizar_url(url: str) -> str:
    if not url:
        return "[SIN_URL]"
    partes = url.split("?")
    return f"{partes[0]}?[SECRETOS_OCULTOS]" if len(partes) > 1 else partes[0]


class TeamsClient(NotificationChannelClient):
    def __init__(self, webhook_url: Optional[str] = None, timeout_seconds: Optional[int] = None):
        self.webhook_url = (
            webhook_url
            or os.getenv("TEAMS_WORKFLOW_URL", "")
            or os.getenv("TEAMS_WEBHOOK_URL", "")
        )
        timeout_env = os.getenv("TEAMS_TIMEOUT_SECONDS", "10")
        self.timeout = timeout_seconds or int(timeout_env)

    @property
    def nombre_canal(self) -> str:
        return "teams"

    def send(self, payload: NotificationPayload) -> AttemptResult:
        inicio = time.perf_counter()

        if not self.webhook_url:
            duracion = (time.perf_counter() - inicio) * 1000
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=False,
                duracion_ms=round(duracion, 2),
                error="Configuracion ausente: webhook URL no definida",
            )

        resumen = payload.formatear_resumen_teams()
        mensaje = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "Psycode",
                                "weight": "Bolder",
                                "size": "Medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": resumen,
                                "wrap": True,
                                "size": "Default",
                            },
                        ],
                    },
                }
            ],
        }

        data_bytes = json.dumps(mensaje).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status = response.getcode()
                duracion = (time.perf_counter() - inicio) * 1000
                if 200 <= status < 300:
                    return AttemptResult(
                        canal=self.nombre_canal,
                        exitoso=True,
                        duracion_ms=round(duracion, 2),
                    )
                return AttemptResult(
                    canal=self.nombre_canal,
                    exitoso=False,
                    duracion_ms=round(duracion, 2),
                    error=f"HTTP Status {status}",
                )
        except urllib.error.HTTPError as e:
            duracion = (time.perf_counter() - inicio) * 1000
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=False,
                duracion_ms=round(duracion, 2),
                error=f"HTTPError: {e.code}",
            )
        except (urllib.error.URLError, TimeoutError) as e:
            duracion = (time.perf_counter() - inicio) * 1000
            error_tipo = "Timeout" if "timed out" in str(e).lower() else "ConexionRechazada"
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=False,
                duracion_ms=round(duracion, 2),
                error=error_tipo,
            )
        except Exception as e:
            duracion = (time.perf_counter() - inicio) * 1000
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=False,
                duracion_ms=round(duracion, 2),
                error=type(e).__name__,
            )


class EmailClient(NotificationChannelClient):
    def __init__(self, destinatarios=None, *, backup=False):
        if destinatarios is None:
            configured = (settings.NOTIFICATION_EMAIL_BACKUP_TO if backup
                          else settings.NOTIFICATION_EMAIL_TO)
            destinatarios = [e.strip() for e in configured.split(",") if e.strip()]
        self.destinatarios = destinatarios

    @property
    def nombre_canal(self):
        return "email"

    def send(self, payload):
        import subprocess
        import sys

        start = time.perf_counter()
        error = None
        if not self.destinatarios:
            error = "NOTIFICATION_NOT_CONFIGURED"
        else:
            mail = dict(subject=payload.formatear_asunto_correo(),
                        message=payload.formatear_cuerpo_correo(),
                        html_message=payload.formatear_html_correo(),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=self.destinatarios, fail_silently=False)
            try:
                if settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend":
                    # Un proceso cancelable acota DNS, conexión y diálogo SMTP completos.
                    config = {key: getattr(settings, key) for key in (
                        "EMAIL_BACKEND", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER",
                        "EMAIL_HOST_PASSWORD", "EMAIL_USE_TLS", "EMAIL_USE_SSL", "EMAIL_TIMEOUT")}
                    response = subprocess.run(
                        [sys.executable, "-m", "backend.apps.notifications.email_worker"],
                        input=json.dumps({"mail": mail, "config": config}), text=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        cwd=str(settings.BASE_DIR), timeout=settings.EMAIL_DELIVERY_TIMEOUT,
                        check=False)
                    error = {0: None, 2: "NOTIFICATION_TIMEOUT",
                             3: "NOTIFICATION_CONNECTION_FAILED", 4: "NOTIFICATION_REJECTED"}.get(
                                 response.returncode, "NOTIFICATION_INTERNAL_ERROR")
                elif send_mail(**mail) != 1:
                    error = "NOTIFICATION_REJECTED"
            except (subprocess.TimeoutExpired, TimeoutError):
                error = "NOTIFICATION_TIMEOUT"
            except (ConnectionError, OSError):
                error = "NOTIFICATION_CONNECTION_FAILED"
            except Exception:
                error = "NOTIFICATION_INTERNAL_ERROR"
        return AttemptResult("email", error is None,
                             round((time.perf_counter() - start) * 1000), error)
