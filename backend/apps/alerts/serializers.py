"""Contratos de validación de alerts; ver API_CONTRACTS.md."""
import zoneinfo
from datetime import date, datetime, time, timedelta, timezone

from rest_framework import serializers

from .domain import Semaforo

ZONA_SANTIAGO = zoneinfo.ZoneInfo("America/Santiago")
MAX_MONGO_OFFSET = 2**63 - 1


class UTCDateTimeField(serializers.DateTimeField):
    """Transporta el instante en UTC antes de añadir el sufijo Z."""

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M:%SZ", default_timezone=timezone.utc, **kwargs)


class StrictQueryBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if data == "true" or data is True:
            return True
        if data == "false" or data is False:
            return False
        self.fail("invalid", input=data)


class AlertQueryFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, max_length=100)
    fecha_desde = serializers.DateField(required=False)
    fecha_hasta = serializers.DateField(required=False)
    box = serializers.CharField(required=False, max_length=64)
    estado_evaluacion = serializers.ChoiceField(
        choices=["pendiente", "correcta", "falso_positivo", "neutro"],
        required=False,
    )
    revisadas = StrictQueryBooleanField(required=False, default=None, allow_null=True)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=100)
    offset = serializers.IntegerField(required=False, default=0, min_value=0, max_value=MAX_MONGO_OFFSET)

    def to_internal_value(self, data):
        errors = {}
        for key in data:
            if key not in self.fields:
                errors[key] = ["Parámetro de consulta no reconocido."]
            elif hasattr(data, "getlist") and len(data.getlist(key)) != 1:
                errors[key] = ["Parámetro de consulta repetido."]
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)

    def validate(self, attrs):
        desde = attrs.get("fecha_desde")
        hasta = attrs.get("fecha_hasta")

        if desde and hasta and desde > hasta:
            raise serializers.ValidationError({"fecha_desde": "fecha_desde no puede ser posterior a fecha_hasta."})

        try:
            attrs["fecha_desde_utc"] = (
                datetime.combine(desde, time.min, tzinfo=ZONA_SANTIAGO).astimezone(timezone.utc)
                if desde else None
            )
            # El último día representable no tiene un sucesor: el límite superior
            # queda abierto y por tanto incluye todos sus instantes posibles.
            attrs["fecha_hasta_utc"] = (
                datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=ZONA_SANTIAGO).astimezone(timezone.utc)
                if hasta and hasta != date.max else None
            )
        except (OverflowError, ValueError) as exc:
            raise serializers.ValidationError({"fecha_desde": "Rango de fechas fuera de los límites admitidos."}) from exc

        if "q" in attrs:
            attrs["q"] = attrs["q"].strip()

        return attrs


class AlertListFilterSerializer(AlertQueryFilterSerializer):
    registro_evaluaciones = StrictQueryBooleanField(required=False, default=False)


class EvaluacionPublicSerializer(serializers.Serializer):
    alerta_id = serializers.CharField()
    evaluacion = serializers.CharField()
    usuario_id = serializers.CharField()
    usuario = serializers.CharField()
    fecha_hora = UTCDateTimeField()
    estado_evaluacion = serializers.CharField()


class EvaluacionCreateSerializer(serializers.Serializer):
    evaluacion = serializers.ChoiceField(choices=("correcta", "falso_positivo", "neutro"))

    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            extras = set(data.keys()) - set(self.fields)
            if extras:
                raise serializers.ValidationError({campo: ["Campo no permitido."] for campo in extras})
        return super().to_internal_value(data)


class AlertaListItemSerializer(serializers.Serializer):
    alerta_id = serializers.CharField()
    es_prueba = serializers.BooleanField()
    box = serializers.CharField()
    tipo_riesgo = serializers.CharField()
    nivel_severidad = serializers.IntegerField(min_value=1, max_value=3)
    semaforo = serializers.ChoiceField(choices=tuple(item.value for item in Semaforo))
    fecha_hora = UTCDateTimeField()
    estado_evaluacion = serializers.CharField()
    evaluacion = EvaluacionPublicSerializer(allow_null=True)


class TrazabilidadSerializer(serializers.Serializer):
    registrada_en = UTCDateTimeField()
    actualizada_en = UTCDateTimeField()
    origen = serializers.CharField()


class AlertaDetailSerializer(AlertaListItemSerializer):
    analisis = serializers.DictField(read_only=True, allow_null=True)
    sesion_id = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)
    hablante_no_confirmado = serializers.BooleanField()
    trazabilidad = TrazabilidadSerializer()
