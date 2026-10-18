# Alerts: alertas y evaluaciones

Estado: persistencia MongoDB implementada (SCRUM-32). Consulta, evaluación y API de bitácora implementadas.

El esquema de colecciones, invariantes y datos prohibidos está en [MONGODB.md](../../../docs/MONGODB.md). `domain.py` fija semáforo, estados y la evaluación incrustada. `repositories.py` persiste y consulta por `alerta_id`. Datos sintéticos: [seed_demo_alerts](management/commands/README.md). SCRUM-33 consultas HTTP; SCRUM-34 evaluación pública. Consumidores frontend: SCRUM-37, SCRUM-39 y SCRUM-40.

## Rutas disponibles

Namespace Django `alerts`:

| Método | Ruta | Nombre |
|---|---|---|
| GET | `/api/v1/audit-events` | `audit-list` |
| GET | `/api/v1/alerts` | `list` |
| GET | `/api/v1/alerts/{alerta_id}` | `detail` |
| GET, POST | `/api/v1/alerts/{alerta_id}/evaluacion` | `evaluation` |

Usa un único patrón de URL para evaluación y despacha según el método HTTP. [Contrato completo](../../../API_CONTRACTS.md#2-alertas-y-evaluaciones). No hay creación, edición general o eliminación públicas de alertas.

## Capas y métodos previstos

- API: `urls.py`, `views.py`, `serializers.py`; usa serialización explícita, no `ModelSerializer` sobre MongoDB.
- Aplicación: `AlertsService.register_alert`, `list_alerts`, `get_alert`, `record_evaluation`, `get_evaluation`.
- Dominio: `domain.py` define alerta, evaluación y reglas: una evaluación por alerta, severidad 1–3, semáforo derivado uno a uno e invariantes del documento MongoDB. Pruebas en [tests](tests/README.md).
- Puertos: `ports.py` define `AlertQueryPort` y `AlertWritePort`. `AlertNotifier` pertenece a SCRUM-41.
- Infraestructura: `mongo.py` (cliente perezoso), `documents.py` (mapeo sin audio ni ObjectId público) y `repositories.py` (alta, get y evaluación atómica). No hay modelos ORM Django para estas colecciones.
- Comando: `seed_demo_alerts` crea cinco alertas de prueba y verifica la relectura. Requiere MongoDB y `DJANGO_DEBUG=true`.

## Integración y trazabilidad

Los repositorios devuelven DTO, nunca cursores. La evaluación incrustada incluye autor UUID, identificador visible al evaluar y fecha UTC del servidor. Cambia junto con estado y fecha de actualización en una escritura condicional atómica. No se permite reevaluar ni sobrescribir una evaluación en v1.

`register_alert` es una interfaz interna para datos ya clasificados; solo acepta niveles 1–3, no clasifica voz ni genera diagnósticos. Los resultados NULO/sin riesgo se omiten antes de registrarlos. Persiste antes de invocar `AlertNotifier`. Un UUID duplicado produce conflicto y no dispara un nuevo envío.

Dashboard consume `AlertQueryPort`. El registro frontend de evaluaciones usa listado con `revisadas=true` y el objeto `evaluacion` incluido, evitando una consulta por fila.

Pruebas actuales en [tests](tests/README.md): mapeo, duplicados, evaluación atómica, variedad del seed y conexión fallida. La integración contra MongoDB real se activa con `PSYCODE_TEST_MONGODB_URI`. Filtros HTTP y página quedan para SCRUM-33.

`audit.py` comparte event_id y timestamp entre logger y MongoDB para registro, evaluación, intentos y fallos de integración/flujo. `audit_api.py` ofrece consulta con filtros, paginación y orden cronológico; solo administradores y supervisores activos. No incluye interfaz visual. [Contrato](../../../API_CONTRACTS.md#consulta-de-bitácora-scrum-65).
