from datetime import timezone
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from backend.apps.accounts.models import Role, User
from backend.common.responses import success_response
from .audit import (
    ACTIONS,
    OUTCOMES,
    NOTIFICATION_MODES,
    NOTIFICATION_REASONS,
    NOTIFICATION_STATUSES,
)
from .repositories import AlertsRepository


class AuditPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_active
            and (
                user.is_superuser
                or user.role == Role.ADMIN
            )
        )


class AuditQuerySerializer(serializers.Serializer):
    fecha_desde = serializers.DateTimeField(
        required=False,
        default_timezone=timezone.utc,
    )
    fecha_hasta = serializers.DateTimeField(
        required=False,
        default_timezone=timezone.utc,
    )
    alerta_id = serializers.UUIDField(required=False)
    action = serializers.ChoiceField(
        choices=ACTIONS,
        required=False,
    )
    outcome = serializers.ChoiceField(
        choices=OUTCOMES,
        required=False,
    )
    order = serializers.ChoiceField(
        choices=("asc", "desc"),
        default="asc",
    )
    limit = serializers.IntegerField(
        default=50,
        min_value=1,
        max_value=100,
    )
    offset = serializers.IntegerField(
        default=0,
        min_value=0,
    )

    def to_internal_value(self, data):
        if any(
            key not in self.fields
            or len(data.getlist(key)) != 1
            for key in data
        ):
            raise serializers.ValidationError(
                {
                    "query": [
                        "Parámetro desconocido o repetido."
                    ]
                }
            )

        return super().to_internal_value(data)

    def validate(self, attrs):
        if (
            attrs.get("fecha_desde")
            and attrs.get("fecha_hasta")
            and attrs["fecha_desde"] > attrs["fecha_hasta"]
        ):
            raise serializers.ValidationError(
                "fecha_desde no puede superar fecha_hasta."
            )

        if "alerta_id" in attrs:
            attrs["alerta_id"] = str(attrs["alerta_id"])

        return attrs


class NotificationAuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    mode = serializers.ChoiceField(
        choices=NOTIFICATION_MODES,
        allow_null=True,
    )
    phase = serializers.ChoiceField(
        choices=("principal", "respaldo", "resumen"),
    )
    reason = serializers.ChoiceField(
        choices=NOTIFICATION_REASONS,
        allow_null=True,
    )
    attempt = serializers.IntegerField(required=False)
    status = serializers.ChoiceField(
        choices=NOTIFICATION_STATUSES,
        required=False,
    )
    primary_successes = serializers.IntegerField(required=False)
    primary_failures = serializers.IntegerField(required=False)
    backup_successes = serializers.IntegerField(required=False)
    backup_failures = serializers.IntegerField(required=False)


class AuditEventSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    timestamp = serializers.DateTimeField(
        default_timezone=timezone.utc,
    )
    action = serializers.CharField()
    outcome = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor = serializers.SerializerMethodField()
    alerta_id = serializers.UUIDField(allow_null=True)
    sesion_id = serializers.UUIDField(
        allow_null=True,
        default=None,
    )
    sequence = serializers.IntegerField(
        allow_null=True,
        default=None,
    )
    channel = serializers.CharField(allow_null=True)
    contingencia = serializers.BooleanField(allow_null=True)
    error_code = serializers.CharField(allow_null=True)
    duration_ms = serializers.IntegerField(allow_null=True)
    notification = NotificationAuditSerializer(
        allow_null=True,
        default=None,
    )

    def get_actor(self, event):
        actor_id = event.get("actor_id")

        if actor_id is None:
            return "Sistema"

        actor_id = str(actor_id)
        actor_names = self.context.get(
            "actor_names",
            {},
        )

        return (
            actor_names.get(actor_id)
            or f"Usuario ({actor_id})"
        )


def obtener_nombres_actores(eventos):
    actor_ids = {
        str(evento["actor_id"])
        for evento in eventos
        if evento.get("actor_id") is not None
    }

    if not actor_ids:
        return {}

    usuarios = User.objects.filter(
        id__in=actor_ids
    ).values_list(
        "id",
        "username",
    )

    return {
        str(user_id): username
        for user_id, username in usuarios
    }


def fecha_para_excel(valor):
    if not valor:
        return None

    if isinstance(valor, str):
        valor = parse_datetime(valor)

    if valor is None:
        return None

    if django_timezone.is_aware(valor):
        valor = django_timezone.localtime(valor)

    return valor.replace(tzinfo=None)


class AuditListView(APIView):
    permission_classes = [
        IsAuthenticated,
        AuditPermission,
    ]

    def get(self, request):
        serializer = AuditQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        filters = serializer.validated_data

        items, total = AlertsRepository().list_events(
            filters
        )

        actor_names = obtener_nombres_actores(items)

        return success_response(
            {
                "items": AuditEventSerializer(
                    items,
                    many=True,
                    context={
                        "actor_names": actor_names
                    },
                ).data,
                "total": total,
                "limit": filters["limit"],
                "offset": filters["offset"],
            },
            "Bitácora de alertas",
        )


class AuditExportView(APIView):
    permission_classes = [
        IsAuthenticated,
        AuditPermission,
    ]

    def get(self, request):
        fecha_exportacion = django_timezone.now()
        repositorio = AlertsRepository()

        eventos = []
        offset = 0
        limite = 100

        while True:
            lote, total = repositorio.list_events(
                {
                    "fecha_hasta": fecha_exportacion,
                    "order": "desc",
                    "limit": limite,
                    "offset": offset,
                }
            )

            eventos.extend(lote)

            if not lote or len(eventos) >= total:
                break

            offset += len(lote)

        actor_names = obtener_nombres_actores(eventos)

        datos = AuditEventSerializer(
            eventos,
            many=True,
            context={
                "actor_names": actor_names
            },
        ).data

        libro = Workbook()
        hoja = libro.active
        hoja.title = "Bitácora"

        encabezados = [
            "Fecha y hora",
            "Tipo de evento",
            "Resultado",
            "Actor",
            "ID actor",
            "ID alerta",
            "ID sesión",
            "Secuencia",
            "Canal",
            "Uso de respaldo",
            "Código de error",
            "Duración (ms)",
            "ID notificación",
            "Modalidad de notificación",
            "Etapa de notificación",
            "Motivo de notificación",
            "Intento",
            "Estado de notificación",
            "Éxitos principales",
            "Fallos principales",
            "Éxitos respaldo",
            "Fallos respaldo",
        ]

        hoja.append(encabezados)

        acciones = {
            "alerts.register": "Registro de alerta",
            "alerts.evaluate": "Evaluación",
            "notifications.send": "Notificación",
            "notifications.result": "Resumen de notificación",
            "analysis.speechmatics": "Speechmatics",
            "analysis.jev": "JEV",
            "alerts.flow": "Flujo de alerta",
        }

        resultados = {
            "success": "Exitoso",
            "failure": "Fallido",
            "skipped": "Omitido",
        }

        modalidades = {
            "lista_distribucion": "Lista de distribución",
            "supervisores_activos": "Supervisores activos",
        }

        etapas = {
            "principal": "Envío principal",
            "respaldo": "Envío de respaldo",
            "resumen": "Resumen",
        }

        motivos = {
            "FALLO_PARCIAL": "Fallo parcial del envío principal",
            "FALLO_TOTAL": "Fallo total del envío principal",
            "SIN_DESTINATARIOS_VALIDOS": "Sin destinatarios principales válidos",
        }

        for evento in datos:
            notificacion = evento.get("notification") or {}

            contingencia = evento.get("contingencia")

            if contingencia is True:
                respaldo = "Sí"
            elif contingencia is False:
                respaldo = "No"
            else:
                respaldo = "No registrado"

            hoja.append(
                [
                    fecha_para_excel(
                        evento.get("timestamp")
                    ),
                    acciones.get(
                        evento.get("action"),
                        evento.get("action"),
                    ),
                    resultados.get(
                        evento.get("outcome"),
                        evento.get("outcome"),
                    ),
                    evento.get("actor"),
                    str(evento.get("actor_id") or ""),
                    str(evento.get("alerta_id") or ""),
                    str(evento.get("sesion_id") or ""),
                    evento.get("sequence"),
                    evento.get("channel") or "",
                    respaldo,
                    evento.get("error_code") or "",
                    evento.get("duration_ms"),
                    str(notificacion.get("id") or ""),
                    modalidades.get(
                        notificacion.get("mode"),
                        notificacion.get("mode") or "",
                    ),
                    etapas.get(
                        notificacion.get("phase"),
                        notificacion.get("phase") or "",
                    ),
                    motivos.get(
                        notificacion.get("reason"),
                        notificacion.get("reason") or "",
                    ),
                    notificacion.get("attempt"),
                    notificacion.get("status") or "",
                    notificacion.get("primary_successes"),
                    notificacion.get("primary_failures"),
                    notificacion.get("backup_successes"),
                    notificacion.get("backup_failures"),
                ]
            )

        relleno_encabezado = PatternFill(
            fill_type="solid",
            fgColor="198754",
        )

        fuente_encabezado = Font(
            color="FFFFFF",
            bold=True,
        )

        for celda in hoja[1]:
            celda.fill = relleno_encabezado
            celda.font = fuente_encabezado
            celda.alignment = Alignment(
                horizontal="center",
                vertical="center",
            )

        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = hoja.dimensions

        anchos = [
            21,
            26,
            15,
            24,
            38,
            38,
            38,
            12,
            18,
            18,
            22,
            16,
            38,
            25,
            24,
            34,
            12,
            24,
            18,
            18,
            18,
            18,
        ]

        for indice, ancho in enumerate(
            anchos,
            start=1,
        ):
            hoja.column_dimensions[
                hoja.cell(
                    row=1,
                    column=indice,
                ).column_letter
            ].width = ancho

        for celda in hoja["A"][1:]:
            if celda.value:
                celda.number_format = (
                    "dd-mm-yyyy hh:mm:ss"
                )

        for fila in hoja.iter_rows(
            min_row=2,
            max_row=hoja.max_row,
        ):
            for celda in fila:
                celda.alignment = Alignment(
                    vertical="top",
                    wrap_text=True,
                )

        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)

        fecha_nombre = django_timezone.localtime(
            fecha_exportacion
        ).strftime(
            "%Y-%m-%d_%H-%M"
        )

        nombre_archivo = (
            f"bitacora_eventos_{fecha_nombre}.xlsx"
        )

        response = HttpResponse(
            salida.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
        )

        response["Content-Disposition"] = (
            f'attachment; filename="{nombre_archivo}"'
        )

        return response