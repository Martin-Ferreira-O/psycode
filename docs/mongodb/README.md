# Artefactos MongoDB

Esquema de persistencia de alertas y bitácora. La explicación está en [MONGODB.md](../MONGODB.md).

| Archivo | Uso |
|---|---|
| [alerts.validator.json](alerts.validator.json) | Validador `$jsonSchema` + `$expr` de la colección `alerts` |
| [alerts.indexes.json](alerts.indexes.json) | Índices de historial, filtros y unicidad de `alerta_id` |
| [audit_events.validator.json](audit_events.validator.json) | Validador de la bitácora |
| [audit_events.indexes.json](audit_events.indexes.json) | Índices de la bitácora |
| [examples/](examples/) | Documentos de ejemplo en Extended JSON (BSON Date) |

`AlertsRepository.ensure_schema()` aplica validadores e índices al conectar. El validador de bitácora exige actor, sesión y secuencia en escrituras nuevas; los documentos históricos no se reescriben. No usar estos JSON como cuerpo HTTP: las fechas de ejemplo son `{ "$date": "..." }`, no strings ISO de la API.

El bloque `notification` es obligatorio en `notifications.result` y opcional en
eventos históricos. Cuando está presente, el validador restringe sus campos,
modalidad, fase, motivo y tipos; exige el ordinal en intentos y estado/conteos
no negativos en resúmenes. Los ejemplos incluyen un principal fallido, un respaldo
aceptado y un resumen parcial relacionados por `notification.id`. Actualizar el
validador junto con el servidor; no se requiere reescribir documentos antiguos.
