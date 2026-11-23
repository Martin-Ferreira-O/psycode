import copy
import io
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings, tag
from pymongo.errors import DuplicateKeyError
from rest_framework.test import APIClient

from backend.apps.alerts.demo import DEMO_ALERTS, EVALUADOR_ID, EVALUADOR_USUARIO, ORIGEN
from backend.apps.alerts.documents import CAMPOS_ALERTA, CAMPOS_PROHIBIDOS, alerta_a_documento, documento_a_alerta
from backend.apps.alerts.domain import EstadoEvaluacion, Semaforo, alerta_nueva
from backend.apps.alerts.exceptions import AlertAlreadyExists, AlertNotFound, EvaluationAlreadyRegistered
from backend.apps.alerts.mongo import close_client
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.common.errors import PersistenceUnavailable

MOMENTO = datetime(2026, 9, 12, 14, 5, 22, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, matched, modified):
        self.matched_count = matched
        self.modified_count = modified


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, documento):
        stored = copy.deepcopy(documento)
        if "estado_evaluacion" in stored:
            if any(item.get("alerta_id") == stored["alerta_id"] and "estado_evaluacion" in item for item in self.docs):
                raise DuplicateKeyError("E11000 duplicate alerta_id")
        self.docs.append(stored)
        return FakeResult(1, 1)

    def find_one(self, filtro, projection=None):
        for item in self.docs:
            if all(item.get(clave) == valor for clave, valor in filtro.items()):
                encontrado = copy.deepcopy(item)
                if projection and projection.get("_id") == 0:
                    encontrado.pop("_id", None)
                return encontrado
        return None

    def update_one(self, filtro, actualizacion):
        actual = self.find_one(filtro)
        if actual is None:
            return FakeResult(0, 0)
        for item in self.docs:
            if all(item.get(clave) == valor for clave, valor in filtro.items()):
                for ruta, valor in actualizacion.get("$set", {}).items():
                    destino = item
                    partes = ruta.split(".")
                    for parte in partes[:-1]:
                        destino = destino[parte]
                    destino[partes[-1]] = valor
                return FakeResult(1, 1)
        return FakeResult(0, 0)

    def create_index(self, *args, **kwargs):
        return kwargs.get("name", "index")

    def delete_many(self, filtro):
        ids = set(filtro.get("alerta_id", {}).get("$in", []))
        before = len(self.docs)
        self.docs = [item for item in self.docs if item.get("alerta_id") not in ids]
        return FakeResult(before - len(self.docs), before - len(self.docs))


class FakeDatabase:
    def __init__(self):
        self._cols = {}

    def list_collection_names(self):
        return list(self._cols)

    def create_collection(self, name, **kwargs):
        self._cols[name] = FakeCollection()
        return self._cols[name]

    def command(self, spec):
        return {"ok": 1}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = FakeCollection()
        return self._cols[name]


def alta_pendiente(**overrides):
    datos = {
        "alerta_id": "11111111-1111-4111-8111-111111111111",
        "box": "box-3",
        "tipo_riesgo": "riesgo_suicida",
        "nivel_severidad": 2,
        "fecha_hora": MOMENTO,
        "sesion_id": "33333333-3333-4333-8333-333333333333",
        "origen": ORIGEN,
        "descripcion": None,
        "registrada_en": MOMENTO,
    }
    datos.update(overrides)
    return alerta_nueva(**datos)


class DocumentMappingTests(SimpleTestCase):
    def test_documento_no_incluye_audio_ni_paciente(self):
        alerta = alta_pendiente()
        documento = alerta_a_documento(alerta)
        self.assertEqual(set(documento), set(CAMPOS_ALERTA))
        self.assertFalse(CAMPOS_PROHIBIDOS.intersection(documento))
        self.assertIsInstance(documento["nivel_severidad"], int)
        self.assertNotIsInstance(documento["nivel_severidad"], bool)
        self.assertIsNone(documento["evaluacion"])
        self.assertEqual(documento_a_alerta(documento).alerta_id, alerta.alerta_id)

    def test_rechaza_documento_con_audio(self):
        documento = alerta_a_documento(alta_pendiente())
        documento["audio"] = b"no-guardar"
        with self.assertRaises(ValueError):
            documento_a_alerta(documento)


class RepositoryTests(SimpleTestCase):
    def setUp(self):
        self.store = AlertsRepository(FakeDatabase())
        self.service = AlertsService(self.store)

    def test_inserta_consulta_y_conserva_campos(self):
        alerta = alta_pendiente(descripcion="No quiero seguir sintiéndome así.")#Prueba de almacenamiento
        self.store.insert_alert(alerta)
        leida = self.store.get_alert(alerta.alerta_id)
        self.assertEqual(leida.box, "box-3")
        self.assertEqual(leida.sesion_id, alerta.sesion_id)
        self.assertEqual(leida.semaforo, Semaforo.MEDIO)
        self.assertEqual(leida.estado_evaluacion, EstadoEvaluacion.PENDIENTE)
        self.assertIsNone(leida.evaluacion)
        self.assertEqual(leida.trazabilidad.origen, ORIGEN)

        
        self.assertEqual(leida.descripcion,"No quiero seguir sintiéndome así.")

    def test_descripcion_normalizada_se_conserva_en_persistencia(self):
        alerta = alta_pendiente(descripcion="  No   quiero\nseguir\t sintiéndome   así.  ") 
        self.store.insert_alert(alerta) 
        leida = self.store.get_alert(alerta.alerta_id)

        self.assertEqual(leida.descripcion,"No quiero seguir sintiéndome así.")
       
    def test_duplicado_y_ausente(self):
        alerta = alta_pendiente()
        self.store.insert_alert(alerta)
        with self.assertRaises(AlertAlreadyExists):
            self.store.insert_alert(alerta)
        with self.assertRaises(AlertNotFound):
            self.store.get_alert("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    def test_evaluacion_atomica_no_se_sobrescribe(self):
        alerta = alta_pendiente()
        self.store.insert_alert(alerta)
        self.service.record_evaluation(alerta.alerta_id, "correcta", EVALUADOR_ID, EVALUADOR_USUARIO)
        leida = self.store.get_alert(alerta.alerta_id)
        self.assertEqual(leida.estado_evaluacion, EstadoEvaluacion.CORRECTA)
        self.assertEqual(leida.evaluacion.usuario_id, EVALUADOR_ID)
        self.assertEqual(leida.semaforo, Semaforo.MEDIO)
        with self.assertRaises(EvaluationAlreadyRegistered):
            self.service.record_evaluation(alerta.alerta_id, "neutro", EVALUADOR_ID, EVALUADOR_USUARIO)

    def test_cinco_alertas_variadas_se_consultan(self):
        for spec in DEMO_ALERTS:
            self.service.register_alert(
                alerta_id=spec["alerta_id"],
                box=spec["box"],
                tipo_riesgo=spec["tipo_riesgo"],
                nivel_severidad=spec["nivel_severidad"],
                fecha_hora=spec["fecha_hora"],
                sesion_id=spec["sesion_id"],
                origen=ORIGEN,
                descripcion=spec["descripcion"],
            )
            if spec["evaluacion"] is not None:
                self.service.record_evaluation(spec["alerta_id"], spec["evaluacion"], EVALUADOR_ID, EVALUADOR_USUARIO)
        leidas = [self.store.get_alert(spec["alerta_id"]) for spec in DEMO_ALERTS]
        self.assertEqual(len(leidas), 5)
        self.assertGreaterEqual(len({item.box for item in leidas}), 2)
        self.assertGreaterEqual(len({item.tipo_riesgo for item in leidas}), 2)
        self.assertGreaterEqual(len({item.nivel_severidad for item in leidas}), 2)
        self.assertGreaterEqual(len({item.estado_evaluacion for item in leidas}), 2)
        self.assertTrue(any(item.evaluacion is None for item in leidas))
        self.assertTrue(any(item.evaluacion is not None for item in leidas))
        for item in leidas:
            self.assertFalse(CAMPOS_PROHIBIDOS.intersection(alerta_a_documento(item)))


class ConnectionTests(SimpleTestCase):
    def tearDown(self):
        close_client()

    @override_settings(MONGODB_URI="")
    def test_sin_uri_es_persistencia_no_disponible(self):
        with self.assertRaises(PersistenceUnavailable):
            AlertsRepository().get_alert("11111111-1111-4111-8111-111111111111")

    @override_settings(MONGODB_URI="mongodb://127.0.0.1:1", MONGODB_SERVER_SELECTION_TIMEOUT_MS=200)
    def test_servidor_inaccesible_es_persistencia_no_disponible(self):
        close_client()
        with self.assertRaises(PersistenceUnavailable):
            AlertsRepository().ensure_schema()

    def test_comando_exige_debug_y_uri(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_alerts", stdout=io.StringIO())
        with override_settings(DEBUG=True, MONGODB_URI=""):
            with self.assertRaises(CommandError):
                call_command("seed_demo_alerts", stdout=io.StringIO())


@tag("mongo")
@unittest.skipUnless(os.getenv("PSYCODE_TEST_MONGODB_URI", "").strip(), "requiere MongoDB real")
class MongoIntegrationTests(SimpleTestCase):
    def setUp(self):
        close_client()
        self.store = AlertsRepository()
        self.store.ensure_schema()
        db = self.store._db()
        db["alerts"].delete_many({"alerta_id": {"$in": [item["alerta_id"] for item in DEMO_ALERTS]}})
        db["audit_events"].delete_many({"alerta_id": {"$in": [item["alerta_id"] for item in DEMO_ALERTS]}})
        self.store._schema_ready = True

    def tearDown(self):
        db = self.store._db()
        db["alerts"].delete_many({"alerta_id": {"$in": [item["alerta_id"] for item in DEMO_ALERTS]}})
        db["audit_events"].delete_many({"alerta_id": {"$in": [item["alerta_id"] for item in DEMO_ALERTS]}})
        close_client()

    def test_ciclo_real_insertar_evaluar_consultar(self):
        service = AlertsService(self.store)
        spec = DEMO_ALERTS[2]
        service.register_alert(
            alerta_id=spec["alerta_id"],
            box=spec["box"],
            tipo_riesgo=spec["tipo_riesgo"],
            nivel_severidad=spec["nivel_severidad"],
            fecha_hora=spec["fecha_hora"],
            sesion_id=spec["sesion_id"],
            origen=ORIGEN,
            descripcion=spec["descripcion"],
        )
        service.record_evaluation(spec["alerta_id"], spec["evaluacion"], EVALUADOR_ID, EVALUADOR_USUARIO)
        leida = self.store.get_alert(spec["alerta_id"])
        self.assertEqual(leida.estado_evaluacion, spec["evaluacion"])
        self.assertNotIn("audio", alerta_a_documento(leida))
        evento = self.store._db()["audit_events"].find_one({"alerta_id": spec["alerta_id"], "action": "alerts.evaluate"})
        self.assertIsNotNone(evento)
        self.assertEqual(evento["actor_id"], EVALUADOR_ID)

    def test_persiste_evidencias_del_analisis_por_bloque(self):
        evidence = {
            "categoria": "Caso sintético",
            "nivel_matriz": 2,
            "inicio": 1.25,
            "fin": 3.0,
            "puntaje": 0.95,
            "umbral": 0.8,
            "plazo": None,
        }
        analysis = {
            **evidence,
            "version": "bloque-texto-1",
            "evidencias": [{
                **evidence,
                "texto": "Evidencia sintética",
                "contexto_anterior": "",
                "contexto_posterior": "Contexto de la prueba",
            }],
            "evidencias_pendientes": [
                {"code": "JEV_EVIDENCE_UNCERTAIN", "start": 4.0, "end": 6.0, "matrix_level": None},
                {"code": "JEV_BELOW_THRESHOLD", "start": 8.0, "end": 10.0, "matrix_level": 2},
            ],
        }
        alert = alta_pendiente(alerta_id=DEMO_ALERTS[0]["alerta_id"], analisis=analysis)

        self.store.insert_alert(alert)

        self.assertEqual(self.store.get_alert(alert.alerta_id).analisis, analysis)

    def test_api_real_lista_todas_y_registra_evaluacion(self):
        spec = DEMO_ALERTS[0]
        AlertsService(self.store).register_alert(
            alerta_id=spec["alerta_id"],
            box=spec["box"],
            tipo_riesgo=spec["tipo_riesgo"],
            nivel_severidad=spec["nivel_severidad"],
            fecha_hora=spec["fecha_hora"],
            sesion_id=spec["sesion_id"],
            origen=ORIGEN,
            descripcion=spec["descripcion"],
        )
        client = APIClient()
        client.force_authenticate(
            user=SimpleNamespace(
                is_authenticated=True,
                pk=EVALUADOR_ID,
                username=EVALUADOR_USUARIO,
            )
        )

        lista = client.get("/api/v1/alerts?limit=50&offset=0")
        self.assertEqual(lista.status_code, 200, lista.content)
        self.assertEqual(lista.data["data"]["total"], 1)
        self.assertEqual(len(lista.data["data"]["items"]), 1)

        
        self.assertNotIn("descripcion",lista.data["data"]["items"][0],)
        detalle_alerta = client.get(f"/api/v1/alerts/{spec['alerta_id']}")
        self.assertEqual(detalle_alerta.status_code,200,detalle_alerta.content,)
        self.assertIn("descripcion",detalle_alerta.data["data"],)
        self.assertEqual(detalle_alerta.data["data"]["descripcion"],spec["descripcion"],)

        
        

        response = client.post(f"/api/v1/alerts/{spec['alerta_id']}/evaluacion",{"evaluacion": "correcta"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["data"]["usuario_id"], EVALUADOR_ID)

        detalle = client.get(f"/api/v1/alerts/{spec['alerta_id']}/evaluacion")
        self.assertEqual(detalle.status_code, 200, detalle.content)
        self.assertEqual(detalle.data["data"]["evaluacion"], "correcta")

        revisadas = client.get("/api/v1/alerts?revisadas=true&limit=50&offset=0")
        pendientes = client.get("/api/v1/alerts?revisadas=false&limit=50&offset=0")
        self.assertEqual(revisadas.data["data"]["total"], 1)
        self.assertEqual(pendientes.data["data"]["total"], 0)


class AlertApiAccessTests(SimpleTestCase):
    def test_detalle_alerta_requiere_autenticacion(self):
        client = APIClient()

        response = client.get(
            "/api/v1/alerts/11111111-1111-4111-8111-111111111111")
        
        self.assertEqual(response.status_code,401,response.content,)
        self.assertEqual(response.data["error"]["code"],"AUTH_REQUIRED",)
