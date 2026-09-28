"""Contrato HTTP de alertas: fechas UTC y filtros de consulta."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from backend.apps.alerts.domain import alerta_con_evaluacion, evaluacion_nueva
from backend.apps.alerts.serializers import AlertQueryFilterSerializer, AlertaDetailSerializer, AlertaListItemSerializer

from .test_persistence import alta_pendiente


class AlertDateTests(SimpleTestCase):
    def test_fechas_de_lista_y_detalle_conservan_el_instante_utc(self):
        santiago = ZoneInfo("America/Santiago")
        instante = datetime(2026, 9, 12, 10, 5, 22, tzinfo=santiago)
        alerta = alta_pendiente(fecha_hora=instante, registrada_en=instante)
        evaluacion = evaluacion_nueva(
            alerta_id=alerta.alerta_id,
            resultado="correcta",
            usuario_id="22222222-2222-4222-8222-222222222222",
            usuario="psicologo",
            fecha_hora=instante + timedelta(hours=1),
        )
        alerta = alerta_con_evaluacion(alerta, evaluacion, evaluacion.fecha_hora)

        for serialized in (AlertaListItemSerializer(alerta).data, AlertaDetailSerializer(alerta).data):
            fechas = [serialized["fecha_hora"], serialized["evaluacion"]["fecha_hora"]]
            if "trazabilidad" in serialized:
                fechas.extend((serialized["trazabilidad"]["registrada_en"], serialized["trazabilidad"]["actualizada_en"]))
            for valor in fechas:
                with self.subTest(valor=valor):
                    self.assertRegex(valor, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual(datetime.fromisoformat(serialized["fecha_hora"].replace("Z", "+00:00")), instante.astimezone(timezone.utc))
            self.assertEqual(datetime.fromisoformat(serialized["evaluacion"]["fecha_hora"].replace("Z", "+00:00")), evaluacion.fecha_hora)
            if "trazabilidad" in serialized:
                self.assertEqual(datetime.fromisoformat(serialized["trazabilidad"]["registrada_en"].replace("Z", "+00:00")), alerta.trazabilidad.registrada_en)
                self.assertEqual(datetime.fromisoformat(serialized["trazabilidad"]["actualizada_en"].replace("Z", "+00:00")), alerta.trazabilidad.actualizada_en)

    def test_rangos_locales_respetan_cambios_de_hora_y_fecha_extrema(self):
        for fecha, horas in (("2026-04-04", 25), ("2026-09-06", 23)):
            with self.subTest(fecha=fecha):
                serializer = AlertQueryFilterSerializer(data={"fecha_desde": fecha, "fecha_hasta": fecha})
                self.assertTrue(serializer.is_valid(), serializer.errors)
                inicio = serializer.validated_data["fecha_desde_utc"]
                fin = serializer.validated_data["fecha_hasta_utc"]
                self.assertEqual(fin - inicio, timedelta(hours=horas))

        serializer = AlertQueryFilterSerializer(data={"fecha_hasta": "9999-12-31"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data["fecha_hasta_utc"])
