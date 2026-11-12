"""Tipos y reglas de alerts; sin dependencias de infraestructura."""

from __future__ import annotations
import unicodedata 

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final
from uuid import UUID


class DomainError(ValueError):
    """Dato de dominio inválido. La capa de aplicación lo traduce al contrato HTTP."""


class Semaforo(StrEnum):
    """Semáforo operativo derivado del nivel 1–3. No es una escala diagnóstica."""

    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"


class EstadoEvaluacion(StrEnum):
    """Estado persistido de la alerta. `pendiente` no es un valor de evaluación registrable."""

    PENDIENTE = "pendiente"
    CORRECTA = "correcta"
    FALSO_POSITIVO = "falso_positivo"
    NEUTRO = "neutro"


EVALUACIONES_REGISTRABLES: Final[frozenset[EstadoEvaluacion]] = frozenset(
    {
        EstadoEvaluacion.CORRECTA,
        EstadoEvaluacion.FALSO_POSITIVO,
        EstadoEvaluacion.NEUTRO,
    }
)

SEVERIDAD_MIN: Final[int] = 1
SEVERIDAD_MAX: Final[int] = 3
BOX_LONGITUD: Final[tuple[int, int]] = (1, 64)
TIPO_RIESGO_LONGITUD: Final[tuple[int, int]] = (1, 100)
DESCRIPCION_MAX: Final[int] = 500
ORIGEN_LONGITUD: Final[tuple[int, int]] = (1, 100)
USUARIO_LONGITUD: Final[tuple[int, int]] = (1, 150)
ORIGEN_PRUEBA_AUDIO: Final[str] = "analysis.audio-test/1.0"

# Escala operativa del proyecto: un nivel por cada semáforo.
_SEMAFORO_POR_SEVERIDAD: Final[dict[int, Semaforo]] = {
    1: Semaforo.BAJO,
    2: Semaforo.MEDIO,
    3: Semaforo.ALTO,
}


def semaforo_desde_severidad(nivel_severidad: int) -> Semaforo:
    """Única fuente del semáforo. Un valor enviado por el llamador no es autoridad."""
    if isinstance(nivel_severidad, bool) or not isinstance(nivel_severidad, int):
        raise DomainError("nivel_severidad debe ser un entero 1–3, no un booleano ni otro tipo.")
    try:
        return _SEMAFORO_POR_SEVERIDAD[nivel_severidad]
    except KeyError as exc:
        raise DomainError("nivel_severidad debe estar entre 1 y 3 inclusive.") from exc


def es_revisada(estado: EstadoEvaluacion) -> bool:
    return estado in EVALUACIONES_REGISTRABLES


def normalizar_uuid(valor: object, campo: str) -> str:
    """UUID canónico en minúsculas con guiones. Es el identificador público, no un ObjectId."""
    if isinstance(valor, UUID):
        return str(valor)
    if not isinstance(valor, str) or not valor.strip():
        raise DomainError(f"{campo} debe ser un UUID canónico.")
    try:
        return str(UUID(valor.strip()))
    except ValueError as exc:
        raise DomainError(f"{campo} debe ser un UUID canónico.") from exc


def _texto_obligatorio(valor: object, campo: str, limites: tuple[int, int]) -> str:
    if not isinstance(valor, str):
        raise DomainError(f"{campo} debe ser una cadena.")
    texto = valor.strip()
    minimo, maximo = limites
    if not minimo <= len(texto) <= maximo:
        raise DomainError(f"{campo} debe tener entre {minimo} y {maximo} caracteres.")
    return texto


def _descripcion(valor: object) -> str | None:
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise DomainError("descripcion debe ser una cadena o null.")
    texto = unicodedata.normalize("NFC", valor)
    texto = " ".join(texto.split())
    if not texto:
        return None
    if len(texto) > DESCRIPCION_MAX:
        raise DomainError(f"descripcion no puede superar {DESCRIPCION_MAX} caracteres.")
    return texto


def _utc(valor: object, campo: str) -> datetime:
    if not isinstance(valor, datetime):
        raise DomainError(f"{campo} debe ser una fecha/hora UTC.")
    if valor.tzinfo is None:
        raise DomainError(f"{campo} debe incluir zona horaria UTC.")
    return valor.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Trazabilidad:
    registrada_en: datetime
    actualizada_en: datetime
    origen: str


@dataclass(frozen=True, slots=True)
class Evaluacion:
    alerta_id: str
    evaluacion: EstadoEvaluacion
    usuario_id: str
    usuario: str
    fecha_hora: datetime
    estado_evaluacion: EstadoEvaluacion


@dataclass(frozen=True, slots=True)
class Alerta:
    """Documento de negocio de la colección `alerts`. `_id` de MongoDB no forma parte del dominio."""

    alerta_id: str
    box: str
    tipo_riesgo: str
    nivel_severidad: int
    semaforo: Semaforo
    fecha_hora: datetime
    estado_evaluacion: EstadoEvaluacion
    evaluacion: Evaluacion | None
    sesion_id: str
    descripcion: str | None
    trazabilidad: Trazabilidad

    @property
    def es_prueba(self) -> bool:
        return self.trazabilidad.origen == ORIGEN_PRUEBA_AUDIO


def trazabilidad_nueva(origen: object, instante: datetime) -> Trazabilidad:
    momento = _utc(instante, "trazabilidad.registrada_en")
    return Trazabilidad(
        registrada_en=momento,
        actualizada_en=momento,
        origen=_texto_obligatorio(origen, "origen", ORIGEN_LONGITUD),
    )


def evaluacion_nueva(
    *,
    alerta_id: object,
    resultado: object,
    usuario_id: object,
    usuario: object,
    fecha_hora: object,
) -> Evaluacion:
    estado = _estado_registrable(resultado)
    return Evaluacion(
        alerta_id=normalizar_uuid(alerta_id, "alerta_id"),
        evaluacion=estado,
        usuario_id=normalizar_uuid(usuario_id, "usuario_id"),
        usuario=_texto_obligatorio(usuario, "usuario", USUARIO_LONGITUD),
        fecha_hora=_utc(fecha_hora, "evaluacion.fecha_hora"),
        estado_evaluacion=estado,
    )


def alerta_nueva(
    *,
    alerta_id: object,
    box: object,
    tipo_riesgo: object,
    nivel_severidad: object,
    fecha_hora: object,
    sesion_id: object,
    origen: object,
    descripcion: object = None,
    registrada_en: object,
) -> Alerta:
    """Alta interna: pendiente, sin evaluación, semáforo derivado. El llamador no aporta estado."""
    severidad = _severidad(nivel_severidad)
    identificador = normalizar_uuid(alerta_id, "alerta_id")
    momento_registro = _utc(registrada_en, "trazabilidad.registrada_en")
    alerta = Alerta(
        alerta_id=identificador,
        box=_texto_obligatorio(box, "box", BOX_LONGITUD),
        tipo_riesgo=_texto_obligatorio(tipo_riesgo, "tipo_riesgo", TIPO_RIESGO_LONGITUD),
        nivel_severidad=severidad,
        semaforo=semaforo_desde_severidad(severidad),
        fecha_hora=_utc(fecha_hora, "fecha_hora"),
        estado_evaluacion=EstadoEvaluacion.PENDIENTE,
        evaluacion=None,
        sesion_id=normalizar_uuid(sesion_id, "sesion_id"),
        descripcion=_descripcion(descripcion),
        trazabilidad=trazabilidad_nueva(origen, momento_registro),
    )
    validar_alerta(alerta)
    return alerta


def parse_estado_evaluacion(valor: object) -> EstadoEvaluacion:
    if isinstance(valor, EstadoEvaluacion):
        return valor
    if isinstance(valor, str):
        try:
            return EstadoEvaluacion(valor)
        except ValueError:
            pass
    raise DomainError("estado_evaluacion inválido.")


def parse_semaforo(valor: object) -> Semaforo:
    if isinstance(valor, Semaforo):
        return valor
    if isinstance(valor, str):
        try:
            return Semaforo(valor)
        except ValueError:
            pass
    raise DomainError("semaforo inválido.")


def alerta_rehidratada(
    *,
    alerta_id: object,
    box: object,
    tipo_riesgo: object,
    nivel_severidad: object,
    semaforo: object,
    fecha_hora: object,
    estado_evaluacion: object,
    evaluacion: Evaluacion | None,
    sesion_id: object,
    descripcion: object,
    trazabilidad: Trazabilidad,
) -> Alerta:
    """Reconstruye una alerta ya persistida. No cambia semáforo ni estado: solo valida invariantes."""
    alerta = Alerta(
        alerta_id=normalizar_uuid(alerta_id, "alerta_id"),
        box=_texto_obligatorio(box, "box", BOX_LONGITUD),
        tipo_riesgo=_texto_obligatorio(tipo_riesgo, "tipo_riesgo", TIPO_RIESGO_LONGITUD),
        nivel_severidad=_severidad(nivel_severidad),
        semaforo=parse_semaforo(semaforo),
        fecha_hora=_utc(fecha_hora, "fecha_hora"),
        estado_evaluacion=parse_estado_evaluacion(estado_evaluacion),
        evaluacion=evaluacion,
        sesion_id=normalizar_uuid(sesion_id, "sesion_id"),
        descripcion=_descripcion(descripcion),
        trazabilidad=trazabilidad,
    )
    validar_alerta(alerta)
    return alerta


def alerta_con_evaluacion(alerta: Alerta, evaluacion: Evaluacion, actualizada_en: datetime) -> Alerta:
    if alerta.estado_evaluacion != EstadoEvaluacion.PENDIENTE or alerta.evaluacion is not None:
        raise DomainError("La alerta ya tiene una evaluación registrada.")
    if evaluacion.alerta_id != alerta.alerta_id:
        raise DomainError("La evaluación debe referir el mismo alerta_id.")
    momento = _utc(actualizada_en, "trazabilidad.actualizada_en")
    if momento < alerta.trazabilidad.registrada_en:
        raise DomainError("trazabilidad.actualizada_en no puede ser anterior a registrada_en.")
    actualizada = Alerta(
        alerta_id=alerta.alerta_id,
        box=alerta.box,
        tipo_riesgo=alerta.tipo_riesgo,
        nivel_severidad=alerta.nivel_severidad,
        semaforo=alerta.semaforo,
        fecha_hora=alerta.fecha_hora,
        estado_evaluacion=evaluacion.estado_evaluacion,
        evaluacion=evaluacion,
        sesion_id=alerta.sesion_id,
        descripcion=alerta.descripcion,
        trazabilidad=Trazabilidad(
            registrada_en=alerta.trazabilidad.registrada_en,
            actualizada_en=momento,
            origen=alerta.trazabilidad.origen,
        ),
    )
    validar_alerta(actualizada)
    return actualizada


def validar_alerta(alerta: Alerta) -> None:
    """Invariantes que el validador de MongoDB no expresa por sí solo."""
    if alerta.semaforo != semaforo_desde_severidad(alerta.nivel_severidad):
        raise DomainError("semaforo debe derivarse de nivel_severidad; no se admite un valor contradictorio.")
    if alerta.estado_evaluacion == EstadoEvaluacion.PENDIENTE:
        if alerta.evaluacion is not None:
            raise DomainError("Una alerta pendiente no puede incrustar evaluacion.")
        return
    if alerta.evaluacion is None:
        raise DomainError("Una alerta revisada debe incrustar evaluacion.")
    if alerta.evaluacion.alerta_id != alerta.alerta_id:
        raise DomainError("evaluacion.alerta_id debe coincidir con alerta_id.")
    if alerta.evaluacion.evaluacion != alerta.estado_evaluacion:
        raise DomainError("estado_evaluacion debe coincidir con evaluacion.evaluacion.")
    if alerta.evaluacion.estado_evaluacion != alerta.evaluacion.evaluacion:
        raise DomainError("evaluacion.estado_evaluacion debe coincidir con evaluacion.evaluacion.")
    if alerta.trazabilidad.actualizada_en < alerta.trazabilidad.registrada_en:
        raise DomainError("trazabilidad.actualizada_en no puede ser anterior a registrada_en.")


def _severidad(valor: object) -> int:
    if isinstance(valor, bool) or isinstance(valor, float):
        raise DomainError("nivel_severidad debe ser un entero 1–3, no un booleano ni otro tipo.")
    if isinstance(valor, int):
        numero = valor
    elif type(valor).__name__ in {"Int32", "Int64"}:
        numero = int(valor)
    else:
        raise DomainError("nivel_severidad debe ser un entero 1–3, no un booleano ni otro tipo.")
    if not SEVERIDAD_MIN <= numero <= SEVERIDAD_MAX:
        raise DomainError("nivel_severidad debe estar entre 1 y 3 inclusive.")
    return numero


def _estado_registrable(valor: object) -> EstadoEvaluacion:
    if isinstance(valor, EstadoEvaluacion):
        estado = valor
    elif isinstance(valor, str):
        try:
            estado = EstadoEvaluacion(valor)
        except ValueError as exc:
            raise DomainError("evaluacion debe ser correcta, falso_positivo o neutro.") from exc
    else:
        raise DomainError("evaluacion debe ser correcta, falso_positivo o neutro.")
    if estado not in EVALUACIONES_REGISTRABLES:
        raise DomainError("evaluacion debe ser correcta, falso_positivo o neutro.")
    return estado
