from datetime import datetime
from zoneinfo import ZoneInfo
from rest_framework import status
from rest_framework.test import APITestCase
from backend.apps.accounts.models import Role, User
from .services import OperationalService


class OperationalConfigTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_op", email="admin@clinica.cl", password="Password-Segura-123", role=Role.ADMIN
        )
        self.supervisor = User.objects.create_user(
            username="sup_op", email="sup@clinica.cl", password="Password-Segura-123", role=Role.SUPERVISOR
        )
        self.url = "/api/v1/configuracion-operativa"

    def test_actualizar_y_consultar_configuracion_como_admin(self):
        self.client.force_authenticate(user=self.admin)
        payload = {
            "enabled_days": [0, 1, 2, 3, 4],
            "open_time": "09:00",
            "close_time": "19:00",
            "primary_email": "cliente@clinica.cl",
            "backup_email": "sergio@clinica.cl",
        }
        res = self.client.put(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["primary_email"], "cliente@clinica.cl")
        self.assertEqual(res.data["data"]["backup_email"], "sergio@clinica.cl")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["timezone"], "America/Santiago")

    def test_supervisor_no_puede_consultar_ni_modificar(self):
        self.client.force_authenticate(user=self.supervisor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        payload = {"open_time": "08:00"}
        res = self.client.put(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_no_autenticado_rechazado(self):
        self.client.credentials()  # Limpia cualquier cabecera de autenticación previa
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validacion_horaria_america_santiago(self):
        service = OperationalService()
        service.update_config(self.admin, {
            "enabled_days": [0],  # Lunes
            "open_time": "08:00",
            "close_time": "18:00",
            "primary_email": "c@c.cl",
            "backup_email": "s@s.cl",
        })

        # Lunes a las 10:00 AM (dentro de horario)
        dt_dentro = datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo("America/Santiago"))
        res_dentro = service.validate_current_operation(dt_dentro)
        self.assertTrue(res_dentro["authorized"])

        # Lunes a las 20:00 PM (fuera de horario)
        dt_fuera = datetime(2026, 10, 19, 20, 0, tzinfo=ZoneInfo("America/Santiago"))
        res_fuera = service.validate_current_operation(dt_fuera)
        self.assertFalse(res_fuera["authorized"])