# Notifications: avisos por Teams y correo

Estado: pendiente de implementación (SCRUM-41). Los archivos actuales son la estructura base. El módulo enviará avisos internos; no tiene endpoints públicos. El responsable sigue sin asignar en el handoff.

## Capas y métodos previstos

- Aplicación: `NotificationService.notify_alert(alerta_id, payload)` implementa `AlertNotifier`.
- Dominio: `domain.py` define payload permitido y resultado de intentos.
- Infraestructura: `clients.py` implementa `TeamsClient.send(payload)` mediante HTTPS a Teams Workflows y `EmailClient.send(payload)` mediante correo Django.
- Puertos: `ports.py` define clientes sustituibles para probar éxito, rechazo y timeout sin mensajes reales.

No necesita `urls.py`, vistas ni modelos de alerta. Recibe datos del caso de uso de registro, no consulta MongoDB ni datos de pacientes. Composición/configuración ocurre en config.

## Contrato y comportamiento

Ver [contrato interno único](../../../API_CONTRACTS.md#4-registro-y-notificaciones-contratos-internos). Teams primero; correo si Teams falla. Plazo máximo total de 10 segundos por intento/canal, un intento por canal, sin reintentos automáticos en esta versión. Auditar resultado, duración y contingencia en el logger y en `audit_events` ([esquema](../../../docs/MONGODB.md)); distinguir aceptación por proveedor de lectura por una persona.

El payload externo permite tipo de mensaje, box, tipo de riesgo, urgencia y fecha/hora. No incluye UUID del paciente, nombres, sesión, descripción libre, audio, transcripción ni detalles operativos. `alerta_id` acompaña el contexto interno de auditoría, no el cuerpo enviado.

`NOTIFICATIONS_ENABLED=false` desactiva envíos en desarrollo y pruebas sintéticas. Si se activa y falta configuración de Teams, se registra fallo de ese canal y se intenta correo. Si ambos fallan, retornar resultado fallido sin eliminar la alerta ni ocultar el fallo.

SCRUM-41 configurará el workflow, sus propietarios de continuidad y destinatarios con la clínica. Usar la integración vigente de [Teams Workflows](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/what-are-webhooks-and-connectors), encapsulando su formato de transporte. La configuración local mantiene los envíos desactivados.

Pruebas futuras: éxito Teams sin correo, timeout/rechazo Teams con correo, fallo doble, envíos deshabilitados, NULO sin envío y ausencia de información sensible.
