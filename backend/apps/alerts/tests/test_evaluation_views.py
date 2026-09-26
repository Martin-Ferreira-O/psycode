from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from django.test import TestCase
from rest_framework.test import APIClient

from backend.apps.alerts.domain import Evaluacion, EstadoEvaluacion
from backend.apps.alerts.exceptions import AlertNotFound, EvaluationAlreadyRegistered
from backend.common.errors import PersistenceUnavailable

ALERTA_ID = "11111111-1111-4111-8111-111111111111"
USUARIO_ID = UUID("22222222-2222-4222-8222-222222222222")
EVALUATION_TIME = datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc)
URL = f"/api/v1/alerts/{ALERTA_ID}/evaluacion"


def evaluation(result="correcta"):
    estado = EstadoEvaluacion(result)
    return Evaluacion(
        alerta_id=ALERTA_ID,
        evaluacion=estado,
        usuario_id=str(USUARIO_ID),
        usuario="psicologo",
        fecha_hora=EVALUATION_TIME,
        estado_evaluacion=estado,
    )


class EvaluationViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = SimpleNamespace(id=USUARIO_ID, username="psicologo", is_authenticated=True)
        self.client.force_authenticate(user=self.user)
        self.service = Mock()

    def post(self, payload):
        with patch("backend.apps.alerts.views.get_service", return_value=self.service):
            return self.client.post(URL, payload, format="json")

    def get(self):
        with patch("backend.apps.alerts.views.get_service", return_value=self.service):
            return self.client.get(URL)

    def test_post_acepta_cada_evaluacion_valida(self):
        for result in ("correcta", "falso_positivo", "neutro"):
            with self.subTest(result=result):
                self.service.record_evaluation.return_value = evaluation(result)
                response = self.post({"evaluacion": result})
                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data["data"]["evaluacion"], result)

        self.assertEqual(self.service.record_evaluation.call_count, 3)
        self.service.record_evaluation.assert_called_with(
            alerta_id=ALERTA_ID,
            resultado="neutro",
            usuario_id=USUARIO_ID,
            usuario="psicologo",
        )

    def test_post_rechaza_evaluacion_invalida_y_campos_extra(self):
        for payload in (
            {"evaluacion": "pendiente"},
            {"evaluacion": "correcta", "usuario_id": str(USUARIO_ID)},
        ):
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

        self.service.record_evaluation.assert_not_called()

    def test_post_mapea_errores_de_alerta_duplicada_y_persistencia(self):
        cases = (
            (AlertNotFound(ALERTA_ID), 404, "ALERTA_NO_ENCONTRADA"),
            (EvaluationAlreadyRegistered(ALERTA_ID), 409, "EVALUACION_YA_REGISTRADA"),
            (PersistenceUnavailable(), 503, "PERSISTENCE_UNAVAILABLE"),
        )
        for error, expected_status, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                self.service.record_evaluation.side_effect = error
                response = self.post({"evaluacion": "correcta"})
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.data["error"]["code"], expected_code)

    def test_get_devuelve_evaluacion_registrada(self):
        self.service.get_alert.return_value = SimpleNamespace(evaluacion=evaluation())

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["evaluacion"], "correcta")

    def test_get_devuelve_404_para_alerta_pendiente(self):
        self.service.get_alert.return_value = SimpleNamespace(evaluacion=None)

        response = self.get()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "EVALUACION_NO_ENCONTRADA")

    def test_get_mapea_errores_de_alerta_y_persistencia(self):
        for error, expected_status, expected_code in (
            (AlertNotFound(ALERTA_ID), 404, "ALERTA_NO_ENCONTRADA"),
            (PersistenceUnavailable(), 503, "PERSISTENCE_UNAVAILABLE"),
        ):
            with self.subTest(expected_code=expected_code):
                self.service.get_alert.side_effect = error
                response = self.get()
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.data["error"]["code"], expected_code)

    def test_evaluacion_requiere_autenticacion(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(URL, {"evaluacion": "correcta"}, format="json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "AUTH_REQUIRED")
