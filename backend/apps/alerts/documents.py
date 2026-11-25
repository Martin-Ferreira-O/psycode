from .domain import (
    Alerta,
    Evaluacion,
    Trazabilidad,
    alerta_rehidratada,
    evaluacion_nueva,
    validar_alerta,
)

CAMPOS_ALERTA = (
    "alerta_id",
    "box",
    "tipo_riesgo",
    "nivel_severidad",
    "semaforo",
    "fecha_hora",
    "estado_evaluacion",
    "evaluacion",
    "sesion_id",
    "descripcion",
    "trazabilidad",
)
CAMPOS_PROHIBIDOS = frozenset(
    {
        "audio",
        "grabacion",
        "grabación",
        "transcripcion",
        "transcripción",
        "paciente",
        "nombre_paciente",
        "rut",
        "password",
        "token",
        "jwt",
        "correo",
    }
)


def alerta_a_documento(alerta: Alerta) -> dict:
    validar_alerta(alerta)
    return {
        "alerta_id": alerta.alerta_id,
        "box": alerta.box,
        "tipo_riesgo": alerta.tipo_riesgo,
        "nivel_severidad": int(alerta.nivel_severidad),
        "semaforo": str(alerta.semaforo),
        "fecha_hora": alerta.fecha_hora,
        "estado_evaluacion": str(alerta.estado_evaluacion),
        "evaluacion": None if alerta.evaluacion is None else evaluacion_a_documento(alerta.evaluacion),
        "sesion_id": alerta.sesion_id,
        "descripcion": alerta.descripcion,
        **({"analisis": alerta.analisis} if alerta.analisis is not None else {}),
        "trazabilidad": {
            "registrada_en": alerta.trazabilidad.registrada_en,
            "actualizada_en": alerta.trazabilidad.actualizada_en,
            "origen": alerta.trazabilidad.origen,
        },
    }


def evaluacion_a_documento(evaluacion: Evaluacion) -> dict:
    return {
        "alerta_id": evaluacion.alerta_id,
        "evaluacion": str(evaluacion.evaluacion),
        "usuario_id": evaluacion.usuario_id,
        "usuario": evaluacion.usuario,
        "fecha_hora": evaluacion.fecha_hora,
        "estado_evaluacion": str(evaluacion.estado_evaluacion),
    }


def documento_a_alerta(documento: dict) -> Alerta:
    if CAMPOS_PROHIBIDOS.intersection(documento):
        raise ValueError("El documento contiene campos que no deben almacenarse.")
    evaluacion = documento.get("evaluacion")
    trazabilidad = documento["trazabilidad"]
    return alerta_rehidratada(
        alerta_id=documento["alerta_id"],
        box=documento["box"],
        tipo_riesgo=documento["tipo_riesgo"],
        nivel_severidad=int(documento["nivel_severidad"]),
        semaforo=documento["semaforo"],
        fecha_hora=documento["fecha_hora"],
        estado_evaluacion=documento["estado_evaluacion"],
        evaluacion=None if evaluacion is None else evaluacion_nueva(
            alerta_id=evaluacion["alerta_id"],
            resultado=evaluacion["evaluacion"],
            usuario_id=evaluacion["usuario_id"],
            usuario=evaluacion["usuario"],
            fecha_hora=evaluacion["fecha_hora"],
        ),
        sesion_id=documento["sesion_id"],
        descripcion=documento.get("descripcion"),
        analisis=documento.get("analisis"),
        trazabilidad=Trazabilidad(
            registrada_en=trazabilidad["registrada_en"],
            actualizada_en=trazabilidad["actualizada_en"],
            origen=trazabilidad["origen"],
        ),
    )
