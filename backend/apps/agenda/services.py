from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import islice
import math
from pathlib import Path
import re
from threading import Lock
from typing import Iterable
import unicodedata
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from backend.common.boxes import is_box

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

SANTIAGO = ZoneInfo("America/Santiago")
UTC = timezone.utc
HEADERS = ("FECHA", "HORA", "DUR", "ESTATUS")
STATUSES = {"REALIZADA", "CONFIRMADA", "NO CONFIRMADA", "AGENDADA", "PENDIENTE",
            "NO ASISTIO", "NO ASISTIO ALUMNO", "NO ASISTIO PACIENTE", "CANCELADA", "ANULADA"}
NON_BLOCKING = {"CANCELADA", "ANULADA", "NO ASISTIO", "NO ASISTIO ALUMNO", "NO ASISTIO PACIENTE"}


class AgendaError(ValueError):
    pass


class WorkbookFormatError(AgendaError):
    pass


class AgendaNotLoaded(AgendaError):
    pass


@dataclass(frozen=True)
class Appointment:
    box: str
    inicio: datetime
    duracion: timedelta
    termino: datetime
    estatus: str

    @property
    def fecha(self):
        return self.inicio.date()

    @property
    def hora_inicio(self):
        return self.inicio.timetz()

    @property
    def hora_termino(self):
        return self.termino.timetz()


@dataclass(frozen=True)
class RejectedRow:
    hoja: int
    fila: int
    motivo: str
    archivo: int = 1


@dataclass(frozen=True)
class LoadReport:
    aceptadas: int
    rechazadas: tuple[RejectedRow, ...]
    filas_vacias: int
    boxes_actualizados: tuple[str, ...] = ()

    @property
    def duplicadas(self):
        return sum(row.motivo.startswith("duplicada") for row in self.rechazadas)


def _text(value):
    normalized = unicodedata.normalize("NFKD", value)
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).upper().split())


def _box(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise AgendaError("box_invalido")
    label = _text(str(value))
    if label in {"SALA ESPEJO", "SALA-ESPEJO"}:
        return "sala-espejo"
    telematic = re.fullmatch(r"BOX[ -]+TELEMATICO[ #\-]*(\d{1,9})", label)
    if telematic:
        if int(telematic[1]) <= 0:
            raise AgendaError("box_invalido")
        return f"box-telematico-{int(telematic[1])}"
    match = re.fullmatch(r"(?:BOX(?: DE ATENCION)?[ #\-]*)?(\d{1,9})", label)
    if not match or int(match[1]) <= 0:
        raise AgendaError("box_invalido")
    return f"box-{int(match[1])}"


def _local_datetime(value):
    if not isinstance(value, datetime):
        raise AgendaError("fecha_hora_invalida")
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC).astimezone(SANTIAGO)
    candidates = {}
    for fold in (0, 1):
        candidate = value.replace(tzinfo=SANTIAGO, fold=fold)
        instant = candidate.astimezone(UTC)
        if instant.astimezone(SANTIAGO).replace(tzinfo=None) == value:
            candidates[instant] = candidate
    if len(candidates) != 1:
        raise AgendaError("hora_local_ambigua" if candidates else "hora_local_inexistente")
    return next(iter(candidates.values()))


def _date(value):
    if isinstance(value, datetime):
        if value.time() != time() or value.tzinfo is not None:
            raise AgendaError("fecha_invalida")
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                pass
    raise AgendaError("fecha_invalida")


def _time(value):
    if isinstance(value, time) and value.tzinfo is None:
        return value
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value < 1:
        seconds = round(value * 86400, 6)
        if seconds < 86400:
            return (datetime(2000, 1, 1) + timedelta(seconds=seconds)).time()
    if isinstance(value, str) and re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", value.strip()):
        try:
            return time.fromisoformat(value.strip())
        except ValueError:
            pass
    raise AgendaError("hora_invalida")


def _duration(value):
    if isinstance(value, time) and value.tzinfo is None:
        value = timedelta(hours=value.hour, minutes=value.minute, seconds=value.second,
                          microseconds=value.microsecond)
    elif type(value) in (int, float) and math.isfinite(value):
        value = timedelta(days=value)
    elif isinstance(value, str) and (match := re.fullmatch(r"(\d{1,6}):([0-5]\d)(?::([0-5]\d))?", value.strip())):
        value = timedelta(hours=int(match[1]), minutes=int(match[2]), seconds=int(match[3] or 0))
    if not isinstance(value, timedelta) or value <= timedelta():
        raise AgendaError("duracion_invalida")
    return value


def _cell_value(cell):
    if cell.data_type == "f":
        raise AgendaError("formula_no_admitida")
    if cell.data_type == "e":
        raise AgendaError("error_excel")
    return cell.value


def _empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _appointment(box, cells):
    values = [_cell_value(cell) for cell in cells]
    if any(_empty(value) for value in values):
        raise AgendaError("campo_requerido_vacio")
    day, start, duration, status = values
    status = _text(status) if isinstance(status, str) else ""
    if status not in STATUSES:
        raise AgendaError("estatus_desconocido")
    start = _local_datetime(datetime.combine(_date(day), _time(start)))
    duration = _duration(duration)
    end = (start.astimezone(UTC) + duration).astimezone(SANTIAGO)
    return Appointment(box, start, duration, end, status)


def _sheet_layout(rows):
    header = list(islice(rows, 7))
    if len(header) != 7:
        raise WorkbookFormatError("El reporte requiere títulos en la fila 7.")
    titles = [_text(cell.value) if isinstance(cell.value, str) and cell.data_type != "f" else ""
              for cell in header[6]]
    if any(titles.count(name) != 1 for name in HEADERS):
        raise WorkbookFormatError("La fila 7 requiere FECHA, HORA, DUR y ESTATUS sin repetir.")
    columns = [titles.index(name) for name in HEADERS]
    box_columns = [index for index, title in enumerate(titles) if title in {"CLINICA FISICA", "BOX"}]
    if len(box_columns) > 1:
        raise WorkbookFormatError("Hay más de una columna de box en la fila 7.")
    box_column = box_columns[0] if box_columns else None
    box = None
    if box_column is None:
        box_cell = header[1][0]
        label = _text(box_cell.value) if isinstance(box_cell.value, str) else ""
        if box_cell.data_type == "f" or not label.startswith("CLINICA FISICA:"):
            raise WorkbookFormatError("Falta una columna CLINICA FISICA o BOX, o un box en la cabecera A2.")
        try:
            box = _box(label.partition(":")[2].strip())
        except AgendaError:
            raise WorkbookFormatError("Box inválido en la cabecera del reporte.") from None
    return box, columns, box_column


def _read_workbook(workbook, file_number=1):
    unique, rejected, boxes, empty_rows = {}, [], set(), 0
    if not workbook.worksheets:
        raise WorkbookFormatError("El archivo no contiene hojas de agenda.")
    for sheet_number, sheet in enumerate(workbook.worksheets, 1):
        rows = iter(sheet.iter_rows())
        box, columns, box_column = _sheet_layout(rows)
        if is_box(box):
            boxes.add(box)
        for row_number, row in enumerate(rows, 8):
            cells = [row[column] for column in columns]
            if all(_empty(cell.value) for cell in cells):
                empty_rows += 1
                continue
            try:
                row_box = box
                if box_column is not None:
                    row_box = _box(_cell_value(row[box_column]))
                if not is_box(row_box):
                    raise AgendaError("box_fuera_de_alcance")
                boxes.add(row_box)
                item = _appointment(row_box, cells)
                key = (item.box, item.inicio.astimezone(UTC), item.termino.astimezone(UTC))
                if key in unique:
                    previous, previous_sheet, previous_row = unique[key]
                    reason = "duplicada" if previous.estatus == item.estatus else "duplicada_estatus_conflictivo"
                    if previous.estatus in NON_BLOCKING and item.estatus not in NON_BLOCKING:
                        rejected.append(RejectedRow(previous_sheet, previous_row, reason, file_number))
                    else:
                        rejected.append(RejectedRow(sheet_number, row_number, reason, file_number))
                        continue
                unique[key] = (item, sheet_number, row_number)
            except AgendaError as exc:
                rejected.append(RejectedRow(sheet_number, row_number, str(exc), file_number))
            except OverflowError:
                rejected.append(RejectedRow(sheet_number, row_number, "fecha_o_duracion_fuera_de_rango", file_number))
    if not boxes and not rejected:
        raise WorkbookFormatError("No se identifica un box para actualizar; indica el box en la cabecera A2.")
    grouped = {box: [] for box in sorted(boxes)}
    for item, _, _ in sorted(unique.values(), key=lambda entry: entry[0].inicio.astimezone(UTC)):
        grouped[item.box].append(item)
    rejected.sort(key=lambda item: (item.hoja, item.fila))
    return {box: tuple(items) for box, items in grouped.items()}, rejected, empty_rows


class AgendaService:
    def __init__(self):
        self._by_box: dict[str, tuple[Appointment, ...]] = {}
        self._lock = Lock()

    @property
    def records(self):
        by_box = self._by_box
        return tuple(item for box in sorted(by_box) for item in by_box[box])

    def load_excel(self, paths: str | Path | Iterable[str | Path]) -> LoadReport:
        paths = (paths,) if isinstance(paths, (str, Path)) or hasattr(paths, "read") else tuple(paths)
        if not paths:
            raise AgendaError("Debe indicar al menos un archivo Excel.")
        incoming, rejected, empty_rows = {}, [], 0
        for file_number, path in enumerate(paths, 1):
            try:
                with closing(load_workbook(path, read_only=True, data_only=False, keep_links=False)) as workbook:
                    grouped, file_rejected, file_empty_rows = _read_workbook(workbook, file_number)
            except WorkbookFormatError as exc:
                raise WorkbookFormatError(f"Archivo {file_number}: {exc}") from None
            except (OSError, BadZipFile, InvalidFileException, ParseError, KeyError, ValueError, TypeError, IndexError):
                raise WorkbookFormatError(f"No se pudo leer el archivo {file_number} o su estructura es inválida.") from None
            if incoming.keys() & grouped.keys():
                raise AgendaError("Más de un archivo actualiza el mismo box en esta carga.")
            incoming.update(grouped)
            rejected.extend(file_rejected)
            empty_rows += file_empty_rows
        with self._lock:
            self._by_box = {**self._by_box, **incoming}
        return LoadReport(sum(map(len, incoming.values())), tuple(rejected), empty_rows, tuple(sorted(incoming)))

    def is_busy(self, box: str | int, when: datetime) -> bool:
        box, instant = _box(box), _local_datetime(when).astimezone(UTC)
        if not is_box(box):
            raise AgendaError("box_fuera_de_alcance")
        by_box = self._by_box
        if box not in by_box:
            raise AgendaNotLoaded("Debe cargar la agenda de este box antes de consultar ocupación.")
        return any(item.estatus not in NON_BLOCKING
                   and item.inicio.astimezone(UTC) <= instant < item.termino.astimezone(UTC)
                   for item in by_box[box])


    def replace_boxes(self, by_box):
        if any(not is_box(box) for box in by_box):
            raise AgendaError("box_fuera_de_alcance")
        with self._lock:
            self._by_box = {**self._by_box, **{box: tuple(items) for box, items in by_box.items()}}


    def load_smile_json(self, raw, *, boxes, agenda_date, smile_ids=None):
        import json
        try:
            rows = json.loads(raw)
            day = date.fromisoformat(agenda_date)
            if not isinstance(rows, list) or len(rows) > 100000 or not boxes or any(not is_box(box) for box in boxes):
                raise ValueError()
            grouped = {box: [] for box in boxes}
            seen = set()
            keys = {"smile_cita_id", "box", "smile_box_id", "fecha", "hora_inicio", "duracion_minutos", "estado", "codigo_estado"}
            for row in rows:
                if not isinstance(row, dict) or set(row) != keys or type(row["box"]) is not int:
                    raise ValueError()
                box = f"box-{row['box']}"
                if (box not in grouped or not isinstance(row["smile_box_id"], str)
                        or not re.fullmatch(r"[1-9][0-9]{0,11}", row["smile_box_id"])
                        or (smile_ids is not None and smile_ids.get(box) != row["smile_box_id"])
                        or (smile_ids is None and 3 <= row["box"] <= 7 and row["smile_box_id"] != str(row["box"] + 5))):
                    raise ValueError()
                if any(not isinstance(row[k], str) or not row[k] or len(row[k]) > 256
                       for k in ("smile_cita_id", "codigo_estado", "estado", "fecha", "hora_inicio")):
                    raise ValueError()
                if (box, row["smile_cita_id"]) in seen or date.fromisoformat(row["fecha"]) != day:
                    raise ValueError()
                seen.add((box, row["smile_cita_id"]))
                minutes = row["duracion_minutos"]
                status = _text(row["estado"])
                if type(minutes) is not int or not 0 <= minutes <= 59999 or status not in STATUSES:
                    raise ValueError()
                start = _local_datetime(datetime.combine(day, _time(row["hora_inicio"])))
                duration = timedelta(minutes=minutes)
                grouped[box].append(Appointment(box, start, duration, (start.astimezone(UTC) + duration).astimezone(SANTIAGO), status))
        except (ValueError, TypeError, KeyError, OverflowError):
            raise AgendaError("Reporte Smile JSON inválido; se conserva la agenda anterior.") from None
        self.replace_boxes(grouped)
        return LoadReport(len(rows), (), 0, tuple(sorted(boxes)))
