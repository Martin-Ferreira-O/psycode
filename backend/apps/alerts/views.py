"""Presentación HTTP de alerts; pendiente de implementación."""
import uuid
from datetime import datetime, timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.common.errors import PersistenceUnavailable

from .exceptions import AlertNotFound
from .ports import AlertQueryFilters
from .repositories import AlertsRepository
from .serializers import (
    AlertQueryFilterSerializer,
    AlertaDetailSerializer,
    AlertaListItemSerializer,
)
from .services import AlertsService


def get_service() -> AlertsService:
    return AlertsService(store=AlertsRepository())


def ahora_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = AlertQueryFilterSerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Parámetros de consulta inválidos",
                        "details": {"fields": query_serializer.errors},
                    },
                    "timestamp": ahora_utc_iso(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

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


class AlertDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, alerta_id: str):
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