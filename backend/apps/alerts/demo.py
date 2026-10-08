"""Alertas sintéticas de desarrollo. Sin audio, pacientes ni datos clínicos reales."""

from datetime import datetime, timezone

from .domain import EstadoEvaluacion

ORIGEN = "datos_sinteticos"
EVALUADOR_ID = "22222222-2222-4222-8222-222222222222"
EVALUADOR_USUARIO = "autonoma"

# UUIDs estables para que el seed sea idempotente y las pruebas los reconozcan.
DEMO_ALERTS = (
    {
        "alerta_id": "11111111-1111-4111-8111-111111111111",
        "box": "box-1",
        "tipo_riesgo": "riesgo_bajo_sintetico",
        "nivel_severidad": 1,
        "fecha_hora": datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc),
        "sesion_id": "33333333-3333-4333-8333-333333333331",
        "descripcion": None,
        "evaluacion": None,
    },
    {
        "alerta_id": "11111111-1111-4111-8111-111111111112",
        "box": "box-2",
        "tipo_riesgo": "deseo_pasivo_de_muerte",
        "nivel_severidad": 1,
        "fecha_hora": datetime(2026, 9, 9, 15, 20, tzinfo=timezone.utc),
        "sesion_id": "33333333-3333-4333-8333-333333333332",
        "descripcion": "Alerta sintética de prueba; sin datos de paciente.",
        "evaluacion": None,
    },
    {
        "alerta_id": "11111111-1111-4111-8111-111111111113",
        "box": "box-3",
        "tipo_riesgo": "ideacion_activa",
        "nivel_severidad": 2,
        "fecha_hora": datetime(2026, 9, 10, 11, 5, tzinfo=timezone.utc),
        "sesion_id": "33333333-3333-4333-8333-333333333333",
        "descripcion": None,
        "evaluacion": EstadoEvaluacion.CORRECTA,
    },
    {
        "alerta_id": "11111111-1111-4111-8111-111111111114",
        "box": "box-1",
        "tipo_riesgo": "consideracion_de_metodo",
        "nivel_severidad": 3,
        "fecha_hora": datetime(2026, 9, 11, 18, 40, tzinfo=timezone.utc),
        "sesion_id": "33333333-3333-4333-8333-333333333334",
        "descripcion": None,
        "evaluacion": EstadoEvaluacion.FALSO_POSITIVO,
    },
    {
        "alerta_id": "11111111-1111-4111-8111-111111111115",
        "box": "box-4",
        "tipo_riesgo": "conducta_suicida",
        "nivel_severidad": 3,
        "fecha_hora": datetime(2026, 9, 12, 9, 15, tzinfo=timezone.utc),
        "sesion_id": "33333333-3333-4333-8333-333333333335",
        "descripcion": None,
        "evaluacion": EstadoEvaluacion.NEUTRO,
    },
)

DEMO_ALERTA_IDS = tuple(item["alerta_id"] for item in DEMO_ALERTS)
