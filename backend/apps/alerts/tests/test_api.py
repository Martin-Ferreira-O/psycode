"""Contrato HTTP de alertas: fechas UTC y filtros de consulta."""

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from backend.apps.alerts.domain import alerta_con_evaluacion, evaluacion_nueva
from backend.apps.alerts.exceptions import EvaluationAlreadyRegistered
from backend.apps.alerts.ports import AlertQueryFilters
from backend.apps.alerts.repositories import AlertsRepository
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


class AlertSeveritySerializerTests(SimpleTestCase):
    def test_list_serializer_emits_the_three_level_semaphore_mapping(self):
        expected = {1: "BAJO", 2: "MEDIO", 3: "ALTO"}
        for level, semaphore in expected.items():
            with self.subTest(level=level):
                alert = alta_pendiente(nivel_severidad=level)
                serialized = AlertaListItemSerializer(alert).data
                self.assertEqual(serialized["nivel_severidad"], level)
                self.assertEqual(serialized["semaforo"], semaphore)

    def test_severity_field_declares_the_supported_range(self):
        field = AlertaListItemSerializer().fields["nivel_severidad"]
        self.assertEqual(field.min_value, 1)
        self.assertEqual(field.max_value, 3)


class AlertFilterTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=SimpleNamespace(is_authenticated=True))

    def assert_validation_error(self, path, field):
        with patch("backend.apps.alerts.views.get_service") as service:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(set(response.data), {"success", "error", "timestamp"})
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn(field, response.data["error"]["details"]["fields"])
        service.assert_not_called()

    def test_parametros_desconocidos_repetidos_e_invalidos(self):
        for path, field in (
            ("/api/v1/alerts?desconocido=1", "desconocido"),
            ("/api/v1/alerts?box=a&box=b", "box"),
            ("/api/v1/alerts?revisadas=true&revisadas=false", "revisadas"),
            ("/api/v1/alerts?revisadas=1", "revisadas"),
            ("/api/v1/alerts?estado_evaluacion=otra", "estado_evaluacion"),
            ("/api/v1/alerts?limit=0", "limit"),
            ("/api/v1/alerts?offset=9223372036854775808", "offset"),
            ("/api/v1/alerts?fecha_hasta=fecha", "fecha_hasta"),
            ("/api/v1/alerts?fecha_desde=2026-09-13&fecha_hasta=2026-09-12", "fecha_desde"),
        ):
            with self.subTest(path=path):
                self.assert_validation_error(path, field)

    def test_revisadas_ausente_no_filtra_alertas_pendientes(self):
        for query, esperado in (({}, None), ({"revisadas": "false"}, False)):
            with self.subTest(query=query), patch("backend.apps.alerts.views.get_service") as get_service:
                get_service.return_value.list_alerts.return_value = ([], 0)
                response = self.client.get("/api/v1/alerts", query)

            self.assertEqual(response.status_code, 200, response.content)
            filtros = get_service.return_value.list_alerts.call_args.args[0]
            self.assertIs(filtros.revisadas, esperado)

    def test_detalle_rechaza_parametros_de_consulta(self):
        self.assert_validation_error("/api/v1/alerts/11111111-1111-4111-8111-111111111111?foo=1", "query")

    def test_fecha_extrema_llega_al_servicio_sin_error_interno(self):
        with patch("backend.apps.alerts.views.get_service") as get_service:
            get_service.return_value.list_alerts.return_value = ([], 0)
            response = self.client.get("/api/v1/alerts?fecha_desde=9999-12-31&fecha_hasta=9999-12-31")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["data"]["total"], 0)
        filters = get_service.return_value.list_alerts.call_args.args[0]
        self.assertIsNotNone(filters.fecha_desde_utc)
        self.assertIsNone(filters.fecha_hasta_utc)

    def test_estado_y_revisadas_se_combinan_con_and(self):
        store = AlertsRepository()
        cases = (
            ("correcta", True, [{"estado_evaluacion": "correcta"}, {"estado_evaluacion": {"$ne": "pendiente"}}]),
            ("pendiente", True, [{"estado_evaluacion": "pendiente"}, {"estado_evaluacion": {"$ne": "pendiente"}}]),
            ("correcta", False, [{"estado_evaluacion": "correcta"}, {"estado_evaluacion": "pendiente"}]),
        )
        for estado, revisadas, clauses in cases:
            with self.subTest(estado=estado, revisadas=revisadas), patch.object(store, "_alerts") as collection:
                collection.return_value.count_documents.return_value = 0
                collection.return_value.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
                store.list_alerts(AlertQueryFilters(estado_evaluacion=estado, revisadas=revisadas))
                query = collection.return_value.count_documents.call_args.args[0]
                self.assertEqual(query, {"$and": clauses})
                collection.return_value.find.assert_called_once_with(query, {"_id": 0})

    def test_estado_revisadas_y_otros_filtros_conservan_and(self):
        store = AlertsRepository()
        with patch.object(store, "_alerts") as collection:
            collection.return_value.count_documents.return_value = 0
            collection.return_value.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
            store.list_alerts(AlertQueryFilters(box="box-3", estado_evaluacion="correcta", revisadas=True, q="riesgo"))
            query = collection.return_value.count_documents.call_args.args[0]
        self.assertEqual(query["box"], "box-3")
        self.assertEqual(query["$and"], [{"estado_evaluacion": "correcta"}, {"estado_evaluacion": {"$ne": "pendiente"}}])
        self.assertEqual(query["$or"], [
            {"alerta_id": {"$regex": "riesgo", "$options": "i"}},
            {"box": {"$regex": "riesgo", "$options": "i"}},
            {"tipo_riesgo": {"$regex": "riesgo", "$options": "i"}},
            {"tipo_riesgo": {"$regex": (
                "^(?:conducta_suicida|consideracion_de_metodo|deseo_pasivo_de_muerte"
                "|ideacion_activa|sin_ideacion_identificable)$"
            ), "$options": "i"}},
        ])

    def test_busqueda_acepta_texto_visible_y_codigos_guardados(self):
        cases = (
            ("BOX 03", "box", "box-3", True),
            ("box_3", "box", "BOX-03", True),
            ("box-3", "box", "box-4", False),
            ("Ideacion  ACTIVA", "tipo_riesgo", "ideacion_activa", True),
            ("IDEACION_ACTIVA", "tipo_riesgo", "Ideacion activa", True),
            ("Riesgo Suicida", "tipo_riesgo", "DESEO_PASIVO_DE_MUERTE", True),
            ("VULNERACIÓN DE DERECHOS", "tipo_riesgo", "vulneracion_derechos", True),
            ("vulneracion de derechos", "tipo_riesgo", "vulneracion_derechos", True),
            ("riesgo.*", "tipo_riesgo", "riesgo_suicida", False),
            ("ABC-DEF", "alerta_id", "123abc-def456", True),
            ("ABC DEF", "alerta_id", "123abc-def456", False),
        )
        store = AlertsRepository()
        for text, field, value, expected in cases:
            with self.subTest(text=text, value=value), patch.object(store, "_alerts") as alerts:
                alerts.return_value.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
                store.list_alerts(AlertQueryFilters(q=text))
                query = alerts.return_value.count_documents.call_args.args[0]
                conditions = [clause[field] for clause in query["$or"] if field in clause]
                found = any(
                    re.search(condition["$regex"], value, re.IGNORECASE if condition["$options"] == "i" else 0)
                    for condition in conditions
                )
                self.assertEqual(found, expected)


class AlertEvaluationApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.usuario_id = "22222222-2222-4222-8222-222222222222"
        self.alerta_id = "11111111-1111-4111-8111-111111111111"
        self.client.force_authenticate(
            user=SimpleNamespace(
                is_authenticated=True,
                pk=self.usuario_id,
                username="psicologo",
            )
        )

    def test_post_registra_evaluacion_con_usuario_autenticado(self):
        momento = datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc)
        evaluacion = evaluacion_nueva(
            alerta_id=self.alerta_id,
            resultado="correcta",
            usuario_id=self.usuario_id,
            usuario="psicologo",
            fecha_hora=momento,
        )
        with patch("backend.apps.alerts.views.get_service") as get_service:
            get_service.return_value.record_evaluation.return_value = evaluacion
            response = self.client.post(
                f"/api/v1/alerts/{self.alerta_id}/evaluacion",
                {"evaluacion": "correcta"},
                format="json",
            )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["data"]["evaluacion"], "correcta")
        self.assertEqual(response.data["data"]["usuario_id"], self.usuario_id)
        self.assertEqual(
            response.headers["Location"],
            f"/api/v1/alerts/{self.alerta_id}/evaluacion",
        )
        get_service.return_value.record_evaluation.assert_called_once_with(
            self.alerta_id, "correcta", self.usuario_id, "psicologo"
        )

    def test_get_evaluacion_devuelve_resultado_y_pendiente_devuelve_404(self):
        momento = datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc)
        alerta = alta_pendiente()
        evaluacion = evaluacion_nueva(
            alerta_id=self.alerta_id,
            resultado="falso_positivo",
            usuario_id=self.usuario_id,
            usuario="psicologo",
            fecha_hora=momento,
        )
        evaluada = alerta_con_evaluacion(alerta, evaluacion, momento)

        with patch("backend.apps.alerts.views.get_service") as get_service:
            get_service.return_value.get_alert.return_value = evaluada
            response = self.client.get(f"/api/v1/alerts/{self.alerta_id}/evaluacion")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["data"]["evaluacion"], "falso_positivo")

        with patch("backend.apps.alerts.views.get_service") as get_service:
            get_service.return_value.get_alert.return_value = alerta
            response = self.client.get(f"/api/v1/alerts/{self.alerta_id}/evaluacion")
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.data["error"]["code"], "EVALUACION_NO_ENCONTRADA")

    def test_post_repetido_devuelve_conflicto(self):
        with patch("backend.apps.alerts.views.get_service") as get_service:
            get_service.return_value.record_evaluation.side_effect = EvaluationAlreadyRegistered(self.alerta_id)
            response = self.client.post(
                f"/api/v1/alerts/{self.alerta_id}/evaluacion",
                {"evaluacion": "correcta"},
                format="json",
            )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.data["error"]["code"], "EVALUACION_YA_REGISTRADA")
