from django.shortcuts import get_object_or_404
from django.utils import timezone

from collections import defaultdict

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from backend.apps.capture.pc_registry import (
    create_agent,
    renew_agent,
    revoke_agent,
)


from backend.apps.capture.models import (
    AcceptedSequence,
    AgentConnectivityEvent,
    AgentRegistration,
    AgentStatus,
    CaptureSession,
    RuntimeLease,
    ServerConnectivityOutage,
)
from backend.apps.capture.serializers import (
    AgentRegistrationCreateSerializer,
)
from backend.apps.capture.services import CaptureSessionService
from backend.common.responses import success_response

from .services import OperationalService


class IsActiveAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        return bool(
            user.is_active
            and getattr(user, "is_admin", False)
        )


class OperationalConfigView(APIView):
    """
    Configuración operativa general del sistema.
    """

    permission_classes = [
        IsAuthenticated,
        IsActiveAdmin,
    ]

    service = OperationalService()

    def get(self, request):
        data = self.service.get_config()

        return success_response(
            data,
            "Configuración operativa recuperada",
        )

    def put(self, request):
        data = self.service.update_config(
            actor=request.user,
            data=request.data,
        )

        return success_response(
            data,
            "Configuración operativa actualizada",
        )


class AgentRegistrationListCreateView(APIView):
    """
    Gestión administrativa del registro central de PCs.

    GET:
        Lista PCs registrados y su estado operativo.

    POST:
        Registra un PC y devuelve su API key solamente
        en la respuesta de creación.
    """

    permission_classes = [
        IsAuthenticated,
        IsActiveAdmin,
    ]

    def get(self, request):
        agents = AgentRegistration.objects.all().order_by(
            "box",
            "name",
        )

        now = timezone.now()
        data = []

        for agent in agents:
            # Último estado informado por el agente.
            status = AgentStatus.objects.filter(
                box=agent.box,
            ).first()

            diagnostics = (
                dict(status.diagnostics or {})
                if status
                else {}
            )

            # Un RuntimeLease vigente indica que
            # actualmente existe una conexión WSS activa.
            connected = RuntimeLease.objects.filter(
                name=f"control:{agent.box}",
                expires_at__gt=now,
            ).exists()

            # Último fragmento de audio aceptado
            # por el servidor.
            last_audio = (
                AcceptedSequence.objects
                .filter(
                    session__box=agent.box,
                )
                .order_by(
                    "-accepted_at",
                )
                .values(
                    "captured_at",
                    "accepted_at",
                )
                .first()
            )

            # Última sesión conocida para el box.
            latest_session = (
                CaptureSession.objects
                .filter(
                    box=agent.box,
                )
                .order_by(
                    "-scheduled_start",
                    "-authorized_at",
                )
                .first()
            )

            pipeline = None

            if latest_session is not None:
                inspection = (
                    CaptureSessionService()
                    .inspection(
                        agent.box,
                        latest_session.session_id,
                        now=now,
                    )
                )

                pipeline = {
                    "session_id": inspection[
                        "session_id"
                    ],
                    "capture": inspection[
                        "capture"
                    ],
                    "reception": inspection[
                        "reception"
                    ],
                    "processing": inspection[
                        "processing"
                    ],
                    "diagnostic_code": inspection[
                        "diagnostic_code"
                    ],
                    "error_code": inspection[
                        "error_code"
                    ],
                    "backlog_alert": inspection[
                        "backlog_alert"
                    ],
                    "job_counts": inspection[
                        "job_counts"
                    ],
                }

            data.append({
                # Identidad administrativa
                "agent_id": str(agent.agent_id),
                "name": agent.name,
                "box": agent.box,
                "active": agent.is_active,
                "created_at": agent.created_at,
                "updated_at": agent.updated_at,
                "revoked_at": agent.revoked_at,

                # Estado del agente
                "version": diagnostics.get(
                    "agent_version",
                ),

                "connection": (
                    "online"
                    if connected
                    else "offline"
                ),

                "last_seen_at": (
                    status.seen_at
                    if status
                    else None
                ),

                # Estado informado directamente
                # por psycode-alterno.
                "capturing": diagnostics.get(
                    "capturing",
                    False,
                ),

                "pending": diagnostics.get(
                    "pending",
                    0,
                ),

                "free_bytes": diagnostics.get(
                    "free_bytes",
                ),

                "remaining_seconds": diagnostics.get(
                    "remaining_seconds",
                ),

                "obs": diagnostics.get(
                    "obs",
                    "unknown",
                ),

                "operational_code": diagnostics.get(
                    "operational_code",
                    "",
                ),
                # Aviso simplificado para la pantalla administrativa.
                "storage_warning": (
                    {
                        "active": True,
                        "level": (
                            "critical"
                            if diagnostics.get("operational_code") in {
                                "STORAGE_CRITICAL",
                                "DISK_LOW",
                            }
                            else "warning"
                        ),
                        "code": diagnostics.get(
                            "operational_code",
                        ),
                    }
                    if diagnostics.get("operational_code") in {
                        "STORAGE_WARNING",
                        "STORAGE_CRITICAL",
                        "DISK_LOW",
                    }
                    else {
                        "active": False,
                        "level": None,
                        "code": None,
                    }
                ),
                "smile_last_sync": diagnostics.get(
                    "smile_last_sync",
                ),

                # Último audio recibido.
                "last_audio": last_audio,

                # Estados independientes del flujo.
                "capture_status": (
                    pipeline["capture"]
                    if pipeline
                    else "no_session"
                ),

                "reception_status": (
                    pipeline["reception"]
                    if pipeline
                    else "no_session"
                ),

                "processing_status": (
                    pipeline["processing"]
                    if pipeline
                    else "no_session"
                ),

                # Detalle completo del flujo.
                "pipeline": pipeline,
            })

        return success_response(
            data,
            "PCs registrados recuperados",
        )

    def post(self, request):
        serializer = AgentRegistrationCreateSerializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        agent, api_key = create_agent(
            name=serializer.validated_data[
                "name"
            ],
            box=serializer.validated_data[
                "box"
            ],
        )

        data = {
            "agent_id": str(agent.agent_id),
            "name": agent.name,
            "box": agent.box,
            "active": agent.is_active,
            "created_at": agent.created_at,

            # La API key completa se entrega
            # solamente en este momento.
            "api_key": api_key,
        }

        return success_response(
            data,
            (
                "PC registrado. Guarda la API key; "
                "no volverá a mostrarse."
            ),
            status=201,
        )


class AgentRegistrationRevokeView(APIView):
    """
    Revoca la credencial actual de un PC sin eliminar
    su identidad ni su historial.
    """

    permission_classes = [
        IsAuthenticated,
        IsActiveAdmin,
    ]

    def post(self, request, agent_id):
        agent = get_object_or_404(
            AgentRegistration,
            agent_id=agent_id,
        )

        revoke_agent(agent)

        data = {
            "agent_id": str(agent.agent_id),
            "name": agent.name,
            "box": agent.box,
            "active": agent.is_active,
            "revoked_at": agent.revoked_at,
        }

        return success_response(
            data,
            "Credencial del PC revocada correctamente.",
        )


class AgentRegistrationRenewView(APIView):
    """
    Renueva la credencial de un PC manteniendo
    el mismo agent_id.

    La nueva API key se devuelve solamente
    en esta respuesta.
    """

    permission_classes = [
        IsAuthenticated,
        IsActiveAdmin,
    ]

    def post(self, request, agent_id):
        agent = get_object_or_404(
            AgentRegistration,
            agent_id=agent_id,
        )

        agent, api_key = renew_agent(
            agent,
        )

        data = {
            "agent_id": str(agent.agent_id),
            "name": agent.name,
            "box": agent.box,
            "active": agent.is_active,
            "revoked_at": agent.revoked_at,

            # Solo se muestra al renovar.
            "api_key": api_key,
        }

        return success_response(
            data,
            ("Credencial renovada. Guarda la nueva ""API key; no volverá a mostrarse."),
        )

class AgentConnectivityHistoryView(APIView):
    """
    Historial de caídas y recuperaciones de un PC.

    Permite filtrar por fecha y pagina los resultados.
    Distingue eventos informados por el agente de una
    desconexión actualmente inferida por el servidor.
    """

    permission_classes = [
        IsAuthenticated,
        IsActiveAdmin,
    ]

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    def get(self, request, agent_id):
        agent = get_object_or_404(
            AgentRegistration,
            agent_id=agent_id,
        )

        # ---------------------------------------------
        # Filtros de fecha
        # ---------------------------------------------
        date_from = request.query_params.get("desde")
        date_to = request.query_params.get("hasta")

        events_query = AgentConnectivityEvent.objects.filter(
            agent_id=str(agent.agent_id),
            box=agent.box,
        )

        if date_from:
            try:
                events_query = events_query.filter(
                    occurred_at__date__gte=date_from,
                )
            except ValueError:
                return success_response(
                    {
                        "error": "INVALID_DATE_FROM",
                    },
                    "Fecha 'desde' inválida.",
                    status=400,
                )

        if date_to:
            try:
                events_query = events_query.filter(
                    occurred_at__date__lte=date_to,
                )
            except ValueError:
                return success_response(
                    {
                        "error": "INVALID_DATE_TO",
                    },
                    "Fecha 'hasta' inválida.",
                    status=400,
                )

        events = list(
            events_query.order_by(
                "occurred_at",
                "received_at",
            )
        )

        # ---------------------------------------------
        # Agrupar por outage_id
        # ---------------------------------------------
        grouped = defaultdict(list)

        for event in events:
            key = (
                str(event.outage_id)
                if event.outage_id
                else str(event.event_id)
            )

            grouped[key].append(event)

        history = []
        now = timezone.now()
        for outage_id, outage_events in grouped.items():
            disconnected = next(
                (
                    event
                    for event in outage_events
                    if event.kind.endswith(
                        ".disconnected"
                    )
                ),
                None,
            )

            reconnected = next(
                (
                    event
                    for event in outage_events
                    if event.kind.endswith(
                        ".reconnected"
                    )
                ),
                None,
            )

            first_event = outage_events[0]

            channel = first_event.kind.split(".")[0]

            started_at = (
                disconnected.occurred_at
                if disconnected
                else None
            )

            recovered_at = (
                reconnected.occurred_at
                if reconnected
                else None
            )

            duration_ms = (
                reconnected.duration_ms
                if reconnected
                else None
            )

            # Si el agente informó ambos tiempos pero
            # no una duración, podemos derivarla.
            if (
                duration_ms is None
                and started_at is not None
                and recovered_at is not None
            ):
                duration_ms = int(
                    (
                        recovered_at
                        - started_at
                    ).total_seconds()
                    * 1000
                )

            cause = ""

            if disconnected and disconnected.cause:
                cause = disconnected.cause
            elif reconnected and reconnected.cause:
                cause = reconnected.cause

            history.append({
                "outage_id": outage_id,

                # https / wss / storage
                "channel": channel,

                # Este evento fue registrado originalmente
                # por psycode-alterno.
                "source": "agent_reported",

                "started_at": started_at,
                "recovered_at": recovered_at,
                "duration_ms": duration_ms,

                "cause": (
                    cause
                    if cause
                    else "UNKNOWN"
                ),

                "active": (
                    disconnected is not None
                    and reconnected is None
                ),

                # Los tiempos fueron informados por el PC.
                "start_time_quality": (
                    "reported"
                    if started_at
                    else "unknown"
                ),

                "recovery_time_quality": (
                    "reported"
                    if recovered_at
                    else "unknown"
                ),

                "received_at": max(
                    event.received_at
                    for event in outage_events
                ),
            })
        # ---------------------------------------------
        # Caídas inferidas y persistidas por el servidor
        # ---------------------------------------------
        server_outages = (
            ServerConnectivityOutage.objects
            .filter(agent=agent)
            .order_by("-detected_at")
        )

        if date_from:
            server_outages = server_outages.filter(
                detected_at__date__gte=date_from,
            )

        if date_to:
            server_outages = server_outages.filter(
                detected_at__date__lte=date_to,
            )

        for outage in server_outages:
            duration_ms = None

            if (
                outage.started_at is not None
                and outage.recovered_at is not None
            ):
                duration_ms = max(
                    0,
                    int(
                        (
                            outage.recovered_at
                            - outage.started_at
                        ).total_seconds()
                        * 1000
                    ),
                )

            elif outage.started_at is not None:
                duration_ms = max(
                    0,
                    int(
                        (
                            now - outage.started_at
                        ).total_seconds()
                        * 1000
                    ),
                )

            history.append({
                "outage_id": str(outage.outage_id),
                "channel": "wss",
                "source": "server_inferred",
                "started_at": outage.started_at,
                "recovered_at": outage.recovered_at,
                "duration_ms": duration_ms,
                "cause": outage.cause,
                "active": outage.is_active,
                "start_time_quality": outage.start_time_quality,
                "recovery_time_quality": outage.recovery_time_quality,
                "received_at": outage.detected_at,
            })

        # Más reciente primero.
        history.sort(
            key=lambda item: (
                item["started_at"]
                or item["received_at"]
                or now
            ),
            reverse=True,
        )

        # ---------------------------------------------
        # Paginación
        # ---------------------------------------------
        try:
            page = int(
                request.query_params.get(
                    "page",
                    1,
                )
            )

            page_size = int(
                request.query_params.get(
                    "page_size",
                    self.DEFAULT_PAGE_SIZE,
                )
            )
        except (TypeError, ValueError):
            return success_response(
                {
                    "error": "INVALID_PAGINATION",
                },
                "Parámetros de paginación inválidos.",
                status=400,
            )

        if page < 1:
            page = 1

        page_size = max(
            1,
            min(
                page_size,
                self.MAX_PAGE_SIZE,
            ),
        )

        total = len(history)

        start = (
            page - 1
        ) * page_size

        end = start + page_size

        results = history[start:end]

        total_pages = (
            (
                total
                + page_size
                - 1
            )
            // page_size
            if total
            else 0
        )

        data = {
            "agent": {
                "agent_id": str(agent.agent_id),
                "name": agent.name,
                "box": agent.box,
            },

            "filters": {
                "desde": date_from,
                "hasta": date_to,
            },

            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },

            "results": results,
        }

        return success_response(
            data,
            "Historial de conexión recuperado.",
        )