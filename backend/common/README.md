# Utilidades compartidas

Contiene únicamente comportamientos transversales. No tiene rutas HTTP ni depende de apps de negocio.

## Archivos y métodos

- `responses.py`: `success_response(data, message, status)` agrega la estructura de respuesta y la fecha UTC; `204` no tiene cuerpo.
- `errors.py`: ServiceError, error_body y exception_handler traducen errores de aplicación, validación y framework al contrato; handlers JSON de 400/404/500.
- `audit.py`: AuditWriter.record(action, outcome, actor_id=None, error_code=None, alerta_id=None) mediante logging estructurado. Solo admite campos explícitos, sin cuerpos de solicitudes ni secretos.
- `errors.py`: `PersistenceUnavailable` (503) cuando SQLite o MongoDB no responden.

El contrato previsto de un evento técnico tiene `event_id` UUID, `timestamp` UTC, `action`, `outcome` (`success`, `failure` o `skipped`), y, cuando corresponda, `actor_id`, `alerta_id`, `channel`, `error_code`. Para notificaciones incluye duración y si se usó contingencia. Los nombres de evento previstos son `auth.login`, `auth.refresh`, `auth.logout`, `auth.password_reset`, `alerts.register`, `alerts.evaluate`, `notifications.send`.

`alerts.register`, `alerts.evaluate` y `notifications.send` se persisten además en la colección MongoDB `audit_events` (bitácora). Los eventos de autenticación no se duplican ahí. Esquema: [MONGODB.md](../../docs/MONGODB.md).

En SCRUM-31 se emiten auth.login, auth.refresh, auth.logout, auth.request_password_reset y auth.confirm_password_reset. Campos alerta_id/channel y eventos de otras apps se incorporarán con sus tareas; todavía no forman parte de la firma ejecutable. api.error registra errores inesperados sin detalles sensibles.

No registrar contraseñas, JWT, tokens de recuperación, URLs secretas, audio, datos personales de pacientes, descripción clínica ni payloads completos de proveedores. La auditoría técnica no reemplaza la evaluación y trazabilidad persistidas en MongoDB.

## Dependencias y tareas

Los módulos consumen estos contratos técnicos; common no conoce reglas de evaluación o semáforo. El formato público está exclusivamente en [API_CONTRACTS.md](../../API_CONTRACTS.md). SCRUM-31 implementa la base de respuestas y errores, y cada tarea posterior aportará sus eventos y traducciones específicas.
