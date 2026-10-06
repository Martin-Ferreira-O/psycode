from unittest.mock import MagicMock
from django.test import SimpleTestCase

from .domain import NotificationPayload, NotificationResult, AttemptResult, INDICADORES_RIESGO
from .ports import NotificationChannelClient
from .services import NotificationService


class NotificationsTestCase(SimpleTestCase):
    def setUp(self):
        self.mock_teams = MagicMock(spec=NotificationChannelClient)
        self.mock_teams.nombre_canal = "teams"

        self.mock_email = MagicMock(spec=NotificationChannelClient)
        self.mock_email.nombre_canal = "email"

        self.service = NotificationService(
            teams_client=self.mock_teams,
            email_client=self.mock_email,
            enabled=True,
        )

        self.payload_alto = NotificationPayload(
            nivel_riesgo="ALTO",
            tipo_riesgo="Riesgo suicida",
            box="Box 03",
            fecha_hora="14:37",
        )

    def test_nulo_o_sin_riesgo_no_notifica(self):
        payload_nulo = NotificationPayload(
            nivel_riesgo="NULO",
            tipo_riesgo="Ninguno",
            box="Box 01",
            fecha_hora="10:00",
        )
        res = self.service.notify_alert("ALT-001", payload_nulo)
        self.assertFalse(res.enviado)
        self.assertEqual(res.motivo_omision, "NULO_O_SIN_RIESGO")
        self.mock_teams.send.assert_not_called()
        self.mock_email.send.assert_not_called()

    def test_formato_compacto_teams(self):
        resumen = self.payload_alto.formatear_resumen_teams()
        self.assertEqual(resumen, "🔴 ALTO · Riesgo suicida · Box 03 · 14:37")

    def test_envio_exitoso_teams_no_activa_correo(self):
        self.mock_teams.send.return_value = AttemptResult("teams", True, 95.0, None)

        res = self.service.notify_alert("ALT-002", self.payload_alto)
        self.assertTrue(res.enviado)
        self.assertEqual(res.canal_exitoso, "teams")
        self.mock_teams.send.assert_called_once()
        self.mock_email.send.assert_not_called()

    def test_fallback_a_correo_cuando_teams_falla(self):
        self.mock_teams.send.return_value = AttemptResult("teams", False, 150.0, "Timeout")
        self.mock_email.send.return_value = AttemptResult("email", True, 80.0, None)

        res = self.service.notify_alert("ALT-003", self.payload_alto)
        self.assertTrue(res.enviado)
        self.assertEqual(res.canal_exitoso, "email")
        self.mock_teams.send.assert_called_once()
        self.mock_email.send.assert_once if hasattr(self.mock_email.send, "assert_once") else self.mock_email.send.assert_called_once()

    def test_fallo_doble_mantiene_alerta_pendiente(self):
        self.mock_teams.send.return_value = AttemptResult("teams", False, 120.0, "ConexionRechazada")
        self.mock_email.send.return_value = AttemptResult("email", False, 90.0, "SMTPError")

        res = self.service.notify_alert("ALT-004", self.payload_alto)
        self.assertFalse(res.enviado)
        self.assertEqual(res.motivo_omision, "FALLO_DOBLE_CANALES")