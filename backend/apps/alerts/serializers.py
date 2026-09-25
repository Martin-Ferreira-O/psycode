"""Contratos de validación de alerts; ver API_CONTRACTS.md."""
import zoneinfo
from datetime import datetime, time, timedelta

from rest_framework import serializers

ZONA_SANTIAGO = zoneinfo.ZoneInfo("America/Santiago")


class AlertQueryFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, max_length=100)
    fecha_desde = serializers.DateField(required=False)
    fecha_hasta = serializers.DateField(required=False)
    box = serializers.CharField(required=False, max_length=64)
    estado_evaluacion = serializers.ChoiceField(
        choices=["pendiente", "correcta", "falso_positivo", "neutro"],
        required=False,
    )
    revisadas = serializers.BooleanField(required=False)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=100)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate(self, attrs):
        desde = attrs.get("fecha_desde")
        hasta = attrs.get("fecha_hasta")

        if desde and hasta and desde > hasta:
            raise serializers.ValidationError({"fecha_desde": "fecha_desde no puede ser posterior a fecha_hasta."})

        if desde:
            inicio_local = datetime.combine(desde, time.min, tzinfo=ZONA_SANTIAGO)
            attrs["fecha_desde_utc"] = inicio_local.astimezone(zoneinfo.ZoneInfo("UTC"))
        else:
            attrs["fecha_desde_utc"] = None

        if hasta:
            fin_local = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=ZONA_SANTIAGO)
            attrs["fecha_hasta_utc"] = fin_local.astimezone(zoneinfo.ZoneInfo("UTC"))
        else:
            attrs["fecha_hasta_utc"] = None

        if "q" in attrs:
            attrs["q"] = attrs["q"].strip()

        return attrs


class EvaluacionCreateSerializer(serializers.Serializer):
    evaluacion = serializers.ChoiceField(
        choices=["correcta", "falso_positivo", "neutro"],
        required=True,
    )

    def validate(self, attrs):
        campos_extra = set(self.initial_data) - {"evaluacion"}
        if campos_extra:
            raise serializers.ValidationError(
                {"non_field_errors": ["Solo se permite el campo evaluacion."]}
            )
        return attrs


class EvaluacionPublicSerializer(serializers.Serializer):
    alerta_id = serializers.CharField()
    evaluacion = serializers.CharField()
    usuario_id = serializers.CharField()
    usuario = serializers.CharField()
    fecha_hora = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")
    estado_evaluacion = serializers.CharField()


class AlertaListItemSerializer(serializers.Serializer):
    alerta_id = serializers.CharField()
    box = serializers.CharField()
    tipo_riesgo = serializers.CharField()
    nivel_severidad = serializers.IntegerField()
    semaforo = serializers.SerializerMethodField()
    fecha_hora = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")
    estado_evaluacion = serializers.CharField()
    evaluacion = EvaluacionPublicSerializer(allow_null=True)

    def get_semaforo(self, obj):
        return getattr(obj.semaforo, "value", obj.semaforo)


class TrazabilidadSerializer(serializers.Serializer):
    registrada_en = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")
    actualizada_en = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")
    origen = serializers.CharField()


class AlertaDetailSerializer(AlertaListItemSerializer):
    sesion_id = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)
    trazabilidad = TrazabilidadSerializer()