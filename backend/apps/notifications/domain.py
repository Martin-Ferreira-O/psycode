"""Tipos y reglas de notifications; sin dependencias de infraestructura."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from django.template.loader import render_to_string

INDICADORES_RIESGO: Dict[str, str] = {
    "BAJO": "🟢 BAJO",
    "MEDIO": "🟡 MEDIO",
    "ALTO": "🔴 ALTO",
}

COLORES_RIESGO: Dict[str, str] = {
    "BAJO": "#16a34a",
    "MEDIO": "#d97706",
    "ALTO": "#dc2626",
}

NIVELES_SIN_NOTIFICACION = {"NULO", "SIN RIESGO", "NINGUNO", ""}


@dataclass(frozen=True)
class NotificationPayload:
    nivel_riesgo: str
    tipo_riesgo: str
    box: str
    fecha_hora: str

    def __post_init__(self):
        if not self.box or not self.tipo_riesgo:
            raise ValueError("box y tipo_riesgo son obligatorios")

    @property
    def nivel_normalizado(self) -> str:
        return self.nivel_riesgo.strip().upper()

    def debe_notificar(self) -> bool:
        return self.nivel_normalizado in INDICADORES_RIESGO

    @property
    def indicador_visual(self) -> str:
        return INDICADORES_RIESGO.get(self.nivel_normalizado, f"⚪ {self.nivel_normalizado}")

    @property
    def color_hex(self) -> str:
        return COLORES_RIESGO.get(self.nivel_normalizado, "#dc2626")

    def formatear_resumen_teams(self) -> str:
        return f"{self.indicador_visual} · {self.tipo_riesgo} · {self.box} · {self.fecha_hora}"

    def formatear_asunto_correo(self) -> str:
        return f"Alerta del sistema - {self.box}"

    def formatear_cuerpo_correo(self) -> str:
        return (
            "ALERTA DEL SISTEMA\n\n"
            f"Box: {self.box}\n"
            f"Tipo: {self.tipo_riesgo}\n"
            f"Nivel: {self.indicador_visual}\n"
            f"Hora: {self.fecha_hora}\n\n"
            "Se requiere revisión profesional.\n\n"
            "Sin datos personales del paciente"
        )

    def formatear_html_correo(self) -> str:
        context = {
            "box": self.box,
            "tipo_riesgo": self.tipo_riesgo,
            "nivel_riesgo": self.nivel_normalizado,
            "indicador_visual": self.indicador_visual,
            "color_hex": self.color_hex,
            "fecha_hora": self.fecha_hora,
        }
        return render_to_string("notifications/alerta_correo.html", context)


@dataclass
class AttemptResult:
    canal: str
    exitoso: bool
    duracion_ms: float
    error: Optional[str] = None


@dataclass
class NotificationResult:
    alerta_id: str
    enviado: bool
    canal_exitoso: Optional[str] = None
    intentos: List[AttemptResult] = field(default_factory=list)
    motivo_omision: Optional[str] = None
    