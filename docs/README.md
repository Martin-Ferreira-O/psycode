# Documentación del proyecto

Para instalar y probar el backend, sigue el [README principal](../README.md). Para desarrollar una tarea, consulta la [arquitectura](../ARCHITECTURE.md) y los [contratos API](../API_CONTRACTS.md).

**Para probar consultoria-bn con psycode-agent**, comienza por
[la guía paso a paso de ambos repositorios](PRUEBAS-SERVIDOR-AGENTE.md).
Explica qué instalar, dónde ejecutar cada comando y cómo comprobar el resultado.

| Documento | Cuándo consultarlo |
|---|---|
| [Configuración operativa: contrato API](../API_CONTRACTS.md#12-configuración-operativa) | Modalidad principal de notificación, respaldo independiente, validaciones, ejemplos y migración para frontend. |
| [PRUEBAS-SERVIDOR-AGENTE.md](PRUEBAS-SERVIDOR-AGENTE.md) | Primera prueba conjunta: paquete del agente, integración automática, fallos comunes y captura manual opcional. |
| [SCRUM-72-INTEGRACION.md](SCRUM-72-INTEGRACION.md) | Traspaso histórico del agente del box; para operación y transporte actuales, usar la guía conjunta y OPERACION-SEPARADA.md. |
| [MONGODB.md](MONGODB.md) | Colecciones, documentos, índices, relaciones, estados y datos que no se persisten. Artefactos en [mongodb/](mongodb/). |
| [SCRUM-31.md](SCRUM-31.md) | Detalles de autenticación, correo y verificaciones de la entrega original. Las credenciales actuales están en el README principal. |
| [SCRUM-32.md](SCRUM-32.md) | Conexión MongoDB, repositorio de alertas, comando de datos sintéticos y verificación. |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Criterios de revisión de SCRUM-30 y escenarios previstos para las siguientes tareas. |
| [SOURCE_NOTES.md](SOURCE_NOTES.md) | Diferencias entre los insumos originales y límites de interpretación de la matriz. |
| `Matriz-lenguaje-ideacion-suicida.xlsx` | Matriz original del cliente: gradiente clínico, frases, características NLP, lenguaje profesional, evidencia y reglas de uso. |
| [matriz-lenguaje-ideacion-suicida.md](matriz-lenguaje-ideacion-suicida.md) | Transcripción de las seis hojas del Excel. |

La matriz se usa provisionalmente para la severidad de alertas según el Anexo A de [API_CONTRACTS.md](../API_CONTRACTS.md). Antes de modificar esa clasificación, lee las observaciones de `SOURCE_NOTES.md`: no debe asumirse una equivalencia exacta con C-SSRS. El sistema no diagnostica; la clasificación necesita validación clínica antes de usarse en producción.

El Excel y su transcripción se conservan como referencias originales. Los documentos de entrega registran el estado de su fecha; los README de los módulos describen el estado actual del código.

- [SCRUM-46 — Estados y errores comunes del frontend](SCRUM-46.md): helpers, integración, alcance y verificación.

La bitácora consultable y el correo principal con respaldo se describen en [SCRUM-65.md](SCRUM-65.md).

- [Operación separada](OPERACION-SEPARADA.md): instalación, procesos y recuperación.
- [Control y audio](CONTROL-Y-AUDIO.md): WS, v1/v2 y Smile nativo.
- [Extracción](EXTRACCION-AGENTE.json) y [fuente Smile](SMILE-PROVENANCE.json).

- [Resultado y límites de validación](RESULTADO-SEPARACION.md).
- [Revisión funcional posterior de la rama](REVISION-FUNCIONAMIENTO-SERVIDOR.md): correcciones, pruebas propias y límites antes del VPS/Windows.

El [README de notificaciones](../backend/apps/notifications/README.md#trazabilidad-de-notificaciones)
describe modalidad, intentos principales y de respaldo, resúmenes y conteos.
El [formato de eventos](MONGODB.md#6-colección-audit_events-bitácora) detalla los
campos y la validación, incluida la compatibilidad con eventos anteriores.
