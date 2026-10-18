# Notificaciones por correo

`NotificationService.notify_alert(alerta_id, payload)` consulta la alerta persistida y envía primero al correo principal configurado en `NOTIFICATION_EMAIL_TO` (SCRUM-67). Solo si falla o expira intenta `NOTIFICATION_EMAIL_BACKUP_TO` (Sergio). No se necesitan contraseñas de destinatarios: las credenciales corresponden al remitente o relay SMTP.

`NOTIFICATIONS_ENABLED=false` por defecto. Teams permanece fuera del flujo y deshabilitado hasta decidir el webhook; su cliente se mantiene desacoplado. NULO/sin riesgo, alerta ausente, persistencia inaccesible o envíos desactivados no generan mensajes. Un fallo doble conserva la alerta.

La composición `backend.config.composition.alerts_service()` conecta persistencia y notificación en ese orden. Los repositorios no envían; los duplicados no vuelven a notificar. El seed usa el servicio sin notificador. El mensaje se reconstruye desde la alerta confirmada e incluye únicamente box, tipo de riesgo constante, semáforo y fecha. Nunca descripción, audio, transcripción ni datos de pacientes.

Cada intento se registra por separado mediante `AlertAudit`, con el mismo event_id en logger y MongoDB. `contingencia` distingue principal/respaldo sin guardar correos. SMTP usa un proceso cancelable con plazo completo `EMAIL_TIMEOUT_SECONDS`; un timeout puede dejar incierta la aceptación por el servidor, pero no deja un hilo de envío activo. Aceptación no implica entrega o lectura. No se implementa cola de recuperación ni reintentos automáticos.

Pruebas: `uv run python manage.py test backend.apps.notifications --settings=backend.config.test_settings --noinput`. Usan correo en memoria, clientes simulados y un servidor SMTP local sin credenciales. [Contrato](../../../API_CONTRACTS.md#4-registro-y-notificaciones-contratos-internos), [arquitectura](../../../ARCHITECTURE.md).
