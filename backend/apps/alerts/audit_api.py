"""Consulta de bitácora para administradores activos."""
from datetime import timezone

from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from backend.apps.accounts.models import Role
from backend.common.responses import success_response
from .audit import ACTIONS, OUTCOMES
from .repositories import AlertsRepository


class AuditPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_active and (user.is_superuser or user.role == Role.ADMIN))


class AuditQuerySerializer(serializers.Serializer):
    fecha_desde = serializers.DateTimeField(required=False, default_timezone=timezone.utc)
    fecha_hasta = serializers.DateTimeField(required=False, default_timezone=timezone.utc)
    alerta_id = serializers.UUIDField(required=False)
    action = serializers.ChoiceField(choices=ACTIONS, required=False)
    outcome = serializers.ChoiceField(choices=OUTCOMES, required=False)
    order = serializers.ChoiceField(choices=('asc', 'desc'), default='asc')
    limit = serializers.IntegerField(default=50, min_value=1, max_value=100)
    offset = serializers.IntegerField(default=0, min_value=0)

    def to_internal_value(self, data):
        if any(k not in self.fields or len(data.getlist(k)) != 1 for k in data):
            raise serializers.ValidationError({'query': ['Parámetro desconocido o repetido.']})
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs.get('fecha_desde') and attrs.get('fecha_hasta') and attrs['fecha_desde'] > attrs['fecha_hasta']:
            raise serializers.ValidationError('fecha_desde no puede superar fecha_hasta.')
        if 'alerta_id' in attrs:
            attrs['alerta_id'] = str(attrs['alerta_id'])
        return attrs


class AuditEventSerializer(serializers.Serializer):
    # Lista explícita: nunca devolver campos inesperados de un documento histórico.
    event_id = serializers.UUIDField()
    timestamp = serializers.DateTimeField(default_timezone=timezone.utc)
    action = serializers.CharField()
    outcome = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor = serializers.SerializerMethodField()
    alerta_id = serializers.UUIDField(allow_null=True)
    sesion_id = serializers.UUIDField(allow_null=True, default=None)
    sequence = serializers.IntegerField(allow_null=True, default=None)
    channel = serializers.CharField(allow_null=True)
    contingencia = serializers.BooleanField(allow_null=True)
    error_code = serializers.CharField(allow_null=True)
    duration_ms = serializers.IntegerField(allow_null=True)

    def get_actor(self, event):
        return 'Sistema' if event.get('actor_id') is None else 'Usuario'


class AuditListView(APIView):
    permission_classes = [IsAuthenticated, AuditPermission]

    def get(self, request):
        serializer = AuditQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data
        items, total = AlertsRepository().list_events(filters)
        return success_response({
            'items': AuditEventSerializer(items, many=True).data,
            'total': total, 'limit': filters['limit'], 'offset': filters['offset'],
        }, 'Bitácora de alertas')
