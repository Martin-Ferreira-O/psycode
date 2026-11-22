from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from django.test import SimpleTestCase
from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904

from . import services
from .services import AgendaError, AgendaNotLoaded, AgendaService, SANTIAGO

WHEN = datetime(2026, 9, 24, 9, 30)
BOXES = ("box-3", "box-4", "box-5", "box-6", "box-7")


def row(**changes):
    values = dict(fecha="24/09/2026", hora="09:00", dur="01:00", estatus="REALIZADA")
    values.update(changes)
    return tuple(values.values())


class AgendaTests(SimpleTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root, self.serial = Path(directory.name), 0
        self.agenda = AgendaService()

    def workbook(self, rows=None, box=3, boxes=None, edit=None):
        book = Workbook()
        sheet = book.active
        if box is not None:
            sheet["A2"] = f"Clinica fisica: BOX DE ATENCION {box}"
        headers = {1: "FECHA", 3: "HORA", 4: "DUR", 7: "PACIENTE", 15: "SERV. DE ATENCION", 18: "ESTATUS"}
        if boxes is not None:
            headers[15] = "CLINICA FISICA"
        for column, value in headers.items():
            sheet.cell(7, column, value)
        for index, values in enumerate([row()] if rows is None else rows, 8):
            for column, value in zip((1, 3, 4, 18), values):
                sheet.cell(index, column, value)
            sheet.cell(index, 7, "PERSONAL_FICTICIO")
            sheet.cell(index, 15, boxes[index - 8] if boxes is not None else "SERVICIO_FICTICIO")
        if edit:
            edit(book)
        self.serial += 1
        path = self.root / f"agenda_{self.serial}.xlsx"
        book.save(path)
        book.close()
        return path

    def test_read_query_and_privacy(self):
        path = self.workbook([row(), (None,) * 4], edit=lambda book: setattr(book.active["O8"], "value", "=1+2"))
        original = path.read_bytes()
        report = self.agenda.load_excel(path)
        item, = self.agenda.records
        self.assertEqual((report.aceptadas, report.rechazadas, report.filas_vacias), (1, (), 1))
        self.assertEqual((item.box, item.fecha, item.hora_inicio.hour, item.duracion, item.hora_termino.hour),
                         ("box-3", date(2026, 9, 24), 9, timedelta(hours=1), 10))
        self.assertEqual(item.termino.isoformat(), "2026-09-24T10:00:00-03:00")
        for box in (3, "3", "box-03", "Box de atención 3"):
            self.assertTrue(self.agenda.is_busy(box, WHEN))
        for instant, busy in ((WHEN.replace(hour=8), False), (WHEN.replace(minute=0), True),
                              (WHEN.replace(minute=59), True), (WHEN.replace(hour=10, minute=0), False),
                              (WHEN.replace(day=25), False), (datetime(2026, 9, 24, 12, 30, tzinfo=timezone.utc), True)):
            self.assertEqual(self.agenda.is_busy(3, instant), busy)
        self.assertEqual(set(asdict(item)), {"box", "inicio", "duracion", "termino", "estatus"})
        self.assertNotIn("FICTICIO", repr(report) + repr(self.agenda.records))
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(AgendaNotLoaded):
            self.agenda.is_busy(4, WHEN)

    def test_boxes_and_statuses(self):
        boxes = [f"BOX DE ATENCION {box}" for box in range(1, 10)] + [
            "BOX TELEMATICO 3", "Sala espejo", None, "PERSONAL_FICTICIO", "=1+2", "#VALUE!"]
        report = self.agenda.load_excel(self.workbook([row() for _ in boxes], boxes=boxes))
        self.assertEqual((report.aceptadas, len(report.rechazadas)), (9, 6))
        self.assertEqual(report.boxes_actualizados, tuple(f"box-{n}" for n in range(1, 10)))
        self.assertEqual({entry.motivo for entry in report.rechazadas},
                         {"box_fuera_de_alcance", "box_invalido", "formula_no_admitida", "error_excel"})
        for box in (0, -1, "BOX TELEMATICO 3", "Sala espejo", True, 3.5, "paciente"):
            with self.subTest(box=box), self.assertRaises(AgendaError):
                self.agenda.is_busy(box, WHEN)
        statuses = [(s, True) for s in ("REALIZADA", "CONFIRMADA", "NO CONFIRMADA", "AGENDADA", "PENDIENTE")]
        statuses += [(s, False) for s in ("CANCELADA", "ANULADA", "NO ASISTIÓ", "NO ASISTIÓ ALUMNO", "NO ASISTIO PACIENTE")]
        for status, busy in statuses:
            with self.subTest(status=status):
                self.agenda.load_excel(self.workbook([row(estatus=status)]))
                self.assertEqual(self.agenda.is_busy(3, WHEN), busy)

    def test_invalid_rows_and_file_references(self):
        cases = [({"fecha": "31/02/2026"}, "fecha_invalida"), ({"hora": "25:00"}, "hora_invalida"),
                 ({"dur": "00:00"}, "duracion_invalida"), ({"dur": "-01:00"}, "duracion_invalida"),
                 ({"dur": "01:60"}, "duracion_invalida"), ({"estatus": "PERSONAL_FICTICIO"}, "estatus_desconocido"),
                 ({"fecha": None}, "campo_requerido_vacio"), ({"hora": "=1+2"}, "formula_no_admitida"),
                 ({"hora": "#VALUE!"}, "error_excel"),
                 ({"fecha": "06/09/2026", "hora": "00:30"}, "hora_local_inexistente"),
                 ({"fecha": "04/04/2026", "hora": "23:30"}, "hora_local_ambigua")]
        first = self.workbook([row(), *(row(**changes) for changes, _ in cases), row(hora="11:00")])
        second = self.workbook([row(hora="25:00")], box=4)
        report = self.agenda.load_excel([first, second])
        self.assertEqual(report.aceptadas, 2)
        self.assertEqual([entry.motivo for entry in report.rechazadas], [reason for _, reason in cases] + ["hora_invalida"])
        self.assertEqual((report.rechazadas[0].archivo, report.rechazadas[0].hoja, report.rechazadas[0].fila), (1, 1, 9))
        self.assertEqual((report.rechazadas[-1].archivo, report.rechazadas[-1].fila), (2, 8))
        self.assertNotIn("PERSONAL_FICTICIO", repr(report) + repr(self.agenda.records))
        self.assertNotIn(str(self.root), repr(report) + repr(vars(self.agenda)))

    def test_duplicates(self):
        report = self.agenda.load_excel(self.workbook([
            row(), row(estatus=" realizada "), row(estatus="CONFIRMADA"), row(hora="11:00")]))
        self.assertEqual((report.aceptadas, report.duplicadas), (2, 2))
        self.assertEqual([entry.motivo for entry in report.rechazadas], ["duplicada", "duplicada_estatus_conflictivo"])
        path = self.workbook(edit=lambda book: book.copy_worksheet(book.active))
        report = self.agenda.load_excel(path)
        self.assertEqual((report.aceptadas, report.duplicadas, report.rechazadas[0].hoja), (1, 1, 2))
        for statuses in (("CANCELADA", "CONFIRMADA"), ("CONFIRMADA", "CANCELADA")):
            report = self.agenda.load_excel(self.workbook([row(estatus=s) for s in statuses]))
            self.assertEqual((report.aceptadas, report.duplicadas), (1, 1))
            self.assertEqual(self.agenda.records[0].estatus, "CONFIRMADA")

    def test_native_excel_dates_and_elapsed_duration(self):
        formats = [(date(2026, 9, 24), time(9), timedelta(hours=1), 10),
                   (datetime(2026, 9, 24), .5, 1 / 24, 13), ("2026-09-24", "15:00:00", time(1), 16)]
        for day, start, duration, end_hour in formats:
            for mac_epoch in (False, True):
                with self.subTest(day=day, mac_epoch=mac_epoch):
                    edit = (lambda book: setattr(book, "epoch", CALENDAR_MAC_1904)) if mac_epoch else None
                    self.agenda.load_excel(self.workbook([row(fecha=day, hora=start, dur=duration)], edit=edit))
                    self.assertEqual(self.agenda.records[0].termino.hour, end_hour)
        for day, start, duration, end in (("24/09/2026", "23:30", "25:00", "2026-09-26T00:30:00-03:00"),
                                          ("05/09/2026", "23:30", "02:00", "2026-09-06T02:30:00-03:00"),
                                          ("04/04/2026", "22:30", "02:00", "2026-04-04T23:30:00-04:00")):
            with self.subTest(day=day):
                self.agenda.load_excel(self.workbook([row(fecha=day, hora=start, dur=duration)]))
                self.assertEqual(self.agenda.records[0].termino.isoformat(), end)
        self.assertTrue(self.agenda.is_busy(3, datetime(2026, 4, 4, 23, 15, tzinfo=SANTIAGO, fold=1)))
        self.assertFalse(self.agenda.is_busy(3, datetime(2026, 4, 4, 23, 30, tzinfo=SANTIAGO, fold=1)))

    def test_joint_and_separate_uploads_preserve_other_boxes(self):
        for together in (True, False):
            with self.subTest(together=together):
                self.agenda = AgendaService()
                paths = [self.workbook(box=box) for box in range(3, 8)]
                if together:
                    self.agenda.load_excel(paths)
                else:
                    for path in paths:
                        self.agenda.load_excel(path)
                self.assertTrue(all(self.agenda.is_busy(box, WHEN) for box in range(3, 8)))
                report = self.agenda.load_excel(self.workbook([row(hora="11:00")]))
                self.assertEqual((report.boxes_actualizados, len(self.agenda.records)), (("box-3",), 5))
                self.assertFalse(self.agenda.is_busy(3, WHEN))
                self.assertTrue(self.agenda.is_busy(3, WHEN.replace(hour=11)))
                self.agenda.load_excel(self.workbook([row(estatus="NO ASISTIO")]))
                self.assertFalse(self.agenda.is_busy(3, WHEN))
                self.assertTrue(all(self.agenda.is_busy(box, WHEN) for box in range(4, 8)))

    def test_invalid_loads_preserve_previous_agendas(self):
        self.agenda.load_excel([self.workbook(box=3), self.workbook(box=4)])
        previous = self.agenda.records
        update = self.workbook([row(hora="11:00")])
        corrupt = self.root / "invalid.xlsx"
        corrupt.write_bytes(b"invalid workbook")
        invalid = [[], [update, corrupt], [self.root / "missing.xlsx"], [update, self.workbook()]]
        for cell, value in (("A2", None), ("A7", "OTRA"), ("B7", "FECHA")):
            invalid.append([update, self.workbook(box=4, edit=lambda book, c=cell, v=value: setattr(book.active[c], "value", v))])
        invalid.append([self.workbook([], box=None, boxes=[])])
        invalid.append([self.workbook(edit=lambda book: book.create_sheet("Sin formato"))])
        for paths in invalid:
            with self.subTest(paths=paths), self.assertRaises(AgendaError):
                self.agenda.load_excel(paths)
            self.assertEqual(self.agenda.records, previous)

    def test_empty_updates_and_unloaded_boxes(self):
        with self.assertRaises(AgendaNotLoaded):
            self.agenda.is_busy(3, WHEN)
        for rows in ([], [row(dur="00:00")]):
            self.agenda.load_excel([self.workbook(), self.workbook(box=4)])
            report = self.agenda.load_excel(self.workbook(rows))
            self.assertEqual((report.aceptadas, report.boxes_actualizados), (0, ("box-3",)))
            self.assertFalse(self.agenda.is_busy(3, WHEN))
            self.assertTrue(self.agenda.is_busy(4, WHEN))
            with self.assertRaises(AgendaNotLoaded):
                self.agenda.is_busy(5, WHEN)

    def test_multi_box_report_updates_only_identified_boxes(self):
        self.agenda.load_excel([self.workbook(box=box) for box in range(3, 8)])
        path = self.workbook([row(hora="11:00"), row(hora="12:00")], boxes=["BOX DE ATENCION 3", "BOX DE ATENCION 5"])
        report = self.agenda.load_excel(path)
        self.assertEqual(report.boxes_actualizados, ("box-3", "box-5"))
        self.assertTrue(all(self.agenda.is_busy(box, WHEN) for box in (4, 6, 7)))
        self.assertTrue(all(not self.agenda.is_busy(box, WHEN) for box in (3, 5)))

    def test_simultaneous_uploads_preserve_boxes_and_previous_snapshot(self):
        self.agenda.load_excel(self.workbook())
        paths = [self.workbook([row(hora="11:00")], box=box) for box in range(3, 8)]
        read, barrier = services._read_workbook, Barrier(5)
        def synchronized_read(*args):
            result = read(*args)
            self.assertTrue(self.agenda.is_busy(3, WHEN))
            barrier.wait(5)
            return result
        with patch.object(services, "_read_workbook", side_effect=synchronized_read), ThreadPoolExecutor(5) as pool:
            list(pool.map(self.agenda.load_excel, paths))
        self.assertEqual({item.box for item in self.agenda.records}, set(BOXES))
        self.assertFalse(self.agenda.is_busy(3, WHEN))
        self.assertTrue(all(self.agenda.is_busy(box, WHEN.replace(hour=11)) for box in range(3, 8)))
