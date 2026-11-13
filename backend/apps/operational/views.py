from django.shortcuts import get_object_or_404
from django.utils import timezone

from collections import defaultdict
from datetime import date
import re

from rest_framework.exceptions import NotFound, ValidationError
from backend.common.boxes import is_box, registrable_boxes
from backend.apps.capture.legacy_registry import sync_legacy_registry, historical_ids
from backend.apps.capture.pairing import discard_abandoned_enrollments
from backend.apps.capture.server_connectivity import reconcile_connection

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
    CaptureSession,
    RuntimeLease,
    ServerConnectivityOutage,
)
from backend.apps.capture.serializers import (
    AgentRegistrationCreateSerializer,
)
from backend.apps.capture.services import CaptureSessionService
from backend.common.responses import success_response
from backend.apps.agenda.collector_check import identity_for, request_check, snapshot, sources_for
from backend.apps.capture.agent_events import BoundedJSONParser

from .serializers import AgentRegistrationRenameSerializer
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
        discard_abandoned_enrollments()
        sync_legacy_registry()
        now = timezone.now()
        data, pipelines = [], {}
        for agent in AgentRegistration.objects.select_related("pairing", "smile_room", "smilecollectorcheck").all().order_by("box", "name", "agent_id"):
            if agent.control_owner:
                reconcile_connection(agent)
            pairing = getattr(agent, "pairing", None)
            pending = bool(pairing and not pairing.activated_at and pairing.expires_at > now)
            credential_state = ("active" if agent.is_active else
                "pending_pairing" if pending else
                "pairing_expired" if pairing and not pairing.activated_at else
                "pending_pairing" if not agent.token_sha256 else "revoked")
            diagnostics = agent.diagnostics or {}
            smile_sources = sources_for(identity_for(agent))
            connected = bool(agent.is_active and agent.control_owner and RuntimeLease.objects.filter(
                name=f"control:{agent.box}", owner=agent.control_owner, expires_at__gt=now,
            ).exists())
            last_audio = AcceptedSequence.objects.filter(agent_id__in=historical_ids(agent)).order_by(
                "-accepted_at", "-pk",
            ).values("captured_at", "accepted_at").first()
            # La sesión/pipeline pertenece al box; la telemetría y audio al PC.
            if agent.box not in pipelines:
                session = CaptureSession.objects.filter(box=agent.box, audiotest__isnull=True).order_by(
                    "-scheduled_start", "-authorized_at", "-session_id",
                ).first()
                pipeline = None
                if session:
                    inspection = CaptureSessionService().inspection(agent.box, session.session_id, now=now)
                    pipeline = {key: inspection[key] for key in (
                        "session_id", "capture", "reception", "processing", "diagnostic_code",
                        "error_code", "backlog_alert", "job_counts",
                    )}
                pipelines[agent.box] = pipeline
            pipeline = pipelines[agent.box]
            code = diagnostics.get("operational_code", "")
            storage = code in {"STORAGE_WARNING", "STORAGE_CRITICAL", "DISK_LOW"}
            data.append({
                "agent_id": str(agent.pk), "name": agent.name, "box": agent.box,
                "active": agent.is_active, "created_at": agent.created_at,
                "updated_at": agent.updated_at, "revoked_at": agent.revoked_at,
                "credential_state": credential_state,
                "installation_pending": pending,
                "initial_installation": agent.is_provisional,
                "installation_expires_at": pairing.expires_at if pending else None,
                "smile_room_id": str(agent.smile_room_id) if agent.smile_room_id else None,
                "room_available": agent.smile_room.available if agent.smile_room_id else True,
                "version": diagnostics.get("agent_version"),
                "connection": "online" if connected else "offline",
                "last_seen_at": agent.last_seen_at,
                # Conservar tipos/defaults de la API anterior. Los campos reportados
                # permiten distinguir un cero real de un dato aún desconocido.
                "capturing": diagnostics.get("capturing", False),
                "pending": diagnostics.get("pending", 0), "free_bytes": diagnostics.get("free_bytes"),
                "telemetry_fields": sorted(diagnostics),
                "remaining_seconds": diagnostics.get("remaining_seconds"),
                "obs": diagnostics.get("obs", "unknown"), "operational_code": code,
                "storage_warning": {
                    "active": storage,
                    "level": ("warning" if code == "STORAGE_WARNING" else "critical") if storage else None,
                    "code": code if storage else None,
                },
                "smile_last_sync": diagnostics.get("smile_last_sync"), "last_audio": last_audio,
                "smile_sources": smile_sources,
                "smile_check_supported": diagnostics.get("smile_check_supported") is True,
                "smile_check": snapshot(getattr(agent, "smilecollectorcheck", None), now) if smile_sources else None,
                "capture_status": pipeline["capture"] if pipeline else "no_session",
                "reception_status": pipeline["reception"] if pipeline else "no_session",
                "processing_status": pipeline["processing"] if pipeline else "no_session",
                "pipeline": pipeline, "pipeline_scope": "box",
            })
        return success_response(data, "PCs registrados recuperados")

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


class SmileCollectorCheckView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    parser_classes = [BoundedJSONParser]

    def post(self, request, agent_id):
        data = request.data
        if not isinstance(data, dict) or set(data) != {"source"} or not isinstance(data["source"], str):
            raise ValidationError("Indica la fuente del colector.")
        return success_response(request_check(agent_id, data["source"]), "Prueba Smile solicitada", status=202)


class AgentRegistrationRenameView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, agent_id):
        serializer = AgentRegistrationRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        if not AgentRegistration.objects.filter(pk=agent_id).update(name=name, updated_at=timezone.now()):
            raise NotFound()
        return success_response({"agent_id": str(agent_id), "name": name}, "Nombre del PC actualizado")


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
    """Incidentes completos, filtrados por inicio (detección si es desconocido)."""
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    def get(self, request, agent_id):
        agent = get_object_or_404(AgentRegistration, agent_id=agent_id)
        dates = {}
        for name in ("desde", "hasta"):
            value = request.query_params.get(name)
            try:
                if value and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError()
                dates[name] = date.fromisoformat(value) if value else None
            except ValueError:
                raise ValidationError({name: "Usa una fecha válida con formato AAAA-MM-DD."}) from None
        if dates["desde"] and dates["hasta"] and dates["desde"] > dates["hasta"]:
            raise ValidationError({"hasta": "La fecha final debe ser igual o posterior a la inicial."})
        box = request.query_params.get("box")
        if box and not is_box(box):
            raise ValidationError({"box": "Box inválido."})
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = max(1, min(int(request.query_params.get("page_size", 20)), 100))
        except (ValueError, TypeError):
            raise ValidationError({"page": "Parámetros de paginación inválidos."}) from None

        if agent.control_owner:
            reconcile_connection(agent)
        events = AgentConnectivityEvent.objects.filter(agent_id__in=historical_ids(agent)).order_by(
            "occurred_at", "received_at", "event_id",
        )
        if box:
            events = events.filter(box=box)
        grouped = defaultdict(list)
        for event in events:
            if event.kind.endswith((".disconnected", ".reconnected")):
                # No mezclar canales ni boxes aunque compartan outage_id.
                key = (event.box, event.kind.split(".")[0], str(event.outage_id or event.event_id))
                grouped[key].append(event)
        history, now = [], timezone.now()
        for (event_box, channel, outage_id), outage_events in grouped.items():
            disconnected = next((e for e in outage_events if e.kind.endswith(".disconnected")), None)
            reconnected = next((e for e in outage_events if e.kind.endswith(".reconnected")), None)
            started = disconnected.occurred_at if disconnected else None
            recovered = reconnected.occurred_at if reconnected else None
            duration = reconnected.duration_ms if reconnected else None
            if duration is None and started and recovered:
                duration = int((recovered - started).total_seconds() * 1000)
                if duration < 0:
                    duration = None
            history.append({
                "outage_id": outage_id, "box": event_box, "channel": channel, "source": "agent_reported",
                "started_at": started, "recovered_at": recovered, "duration_ms": duration,
                "cause": (disconnected.cause if disconnected and disconnected.cause else
                          reconnected.cause if reconnected and reconnected.cause else "UNKNOWN"),
                "active": disconnected is not None and reconnected is None,
                "start_time_quality": "reported" if started else "unknown",
                "recovery_time_quality": "reported" if recovered else "unknown",
                "received_at": max(e.received_at for e in outage_events),
            })
        outages = ServerConnectivityOutage.objects.filter(agent=agent)
        if box:
            outages = outages.filter(box=box)
        for outage in outages:
            duration = None
            if outage.started_at:
                duration = max(0, int(((outage.recovered_at or now) - outage.started_at).total_seconds() * 1000))
            history.append({
                "outage_id": str(outage.pk), "box": outage.box, "channel": "wss", "source": "server_inferred",
                "started_at": outage.started_at, "recovered_at": outage.recovered_at, "duration_ms": duration,
                "cause": outage.cause, "active": outage.is_active,
                "start_time_quality": outage.start_time_quality,
                "recovery_time_quality": outage.recovery_time_quality, "received_at": outage.detected_at,
            })
        # Filtrar DESPUÉS de emparejar; una recuperación fuera del rango no desaparece.
        def in_range(item):
            day = timezone.localdate(item["started_at"] or item["received_at"])
            return ((not dates["desde"] or day >= dates["desde"]) and
                    (not dates["hasta"] or day <= dates["hasta"]))
        history = [item for item in history if in_range(item)]
        history.sort(key=lambda item: (item["started_at"] or item["received_at"], item["outage_id"], item["channel"]), reverse=True)
        total = len(history)
        return success_response({
            "agent": {"agent_id": str(agent.pk), "name": agent.name, "box": agent.box},
            "filters": {"desde": request.query_params.get("desde"), "hasta": request.query_params.get("hasta"), "box": box},
            "pagination": {"page": page, "page_size": page_size, "total": total,
                           "total_pages": (total + page_size - 1) // page_size},
            "results": history[(page - 1) * page_size:page * page_size],
        }, "Historial de conexión recuperado.")


class SmileRoomListView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        from backend.apps.agenda.models import SmileRoom
        from django.conf import settings
        discard_abandoned_enrollments()
        sync_legacy_registry()
        data, by_box = [], {}
        for candidate in AgentRegistration.objects.values('agent_id', 'name', 'smile_room_id', 'box'):
            by_box.setdefault(candidate['box'], []).append(candidate)
        for room in SmileRoom.objects.all():
            candidates = by_box.get(room.box, [])
            candidate = candidates[0] if len(candidates) == 1 else None
            data.append({
                'room_id': str(room.pk), 'source': room.source, 'box': room.box,
                'name': room.name, 'smile_box_id': room.smile_box_id, 'available': room.available,
                'last_sync_at': room.last_seen_at,
                'pc_id': str(candidate['agent_id']) if candidate and candidate['smile_room_id'] == room.pk else None,
                'existing_pc_id': str(candidate['agent_id']) if candidate else None,
                'existing_pc_name': candidate['name'] if candidate else None,
                'conflict': len(candidates) > 1,
                'legacy_configured': any(item['box'] == room.box for item in settings.CAPTURE_AGENTS.values()),
            })
        represented = {item['box'] for item in data}
        for box in registrable_boxes():
            if box in represented:
                continue
            candidates = by_box.get(box, [])
            candidate = candidates[0] if len(candidates) == 1 else None
            data.append({
                'room_id': None, 'source': None, 'box': box, 'name': f"Box {box[4:]}",
                'smile_box_id': None, 'available': True, 'last_sync_at': None,
                'pc_id': str(candidate['agent_id']) if candidate else None,
                'existing_pc_id': str(candidate['agent_id']) if candidate else None,
                'existing_pc_name': candidate['name'] if candidate else None,
                'conflict': len(candidates) > 1,
                'legacy_configured': any(item['box'] == box for item in settings.CAPTURE_AGENTS.values()),
            })
        data.sort(key=lambda item: (int(item['box'][4:]), item['source']))
        return success_response(data, 'Salas de Smile recuperadas')
