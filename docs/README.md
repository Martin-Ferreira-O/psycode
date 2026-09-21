# Documentación del proyecto

Para instalar y probar el backend, sigue el [README principal](../README.md). Para desarrollar una tarea, consulta la [arquitectura](../ARCHITECTURE.md) y los [contratos API](../API_CONTRACTS.md).

| Documento | Cuándo consultarlo |
|---|---|
| [MONGODB.md](MONGODB.md) | Colecciones, documentos, índices, relaciones, estados y datos que no se persisten. Artefactos en [mongodb/](mongodb/). |
| [SCRUM-31.md](SCRUM-31.md) | Detalles de autenticación, correo y verificaciones de la entrega original. Las credenciales actuales están en el README principal. |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Criterios de revisión de SCRUM-30 y escenarios previstos para las siguientes tareas. |
| [SOURCE_NOTES.md](SOURCE_NOTES.md) | Diferencias entre los insumos originales y límites de interpretación de la matriz. |
| `Matriz-lenguaje-ideacion-suicida.xlsx` | Matriz original del cliente: gradiente clínico, frases, características NLP, lenguaje profesional, evidencia y reglas de uso. |
| [matriz-lenguaje-ideacion-suicida.md](matriz-lenguaje-ideacion-suicida.md) | Transcripción de las seis hojas del Excel. |

La matriz se usa provisionalmente para la severidad de alertas según el Anexo A de [API_CONTRACTS.md](../API_CONTRACTS.md). Antes de modificar esa clasificación, lee las observaciones de `SOURCE_NOTES.md`: no debe asumirse una equivalencia exacta con C-SSRS. El sistema no diagnostica; la clasificación necesita validación clínica antes de usarse en producción.

El Excel y su transcripción se conservan como referencias originales. Los documentos de entrega registran el estado de su fecha; los README de los módulos describen el estado actual del código.
