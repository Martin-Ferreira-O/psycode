# docs/ — Insumos de referencia

Documentación de referencia del proyecto (insumos entregados por el cliente y transcripciones).

| Archivo | Qué es |
|---|---|
| `Matriz-lenguaje-ideacion-suicida.xlsx` | Excel original del cliente: matriz clínica de lenguaje de ideación suicida (6 hojas: gradiente clínico, frases y lenguaje, características NLP, lenguaje profesional, evidencia y fuentes, reglas de uso). |
| `matriz-lenguaje-ideacion-suicida.md` | Transcripción completa del Excel en Markdown (para lectura de personas y modelos). |
| [SOURCE_NOTES.md](SOURCE_NOTES.md) | Lectura de los cinco archivos originales, discrepancia del Excel y límites de interpretación. |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Revisión documental de SCRUM-30 y escenarios para las implementaciones futuras. |
| [SCRUM-31.md](SCRUM-31.md) | Implementación de autenticación, configuración uv/pip y evidencia de verificación. |

**Uso:** este insumo rige la severidad clínica de las alertas (gradiente 0–7, fuente C-SSRS) y las reglas de uso que todo componente debe respetar. Ver integración en `API_CONTRACTS.md` (Anexo A) y resumen en `HANDOFF.md` §1.1.

> ⚠️ El sistema **no diagnostica**: la matriz es insumo de clasificación y alerta, y requiere validación clínica, cultural y externa antes de producción.

## Arquitectura y rutas

Esta carpeta no expone rutas ni contiene métodos ejecutables. Los contratos están en [API_CONTRACTS.md](../API_CONTRACTS.md) y el diseño en [ARCHITECTURE.md](../ARCHITECTURE.md). La documentación del backend está en [backend/README.md](../backend/README.md).

El Excel y su transcripción se conservan como insumos originales. Su gradiente se utiliza provisionalmente según el Anexo A del contrato; consultar las observaciones antes de atribuir equivalencia exacta a C-SSRS. No se implementa un detector con este material en SCRUM-30.
