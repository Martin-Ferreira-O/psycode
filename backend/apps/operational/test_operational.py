from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APITestCase

from backend.apps.accounts.models import Role, User
from backend.apps.agenda.services import AgendaError, AgendaService
from backend.config.composition import capture_authorization_service

from .capture_authorization import (
    ORIGIN_AGENDA,
    ORIGIN_CLINICAL_SCHEDULE,
    ORIGIN_NONE,
    CaptureAuthorizationService,
)
from .models import OperationalConfiguration
from .services import OperationalService

SANTIAGO = ZoneInfo("America/Santiago")


def _build_excel(root: Path, serial: int, box: int = 3, rows: list[tuple] | None = None) -> Path:
    book = Workbook()
    sheet = book.active
    sheet["A2"] = f"Clinica fisica: BOX DE ATENCION {box}"
    headers = {1: "FECHA", 3: "HORA", 4: "DUR", 7: "PACIENTE", 15: "SERV. DE ATENCION", 18: "ESTATUS"}
    for col, val in headers.items():
        sheet.cell(7, col, val)
    default_rows = [("19/10/2026", "09:00", "01:00", "CONFIRMADA")]
    for idx, values in enumerate(default_rows if rows is None else rows, 8):
        for col, val in zip((1, 3, 4, 18), values):
            sheet.cell(idx, col, val)
        sheet.cell(idx, 7, "PACIENTE_CONFIDENCIAL_NO_USAR")
        sheet.cell(idx, 15, "PSICOLOGIA_CLINICA")
    path = root / f"citas_{serial}.xlsx"
    book.save(path)
    book.close()
    return path


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
        self.client.credentials()
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

        dt_dentro = datetime(2026, 10, 19, 10, 0, tzinfo=SANTIAGO)
        res_dentro = service.validate_current_operation(dt_dentro)
        self.assertTrue(res_dentro["authorized"])

        dt_fuera = datetime(2026, 10, 19, 20, 0, tzinfo=SANTIAGO)
        res_fuera = service.validate_current_operation(dt_fuera)
        self.assertFalse(res_fuera["authorized"])


class CaptureAuthorizationIntegrationTests(APITestCase):
    """Pruebas de aceptación para SCRUM-70: Integrar agenda y horario clínico."""

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.serial = 0

        self.admin = User.objects.create_user(
            username="admin_scrum70", email="admin70@clinica.cl", password="Password-Segura-123", role=Role.ADMIN
        )
        OperationalService().update_config(self.admin, {
            "enabled_days": [0, 1, 2, 3, 4],  # Lunes a Viernes
            "open_time": "08:00",
            "close_time": "18:00",
            "primary_email": "alertas@clinica.cl",
            "backup_email": "sergio@clinica.cl",
        })
        self.agenda = AgendaService()
        self.auth_service = CaptureAuthorizationService(agenda_service=self.agenda)

    def _load_box(self, box: int = 3, rows: list[tuple] | None = None):
        self.serial += 1
        path = _build_excel(self.root, self.serial, box=box, rows=rows)
        self.agenda.load_excel(path)

    def test_autoriza_cuando_box_tiene_cita_vigente_dentro_de_horario_clinico(self):
        self._load_box(3, [("19/10/2026", "09:00", "01:00", "CONFIRMADA")])
        when = datetime(2026, 10, 19, 9, 30, tzinfo=SANTIAGO)

        result = self.auth_service.evaluate_box(3, when)
        self.assertTrue(result.authorized)
        self.assertEqual(result.box, "box-3")
        self.assertEqual(result.origen, ORIGIN_AGENDA)
        self.assertEqual(result.inicio, datetime(2026, 10, 19, 9, 0, tzinfo=SANTIAGO))
        self.assertEqual(result.termino, datetime(2026, 10, 19, 10, 0, tzinfo=SANTIAGO))
        self.assertEqual(result.estado_autorizacion, "AUTORIZADO")

        # Verifica contrato de salida para SCRUM-71 y ausencia de datos de pacientes o agenda_id
        payload = result.to_dict()
        self.assertEqual(
            set(payload.keys()),
            {"box", "authorized", "autorizado", "estado_autorizacion", "inicio", "termino", "origen"},
        )
        self.assertNotIn("agenda_id", payload)
        self.assertNotIn("PACIENTE_CONFIDENCIAL_NO_USAR", repr(result) + repr(payload))

    def test_deniega_cuando_agenda_cargada_sin_cita_o_cita_no_bloqueante(self):
        self._load_box(3, [
            ("19/10/2026", "09:00", "01:00", "CONFIRMADA"),
            ("19/10/2026", "11:00", "01:00", "CANCELADA"),
            ("19/10/2026", "12:00", "01:00", "NO ASISTIO PACIENTE"),
        ])
        # Sin cita a las 10:15
        res_libre = self.auth_service.evaluate_box("box-3", datetime(2026, 10, 19, 10, 15, tzinfo=SANTIAGO))
        self.assertFalse(res_libre.authorized)
        self.assertEqual(res_libre.origen, ORIGIN_AGENDA)
        self.assertIsNone(res_libre.inicio)
        self.assertIsNone(res_libre.termino)

        # Cita cancelada a las 11:30
        res_cancelada = self.auth_service.evaluate_box("box-3", datetime(2026, 10, 19, 11, 30, tzinfo=SANTIAGO))
        self.assertFalse(res_cancelada.authorized)
        self.assertEqual(res_cancelada.origen, ORIGIN_AGENDA)

        # Cita con inasistencia a las 12:30
        res_inasistencia = self.auth_service.evaluate_box("box-3", datetime(2026, 10, 19, 12, 30, tzinfo=SANTIAGO))
        self.assertFalse(res_inasistencia.authorized)

    def test_respaldo_horario_clinico_cuando_agenda_no_disponible_y_tras_reinicio(self):
        when = datetime(2026, 10, 19, 10, 30, tzinfo=SANTIAGO)
        with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
            res = self.auth_service.evaluate_box(4, when)

        self.assertTrue(res.authorized)
        self.assertEqual(res.box, "box-4")
        self.assertEqual(res.origen, ORIGIN_CLINICAL_SCHEDULE)
        self.assertEqual(res.inicio, datetime(2026, 10, 19, 8, 0, tzinfo=SANTIAGO))
        self.assertEqual(res.termino, datetime(2026, 10, 19, 18, 0, tzinfo=SANTIAGO))
        self.assertEqual(audit_emit.call_count, 1)
        event = audit_emit.call_args.args[0]
        self.assertEqual(event["action"], "capture.authorization.fallback")
        self.assertEqual(event["error_code"], "AGENDA_NOT_AVAILABLE")

        # Si antes tenía agenda cargada y el proceso se reinicia (nueva instancia de servicio), vuelve a respaldo
        self._load_box(4, [("19/10/2026", "09:00", "01:00", "CONFIRMADA")])
        self.assertFalse(self.auth_service.evaluate_box(4, when).authorized)

        restarted_service = capture_authorization_service()
        res_after_restart = restarted_service.evaluate_box(4, when)
        self.assertTrue(res_after_restart.authorized)
        self.assertEqual(res_after_restart.origen, ORIGIN_CLINICAL_SCHEDULE)

    def test_deniega_si_no_existe_horario_clinico_vigente(self):
        self._load_box(3, [("19/10/2026", "20:00", "01:00", "CONFIRMADA")])

        # Fuera de horario clínico (20:30, clínica cierra a las 18:00)
        res_fuera_hora = self.auth_service.evaluate_box(3, datetime(2026, 10, 19, 20, 30, tzinfo=SANTIAGO))
        self.assertFalse(res_fuera_hora.authorized)
        self.assertIsNone(res_fuera_hora.inicio)
        self.assertIsNone(res_fuera_hora.termino)

        # Día domingo no habilitado (sin agenda tampoco autoriza respaldo)
        res_domingo = self.auth_service.evaluate_box(5, datetime(2026, 10, 25, 10, 0, tzinfo=SANTIAGO))
        self.assertFalse(res_domingo.authorized)

        # Sin horario clínico configurado en base de datos
        OperationalConfiguration.objects.filter(pk=1).update(enabled_days=[], open_time="", close_time="")
        res_sin_config = self.auth_service.evaluate_box(5, datetime(2026, 10, 19, 10, 0, tzinfo=SANTIAGO))
        self.assertFalse(res_sin_config.authorized)

    def test_deniega_sin_fila_de_configuracion_y_no_crea_horario_por_defecto(self):
        self._load_box(3)
        OperationalConfiguration.objects.all().delete()
        when = datetime(2026, 10, 19, 9, 30, tzinfo=SANTIAGO)

        # Box 3 tiene cita vigente; box 4 no tiene agenda disponible.
        for box in (3, 4):
            with self.subTest(box=box):
                result = self.auth_service.evaluate_box(box, when)
                self.assertFalse(result.authorized)
                self.assertIsNone(result.inicio)
                self.assertIsNone(result.termino)
                self.assertFalse(OperationalConfiguration.objects.exists())

    def test_recorta_ventana_de_cita_a_limites_del_horario_clinico(self):
        # Cita de 17:30 a 18:30, pero el horario clínico termina a las 18:00
        self._load_box(3, [("19/10/2026", "17:30", "01:00", "REALIZADA")])
        res = self.auth_service.evaluate_box(3, datetime(2026, 10, 19, 17, 45, tzinfo=SANTIAGO))
        self.assertTrue(res.authorized)
        self.assertEqual(res.inicio, datetime(2026, 10, 19, 17, 30, tzinfo=SANTIAGO))
        self.assertEqual(res.termino, datetime(2026, 10, 19, 18, 0, tzinfo=SANTIAGO))

    def test_informa_una_sola_transicion_por_cada_cambio_de_autorizacion(self):
        self._load_box(3, [("19/10/2026", "09:00", "01:00", "CONFIRMADA")])

        t_9_00 = datetime(2026, 10, 19, 9, 0, tzinfo=SANTIAGO)
        t_9_30 = datetime(2026, 10, 19, 9, 30, tzinfo=SANTIAGO)
        t_10_15 = datetime(2026, 10, 19, 10, 15, tzinfo=SANTIAGO)
        t_10_30 = datetime(2026, 10, 19, 10, 30, tzinfo=SANTIAGO)

        # Primera evaluación: emite transición inicial (AUTORIZADO)
        first = self.auth_service.evaluate_transition(3, t_9_00)
        self.assertIsNotNone(first)
        self.assertTrue(first.authorized)

        # Segunda evaluación dentro de la misma cita: sin cambio -> None
        second = self.auth_service.evaluate_transition(3, t_9_30)
        self.assertIsNone(second)

        # Tercera evaluación al terminar la cita: cambia a DENEGADO -> emite transición
        third = self.auth_service.evaluate_transition(3, t_10_15)
        self.assertIsNotNone(third)
        self.assertFalse(third.authorized)

        # Cuarta evaluación que sigue sin cita: sin cambio -> None
        fourth = self.auth_service.evaluate_transition(3, t_10_30)
        self.assertIsNone(fourth)

    def test_no_emite_transicion_si_solo_cambia_origen_de_denegacion(self):
        self._load_box(3, [])
        with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
            initial = self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 7, 59, tzinfo=SANTIAGO))
            self.assertIsNotNone(initial)
            self.assertFalse(initial.authorized)
            self.assertEqual(initial.origen, ORIGIN_CLINICAL_SCHEDULE)
            self.assertIsNone(self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 8, 0, tzinfo=SANTIAGO)))
            self.assertIsNone(self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 18, 0, tzinfo=SANTIAGO)))

        self.assertEqual(audit_emit.call_count, 1)
        self.assertEqual(audit_emit.call_args.args[0]["action"], "capture.authorization.transition")

    def test_no_emite_transicion_entre_citas_consecutivas_sin_interrupcion(self):
        self._load_box(3, [
            ("19/10/2026", "09:00", "01:00", "CONFIRMADA"),
            ("19/10/2026", "10:00", "01:00", "CONFIRMADA"),
        ])
        with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
            initial = self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 9, 59, tzinfo=SANTIAGO))
            self.assertTrue(initial.authorized)
            self.assertIsNone(self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 10, 0, tzinfo=SANTIAGO)))
            self.assertIsNone(self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 10, 59, tzinfo=SANTIAGO)))
            end = self.auth_service.evaluate_transition(3, datetime(2026, 10, 19, 11, 0, tzinfo=SANTIAGO))
            self.assertFalse(end.authorized)

        self.assertEqual(audit_emit.call_count, 2)

    def test_no_emite_transicion_al_recuperar_agenda_si_sigue_autorizado(self):
        when = datetime(2026, 10, 19, 9, 30, tzinfo=SANTIAGO)
        initial = self.auth_service.evaluate_transition(3, when)
        self.assertTrue(initial.authorized)
        self.assertEqual(initial.origen, ORIGIN_CLINICAL_SCHEDULE)

        self._load_box(3)
        with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
            self.assertIsNone(self.auth_service.evaluate_transition(3, when))
        audit_emit.assert_not_called()
        self.assertEqual(self.auth_service.evaluate_box(3, when).origen, ORIGIN_AGENDA)

        self._load_box(3, [])
        self.assertFalse(self.auth_service.evaluate_transition(3, when).authorized)

    def test_registra_nuevo_fallo_de_configuracion_tras_recuperacion_fuera_de_horario(self):
        config = OperationalConfiguration.objects.get(pk=1)
        outcomes = [RuntimeError("fallo inicial"), RuntimeError("fallo continuo"), config,
                    RuntimeError("nuevo fallo"), RuntimeError("nuevo fallo continuo")]
        times = [(10, 0), (10, 1), (20, 0), (20, 1), (20, 2)]
        with patch.object(self.auth_service, "config_loader", side_effect=outcomes):
            with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
                for hour, minute in times:
                    result = self.auth_service.evaluate_box(3, datetime(2026, 10, 19, hour, minute, tzinfo=SANTIAGO))
                    self.assertFalse(result.authorized)

        self.assertEqual(audit_emit.call_count, 2)
        for call in audit_emit.call_args_list:
            self.assertEqual(call.args[0]["error_code"], "CLINICAL_SCHEDULE_UNAVAILABLE")
            self.assertEqual(call.args[0]["outcome"], "failure")

    def test_no_repite_registro_de_respaldo_en_consultas_consecutivas(self):
        with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
            for minute in (0, 1, 2):
                result = self.auth_service.evaluate_box(3, datetime(2026, 10, 19, 10, minute, tzinfo=SANTIAGO))
                self.assertTrue(result.authorized)
                self.assertEqual(result.origen, ORIGIN_CLINICAL_SCHEDULE)

        self.assertEqual(audit_emit.call_count, 1)
        self.assertEqual(audit_emit.call_args.args[0]["error_code"], "AGENDA_NOT_AVAILABLE")

    def test_registra_fallos_de_agenda_y_usa_respaldo(self):
        when = datetime(2026, 10, 19, 11, 0, tzinfo=SANTIAGO)
        with patch.object(self.agenda, "is_busy", side_effect=RuntimeError("fallo interno")):
            with patch("backend.common.audit.AuditWriter.emit") as audit_emit:
                res = self.auth_service.evaluate_box(6, when)

        self.assertTrue(res.authorized)
        self.assertEqual(res.origen, ORIGIN_CLINICAL_SCHEDULE)
        self.assertEqual(audit_emit.call_count, 1)
        self.assertEqual(audit_emit.call_args.args[0]["error_code"], "AGENDA_QUERY_FAILED")

        # Box fuera de alcance (ej. box 1 o 9) lanza AgendaError
        with self.assertRaises(AgendaError):
            self.auth_service.evaluate_box(1, when)
