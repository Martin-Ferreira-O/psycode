# Dashboard: resumen y estadísticas

Estado: pendiente de implementación. Las rutas de esta página todavía responden 404.

SCRUM-36 necesita estas agregaciones para el frontend. El responsable del backend sigue sin asignar en el handoff; coordina esa asignación al abordar la tarea.

## Rutas por implementar

| Método | Ruta | Nombre Django |
|---|---|---|
| GET | `/api/v1/dashboard/resumen` | `dashboard:summary` |
| GET | `/api/v1/dashboard/estadisticas` | `dashboard:statistics` |

Autenticación obligatoria. Parámetros, límites temporales y ejemplos: [contrato dashboard](../../../API_CONTRACTS.md#3-dashboard).

## Capas y métodos previstos

- API: `urls.py`, `views.py`, `serializers.py` para consultas y respuesta.
- Aplicación: `DashboardService.get_summary` y `get_statistics`.
- Dominio: `domain.py` calcula semana/mes calendario en `America/Santiago` y convierte sus límites a UTC.
- Infraestructura: no tiene base ni repositorio propios. Recibe `AlertQueryPort.summarize` y `daily_counts`, implementados en alerts.

No importa PyMongo ni duplica documentos de alertas. Cuenta por fecha de detección y estado de evaluación actual, no reconstruye estados pasados. Los períodos históricos se consultan mediante `fecha_referencia`; el historial individual usa GET alerts con los límites de fecha devueltos.

Pruebas futuras: lunes/domingo, fin de mes, año bisiesto, cambio de hora en Santiago, ceros sin datos y coherencia entre total, estados, severidades y conteo diario.
