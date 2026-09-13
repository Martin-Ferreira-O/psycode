# Alerts: alertas y evaluaciones

Estado: pendiente de implementación. Los archivos actuales son la estructura base; las rutas de esta página todavía responden 404.

Este módulo manejará el registro, consulta, filtros y evaluación de alertas con persistencia en MongoDB. SCRUM-32 implementa persistencia; SCRUM-33 consultas; SCRUM-34 evaluación. Consumidores frontend: SCRUM-37, SCRUM-39 y SCRUM-40.

## Rutas por implementar

Namespace Django `alerts`:

| Método | Ruta | Nombre |
|---|---|---|
| GET | `/api/v1/alerts` | `list` |
| GET | `/api/v1/alerts/{alerta_id}` | `detail` |
| GET, POST | `/api/v1/alerts/{alerta_id}/evaluacion` | `evaluation` |

Usa un único patrón de URL para evaluación y despacha según el método HTTP. [Contrato completo](../../../API_CONTRACTS.md#2-alertas-y-evaluaciones). No hay creación, edición general o eliminación públicas de alertas.

## Capas y métodos previstos

- API: `urls.py`, `views.py`, `serializers.py`; usa serialización explícita, no `ModelSerializer` sobre MongoDB.
- Aplicación: `AlertsService.register_alert`, `list_alerts`, `get_alert`, `record_evaluation`, `get_evaluation`.
- Dominio: `domain.py` define alerta, evaluación, filtros y reglas: una evaluación por alerta, severidad 0–7 y semáforo derivado provisional.
- Puertos: `ports.py` define `AlertQueryPort`, `AlertWritePort`, `AlertNotifier` según [arquitectura](../../../ARCHITECTURE.md).
- Infraestructura: `repositories.py` implementa consultas y escrituras en MongoDB. No se crean modelos ORM Django para estas colecciones.

## Integración y trazabilidad

Los repositorios devuelven DTO, nunca cursores. La evaluación incrustada incluye autor UUID, identificador visible al evaluar y fecha UTC del servidor. Cambia junto con estado y fecha de actualización en una escritura condicional atómica. No se permite reevaluar ni sobrescribir una evaluación en v1.

`register_alert` es una interfaz interna para datos ya clasificados; no clasifica voz ni genera diagnósticos. Persiste antes de invocar `AlertNotifier`. El semáforo NULO y los datos de prueba con envíos desactivados no generan avisos. Un UUID duplicado produce conflicto y no dispara un nuevo envío.

Dashboard consume `AlertQueryPort`. El registro frontend de evaluaciones usa listado con `revisadas=true` y el objeto `evaluacion` incluido, evitando una consulta por fila.

Pruebas futuras: filtros AND, orden estable, página vacía, UUID inválido/inexistente, fallo de persistencia, dos evaluaciones simultáneas y registro sin envío de datos sintéticos.
