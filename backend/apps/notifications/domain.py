"""Tipos y reglas de notifications; sin dependencias de infraestructura."""
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Dict, List, Optional
from django.template.loader import render_to_string
from django.utils.timezone import get_default_timezone

CIRCULOS_RIESGO: Dict[str, str] = {
    "BAJO": "🟢",
    "MEDIO": "🟡",
    "ALTO": "🔴",
}

NIVELES_SIN_NOTIFICACION = {"NULO", "SIN RIESGO", "NINGUNO", ""}


@dataclass(frozen=True)
class NotificationPayload:
    nivel_riesgo: str
    tipo_riesgo: str
    box: str
    fecha_hora: str
    es_prueba: bool = False
    hablante_no_confirmado: bool = False

    def __post_init__(self):
        if not self.box or not self.tipo_riesgo:
            raise ValueError("box y tipo_riesgo son obligatorios")

    @property
    def nivel_normalizado(self) -> str:
        return self.nivel_riesgo.strip().upper()

    def debe_notificar(self) -> bool:
        return self.nivel_normalizado in CIRCULOS_RIESGO

    @property
    def circulo_riesgo(self) -> str:
        return CIRCULOS_RIESGO.get(self.nivel_normalizado, "⚪")

    @property
    def indicador_visual(self) -> str:
        return f"{self.circulo_riesgo} {self.nivel_normalizado}"

    def formatear_resumen_teams(self) -> str:
        return f"{self.indicador_visual} · {self.tipo_riesgo} · {self.box} · {self.fecha_hora}"

    @property
    def box_correo(self) -> str:
        codigo = re.fullmatch(r"box-([0-9]+)", self.box, re.IGNORECASE)
        return f"Box {codigo[1].zfill(2)}" if codigo else self.box

    @property
    def tipo_riesgo_correo(self) -> str:
        texto = self.tipo_riesgo.replace("_", " ")
        return texto[:1].upper() + texto[1:]

    def fecha_y_hora_correo(self) -> tuple[str, str]:
        try:
            instante = datetime.fromisoformat(self.fecha_hora)
        except ValueError:
            try:
                return "", time.fromisoformat(self.fecha_hora).strftime("%H:%M:%S")
            except ValueError:
                return "", "—"
        if instante.tzinfo is not None:
            instante = instante.astimezone(get_default_timezone())
        return instante.strftime("%d/%m/%Y"), instante.strftime("%H:%M:%S")

    def formatear_asunto_correo(self) -> str:
        if self.es_prueba:
            return f"[PRUEBA] Alerta simulada - {self.box_correo}"
        if self.hablante_no_confirmado:
            return f"[REVISAR] Señal con hablante sin confirmar - {self.box_correo}"
        return f"{self.circulo_riesgo} [RIESGO {self.nivel_normalizado}] Alerta del sistema - {self.box_correo}"

    @property
    def titulo_correo(self) -> str:
        if self.es_prueba:
            return "ALERTA DE PRUEBA"
        if self.hablante_no_confirmado:
            return "ALERTA PARA REVISIÓN"
        return "ALERTA DEL SISTEMA"

    @property
    def mensaje_correo(self) -> str:
        if self.es_prueba:
            return "Detección generada con audio simulado. No requiere intervención clínica."
        if self.hablante_no_confirmado:
            return "Hablante sin confirmar. Se requiere revisión profesional."
        return "Se requiere revisión profesional."

    def formatear_cuerpo_correo(self) -> str:
        fecha, hora = self.fecha_y_hora_correo()
        linea_fecha = f"Fecha: {fecha}\n" if fecha else ""
        return (
            f"{self.titulo_correo}\n\n"
            f"Box: {self.box_correo}\n"
            f"Tipo: {self.tipo_riesgo_correo}\n"
            f"Nivel: {self.indicador_visual}\n"
            f"{linea_fecha}Hora: {hora}\n\n"
            f"{self.mensaje_correo}\n\n"
            "Sin datos personales del paciente"
        )

    def formatear_html_correo(self) -> str:
        fecha, hora = self.fecha_y_hora_correo()
        context = {
            "titulo": self.titulo_correo,
            "mensaje": self.mensaje_correo,
            "box": self.box_correo,
            "tipo_riesgo": self.tipo_riesgo_correo,
            "indicador_visual": self.indicador_visual,
            "nivel_css": self.nivel_normalizado.lower() if self.debe_notificar() else "alto",
            "fecha": fecha,
            "hora": hora,
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
    estado: str = "OMITIDA"
