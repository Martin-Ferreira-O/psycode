"""Tipos y reglas de notifications; sin dependencias de infraestructura."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
        return self.nivel_normalizado not in NIVELES_SIN_NOTIFICACION

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
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Alerta del sistema</title>
</head>
<body style="margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9;">
  <div style="max-width: 480px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
    <div style="background-color: #123962; color: #ffffff; padding: 12px 18px; font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px;">
      <span>✉</span> Correo institucional
    </div>
    
    <div style="padding: 12px 18px; font-size: 12px; color: #475569; border-bottom: 1px solid #e2e8f0; line-height: 1.6;">
      <div style="float: right; color: #64748b;">Hoy, {self.fecha_hora}</div>
      <div><strong>De:</strong> Sistema de Monitoreo</div>
      <div><strong>Asunto:</strong> Alerta del sistema</div>
      <div><strong>Para:</strong> Equipo Clínico</div>
      <div style="clear: both;"></div>
    </div>

    <div style="padding: 24px 18px;">
      <table style="width: 100%; border-collapse: collapse;">
        <tr>
          <td style="width: 52px; vertical-align: top; padding-right: 14px;">
            <div style="width: 46px; height: 46px; border-radius: 50%; background-color: {self.color_hex}; color: #ffffff; font-size: 26px; font-weight: 900; line-height: 46px; text-align: center;">!</div>
          </td>
          <td style="vertical-align: top;">
            <h2 style="margin: 0 0 10px 0; font-size: 17px; font-weight: 800; color: #0f172a; letter-spacing: 0.5px;">ALERTA DEL SISTEMA</h2>
            <div style="font-size: 14px; color: #1e293b; line-height: 1.6;">
              <div><strong>Box:</strong> {self.box}</div>
              <div><strong>Tipo:</strong> {self.tipo_riesgo}</div>
              <div><strong>Nivel:</strong> <span style="color: {self.color_hex}; font-weight: 700;">{self.indicador_visual}</span></div>
              <div><strong>Hora:</strong> {self.fecha_hora}</div>
            </div>
            <p style="margin: 12px 0 0 0; font-size: 13px; color: #475569;">Se requiere revisión profesional.</p>
          </td>
        </tr>
      </table>
    </div>

    <div style="background-color: #f8fafc; padding: 10px 18px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b;">
      🛡 Sin datos personales del paciente
    </div>
  </div>
</body>
</html>"""


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