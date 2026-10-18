# Bitácora de alertas y correo principal/respaldo

Implementado en `sprint/4`: consulta protegida de bitácora, correlación de eventos y actualización del flujo de notificación. No incluye interfaz visual, auditoría administrativa ni navegación del frontend.

## Comportamiento verificado

| Criterio | Implementación / prueba |
|---|---|
| Creación y evaluación | `AlertsRepository` registra solo escrituras exitosas; la evaluación conserva UUID del usuario autenticado y fecha |
| Intentos de despacho | Un evento `notifications.send` por intento, con canal, resultado, timestamp, duración, contingencia y código estable |
| Actor automático/humano | `Sistema` con actor_id null, o `Usuario` con UUID; la evaluación exige usuario |
| Correlación | alerta_id; sesión y secuencia disponibles en fallos técnicos; mismo event_id en logger/MongoDB |
| Fallos de integración y flujo | Speechmatics/JEV, `FLOW_INTERRUPTED`, `ALERT_PERSISTENCE_FAILED`, error inesperado del notificador |
| Consulta | `GET /api/v1/audit-events`, filtros por período/alerta/acción/resultado, limit/offset y orden asc/desc con desempate por event_id |
| Permisos | JWT y usuario activo admin/supervisor o superusuario; sin escritura pública |
| Privacidad | Lista explícita de campos, códigos permitidos, UUID sin nombres/correos; MongoDB rechaza campos ajenos al esquema |
| Principal y respaldo | `NOTIFICATION_EMAIL_TO` primero; `NOTIFICATION_EMAIL_BACKUP_TO` solo ante fallo o timeout; sin credenciales de destinatarios |
| Persistencia antes de envío | La composición del trabajador guarda antes de notificar; duplicados y persistencia caída no envían |
| Fallo doble | Conserva alerta y evaluación pendiente; ambos intentos auditados |
| Teams | Deshabilitado por defecto y excluido del flujo; cliente desacoplado para una decisión posterior |

## Configuración

El destinatario principal acordado con el cliente en SCRUM-67 debe configurarse en `NOTIFICATION_EMAIL_TO`. El respaldo de Sergio se configura en `NOTIFICATION_EMAIL_BACKUP_TO`. Este repositorio no contiene esas direcciones y esta entrega no modifica `.env`. Los envíos permanecen desactivados por defecto (`NOTIFICATIONS_ENABLED=false`). SMTP solo requiere credenciales del remitente/relay. `EMAIL_TIMEOUT_SECONDS` limita el intento completo en un proceso cancelable.

## Verificación reproducible

```sh
uv run python manage.py check --settings=backend.config.test_settings
uv run python manage.py test --settings=backend.config.test_settings --noinput
```

Con un MongoDB exclusivo de pruebas:

```sh
PSYCODE_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 uv run python manage.py test --settings=backend.config.test_settings --noinput
```

Pruebas principales: `alerts.tests.test_audit`, `alerts.tests.test_audit_api`, `notifications.tests`, `analysis.tests`. Incluyen persistencia MongoDB real opcional, restricciones de esquema, actor, permisos, filtros y paginación, clientes simulados, correo en memoria y servidor SMTP local que rechaza al principal y acepta al respaldo. No requieren cuentas SMTP ni proveedores externos.

## Límites operativos

La auditoría se escribe primero al logger. Si MongoDB falla, el log conserva el evento y un diagnóstico `AUDIT_UNAVAILABLE` con su event_id; no hay cola de recuperación. No hay transacción entre guardar y enviar: un corte abrupto puede dejar una alerta almacenada sin aviso. Un timeout SMTP puede dejar incierta la aceptación previa por el relay; no se garantiza entrega exactamente una vez. Eventos con el mismo timestamp BSON (precisión de milisegundos) se ordenan establemente por event_id, sin inferir causalidad entre empates.

El esquema ampliado se aplica con `ensure_schema()`/collMod; no reescribe documentos históricos. La consulta deriva actor desde actor_id y devuelve null para sesión/secuencia históricas ausentes. [Contrato API](../API_CONTRACTS.md#consulta-de-bitácora-scrum-65), [arquitectura](../ARCHITECTURE.md), [MongoDB](MONGODB.md).
