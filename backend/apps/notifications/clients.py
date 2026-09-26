"""Adaptadores Teams/correo pendientes; este módulo no realiza envíos."""
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
    def __init__(self, destinatarios: Optional[List[str]] = None):
        if destinatarios is not None:
            self.destinatarios = destinatarios
        else:
            env_emails = os.getenv("NOTIFICATION_EMAIL_TO", "") or os.getenv("NOTIFICATION_EMAILS", "")
            self.destinatarios = [e.strip() for e in env_emails.split(",") if e.strip()]

    @property
    def nombre_canal(self) -> str:
        return "email"

    def send(self, payload: NotificationPayload) -> AttemptResult:
        inicio = time.perf_counter()

        if not self.destinatarios:
            duracion = (time.perf_counter() - inicio) * 1000
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=False,
                duracion_ms=round(duracion, 2),
                error="Configuracion ausente: destinatarios vacios",
            )

        asunto = payload.formatear_asunto_correo()
        cuerpo_plano = payload.formatear_cuerpo_correo()
        cuerpo_html = payload.formatear_html_correo()
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alertas@psycode.local")

        try:
            send_mail(
                subject=asunto,
                message=cuerpo_plano,
                html_message=cuerpo_html,
                from_email=from_email,
                recipient_list=self.destinatarios,
                fail_silently=False,
            )
            duracion = (time.perf_counter() - inicio) * 1000
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=True,
                duracion_ms=round(duracion, 2),
            )
        except Exception as e:
            duracion = (time.perf_counter() - inicio) * 1000
            return AttemptResult(
                canal=self.nombre_canal,
                exitoso=False,
                duracion_ms=round(duracion, 2),
                error=type(e).__name__,
            )