"""Presentación HTTP de alerts; pendiente de implementación."""
import uuid
from datetime import datetime, timezone

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.common.errors import PersistenceUnavailable, ServiceError

from .exceptions import AlertNotFound, EvaluationAlreadyRegistered
from .ports import AlertQueryFilters
from .repositories import AlertsRepository
from .serializers import (
    AlertListFilterSerializer,
    AlertQueryFilterSerializer,
    EvaluacionCreateSerializer,
    EvaluacionPublicSerializer,
    AlertaDetailSerializer,
    AlertaListItemSerializer,
)
from .services import AlertsService

from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def get_service() -> AlertsService:
    return AlertsService(store=AlertsRepository())


def ahora_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = AlertListFilterSerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        data = query_serializer.validated_data
        filters = AlertQueryFilters(
            q=data.get("q"),
            fecha_desde_utc=data.get("fecha_desde_utc"),
            fecha_hasta_utc=data.get("fecha_hasta_utc"),
            box=data.get("box"),
            estado_evaluacion=data.get("estado_evaluacion"),
            revisadas=data.get("revisadas"),
            limit=data.get("limit", 50),
            offset=data.get("offset", 0),
            registro_evaluaciones=data["registro_evaluaciones"],
        )

        service = get_service()
        try:
            items, total = service.list_alerts(filters)
        except PersistenceUnavailable:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "PERSISTENCE_UNAVAILABLE",
                        "message": "Base de datos no disponible",
                        "details": {},
                    },
                    "timestamp": ahora_utc_iso(),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serialized_items = AlertaListItemSerializer(items, many=True).data

        return Response(
            {
                "success": True,
                "data": {
                    "total": total,
                    "limit": filters.limit,
                    "offset": filters.offset,
                    "items": serialized_items,
                },
                "message": "Lista paginada de recursos",
                "timestamp": ahora_utc_iso(),
            },
            status=status.HTTP_200_OK,
        )

class AlertExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = AlertQueryFilterSerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)

        data = query_serializer.validated_data

        service = get_service()

        alertas = []
        offset = 0
        limite = 100

        try:
            while True:
                filters = AlertQueryFilters(
                    q=data.get("q"),
                    fecha_desde_utc=data.get("fecha_desde_utc"),
                    fecha_hasta_utc=data.get("fecha_hasta_utc"),
                    box=data.get("box"),
                    estado_evaluacion=data.get("estado_evaluacion"),
                    revisadas=data.get("revisadas"),
                    limit=limite,
                    offset=offset,
                )

                items, total = service.list_alerts(filters)

                alertas.extend(items)

                if not items or len(alertas) >= total:
                    break

                offset += len(items)

        except PersistenceUnavailable:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "PERSISTENCE_UNAVAILABLE",
                        "message": "Base de datos no disponible",
                        "details": {},
                    },
                    "timestamp": ahora_utc_iso(),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not alertas:
            return HttpResponse(status=204)

        datos = AlertaListItemSerializer(
            alertas,
            many=True,
        ).data

        libro = Workbook()
        hoja = libro.active
        hoja.title = "Alertas"

        encabezados = [
            "Alerta",
            "Box",
            "Tipo de riesgo",
            "Nivel",
            "Semáforo",
            "Fecha",
            "Hora",
            "Estado",
        ]

        hoja.append(encabezados)

        tipos = {
            "riesgo_suicida": "Riesgo suicida",
            "vulneracion_derechos": "Vulneración de derechos",
        }

        estados = {
            "pendiente": "Pendiente",
            "correcta": "Correcta",
            "falso_positivo": "Falso positivo",
            "neutro": "Neutro",
        }

        for alerta in datos:
            fecha_valor = alerta.get("fecha_hora")
            fecha_texto = ""
            hora_texto = ""

            if fecha_valor:
                momento = parse_datetime(str(fecha_valor))

                if momento is not None:
                    if django_timezone.is_aware(momento):
                        momento = django_timezone.localtime(momento)

                    fecha_texto = momento.strftime("%d-%m-%Y")
                    hora_texto = momento.strftime("%H:%M:%S")

            tipo = alerta.get("tipo_riesgo") or ""

            hoja.append(
                [
                    str(alerta.get("alerta_id") or ""),
                    alerta.get("box") or "",
                    tipos.get(
                        tipo,
                        tipo.replace("_", " ").capitalize()
                    ),
                    alerta.get("nivel_severidad"),
                    alerta.get("semaforo") or "",
                    fecha_texto,
                    hora_texto,
                    estados.get(
                        alerta.get("estado_evaluacion"),
                        alerta.get("estado_evaluacion") or "",
                    ),
                ]
            )

        # Estilo del encabezado igual al Excel de Bitácora
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
            38,  # Alerta
            14,  # Box
            28,  # Tipo
            12,  # Nivel
            16,  # Semáforo
            14,  # Fecha
            14,  # Hora
            20,  # Estado
        ]

        for indice, ancho in enumerate(anchos, start=1):
            hoja.column_dimensions[
                hoja.cell(
                    row=1,
                    column=indice,
                ).column_letter
            ].width = ancho

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
            django_timezone.now()
        ).strftime("%Y-%m-%d_%H-%M")

        nombre_archivo = (
            f"dashboard_alertas_{fecha_nombre}.xlsx"
        )

        response = HttpResponse(
            salida.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response["Content-Disposition"] = (
            f'attachment; filename="{nombre_archivo}"'
        )

        return response
    

class AlertDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, alerta_id: str):
        if request.query_params:
            raise serializers.ValidationError({"query": ["Esta operación no acepta parámetros de consulta."]})
        try:
            valido = uuid.UUID(str(alerta_id))
            ident = str(valido)
        except (ValueError, TypeError, AttributeError):
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Identificador de alerta mal formado",
                        "details": {"alerta_id": str(alerta_id)},
                    },
                    "timestamp": ahora_utc_iso(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = get_service()
        try:
            alerta = service.get_alert(ident)
        except AlertNotFound:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "ALERTA_NO_ENCONTRADA",
                        "message": "La alerta especificada no existe",
                        "details": {"alerta_id": ident},
                    },
                    "timestamp": ahora_utc_iso(),
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        except PersistenceUnavailable:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "PERSISTENCE_UNAVAILABLE",
                        "message": "Base de datos no disponible",
                        "details": {},
                    },
                    "timestamp": ahora_utc_iso(),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serialized = AlertaDetailSerializer(alerta).data
        return Response(
            {
                "success": True,
                "data": serialized,
                "message": "Detalle de alerta",
                "timestamp": ahora_utc_iso(),
            },
            status=status.HTTP_200_OK,
        )


class AlertEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, alerta_id: str):
        try:
            alerta = get_service().get_alert(alerta_id)
        except AlertNotFound:
            raise ServiceError(
                "ALERTA_NO_ENCONTRADA",
                "La alerta especificada no existe",
                404,
                {"alerta_id": alerta_id},
            ) from None
        if alerta.evaluacion is None:
            raise ServiceError(
                "EVALUACION_NO_ENCONTRADA",
                "La alerta todavía no tiene una evaluación",
                404,
                {"alerta_id": alerta.alerta_id},
            )

        return Response(
            {
                "success": True,
                "data": EvaluacionPublicSerializer(alerta.evaluacion).data,
                "message": "Evaluación de alerta",
                "timestamp": ahora_utc_iso(),
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, alerta_id: str):
        serializer = EvaluacionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            evaluacion = get_service().record_evaluation(
                alerta_id,
                serializer.validated_data["evaluacion"],
                str(request.user.pk),
                request.user.username,
            )
        except AlertNotFound:
            raise ServiceError(
                "ALERTA_NO_ENCONTRADA",
                "La alerta especificada no existe",
                404,
                {"alerta_id": alerta_id},
            ) from None
        except EvaluationAlreadyRegistered:
            raise ServiceError(
                "EVALUACION_YA_REGISTRADA",
                "La alerta ya tiene una evaluación",
                409,
                {"alerta_id": alerta_id},
            ) from None

        return Response(
            {
                "success": True,
                "data": EvaluacionPublicSerializer(evaluacion).data,
                "message": "Evaluación registrada",
                "timestamp": ahora_utc_iso(),
            },
            status=status.HTTP_201_CREATED,
            headers={"Location": f"/api/v1/alerts/{evaluacion.alerta_id}/evaluacion"},
        )
