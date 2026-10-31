# Notificaciones por correo

`NotificationService.notify_alert(alerta_id, payload)` consulta la alerta persistida y resuelve los destinatarios al preparar cada notificación habilitada. `RecipientResolver.resolve()` lee la configuración operativa vigente sin modificarla. En modalidad `supervisores_activos` consulta cuentas con rol Supervisor, habilitadas y sin privilegio de superusuario; no consulta sesiones ni último inicio de sesión. Usa sus correos registrados válidos, sin duplicados (ignorando mayúsculas y espacios externos), y refleja cambios de rol, estado y correo en la próxima preparación.

El resultado `RecipientResult` contiene `mode`, `emails`, `reason`, `backup_enabled` y `backup_email`. Si no hay destinatarios principales válidos, `reason` es `SIN_DESTINATARIOS_VALIDOS`. En modalidad de supervisores con respaldo habilitado se intenta ese respaldo; en los demás casos se devuelve el mismo motivo sin intentos de envío ni cambio de modalidad. La lista de distribución usa exclusivamente `primary_email`. Si falta configuración operativa o el correo no es válido, no hay envío: `NOTIFICATION_EMAIL_TO` nunca sustituye la selección guardada. Un fallo principal total o parcial activa un único intento de respaldo si está habilitado; no recibe copia cuando todos los principales son exitosos. No se necesitan contraseñas de destinatarios.

Cada dirección recibe un mensaje independiente, sin exponer las direcciones de otros supervisores. Un rechazo, timeout o excepción no impide intentar los restantes. `NotificationResult.estado` distingue `EXITO_TOTAL` (todos aceptados), `FALLO_PARCIAL` (hay una aceptación y un problema principal, incluso si el respaldo lo recupera), `FALLO_TOTAL` (ninguno aceptado), `SIN_DESTINATARIOS_VALIDOS` y `OMITIDA` (por las condiciones previas). `enviado` indica al menos un envío aceptado; `intentos` contiene un resultado por intento principal o de respaldo, sin direcciones.

`NOTIFICATIONS_ENABLED=false` por defecto. Teams permanece fuera del flujo y deshabilitado hasta decidir el webhook; su cliente se mantiene desacoplado. NULO/sin riesgo, alerta ausente, persistencia inaccesible o envíos desactivados no generan mensajes. Los fallos de envío conservan la alerta.

La composición `backend.config.composition.alerts_service()` conecta persistencia y notificación en ese orden. Los repositorios no envían; los duplicados no vuelven a notificar. El seed usa el servicio sin notificador. El mensaje se reconstruye desde la alerta confirmada e incluye únicamente box, tipo de riesgo constante, semáforo y fecha. Nunca descripción, audio, transcripción ni datos de pacientes.

Cada intento se registra por separado mediante `AlertAudit`, con el mismo event_id en logger y MongoDB. `contingencia=false` identifica los intentos principales y `true` los de respaldo, sin guardar correos. SMTP usa un proceso cancelable con plazo completo `EMAIL_TIMEOUT_SECONDS`; un timeout puede dejar incierta la aceptación por el servidor, pero no deja un hilo de envío activo. Aceptación no implica entrega o lectura. No se implementa cola de recuperación ni reintentos automáticos.

Pruebas: `uv run python manage.py test backend.apps.notifications --settings=backend.config.test_settings --noinput`. Usan correo en memoria, clientes simulados y un servidor SMTP local sin credenciales. [Contrato](../../../API_CONTRACTS.md#4-registro-y-notificaciones-contratos-internos), [arquitectura](../../../ARCHITECTURE.md).

## Trazabilidad de notificaciones

Cada ejecución habilitada sobre una alerta almacenada genera un UUID
`notification.id`, compartido por sus intentos y su resumen, junto con
`alerta_id` y `sesion_id`. Volver a notificar la misma alerta genera otro UUID.
`notification.mode` conserva la modalidad principal utilizada, o null si no
existe configuración válida.

`notifications.send` conserva el resultado individual, duración y código técnico;
`notification.phase` distingue `principal` y `respaldo`, y `attempt` numera los
intentos desde 1. `notifications.result` añade el estado global y los conteos
`primary_successes`, `primary_failures`, `backup_successes` y `backup_failures`.
El resumen no cuenta como otro intento SMTP.

`notification.reason` conserva `FALLO_PARCIAL`, `FALLO_TOTAL` o
`SIN_DESTINATARIOS_VALIDOS`, incluso si el respaldo recupera el envío. Sin
principales válidos, sus conteos son cero. El resumen usa `outcome=success` para
éxito total, `failure` si hubo un problema principal y algún intento, o `skipped`
si no había destinatarios válidos ni se intentó el respaldo.

La pantalla permite consultar modalidad, etapa, conteos, motivo y uso del respaldo.
El escritor solo admite UUID, enums, conteos no negativos y campos permitidos,
sin direcciones, contenido clínico, credenciales ni errores libres. Los eventos
anteriores siguen consultables con `notification=null`, sin inventar conteos.
Los intentos sin resumen por una interrupción no prueban éxito global.
[Formato, validador y ejemplos](../../../docs/MONGODB.md#6-colección-audit_events-bitácora).

## Configuración de destinatarios y respaldo

La configuración operativa admite una sola modalidad principal de notificación a la vez:

- `lista_distribucion`: utiliza exclusivamente el correo almacenado en `primary_email`.
- `supervisores_activos`: resuelve dinámicamente todos los usuarios con rol Supervisor que se encuentren activos y posean un correo válido.

Las modalidades son excluyentes. No se admite configurar ambas simultáneamente. Los cambios de correo, rol o estado de un usuario se reflejan en la siguiente resolución de destinatarios, sin requerir reinicio del sistema ni una sesión iniciada del supervisor.

### Ejemplo: lista de distribución

```json
{
  "notification_mode": "lista_distribucion",
  "primary_email": "lista@example.test",
  "backup_enabled": false,
  "backup_email": ""
}
```

### Ejemplo: supervisores activos

```json
{
  "notification_mode": "supervisores_activos",
  "primary_email": "",
  "backup_enabled": false,
  "backup_email": ""
}
```

En esta modalidad no se configura manualmente una lista de supervisores. Los destinatarios se obtienen desde las cuentas vigentes del sistema. Solamente se consideran usuarios con rol Supervisor, estado activo y correo válido. Cada supervisor recibe un mensaje independiente.

### Ejemplo: respaldo habilitado

```json
{
  "notification_mode": "supervisores_activos",
  "primary_email": "",
  "backup_enabled": true,
  "backup_email": "respaldo@example.test"
}
```

Cuando el respaldo está habilitado, un fallo parcial o total de los destinatarios principales puede generar un único intento de contingencia al correo configurado en `backup_email`.

Aunque fallen varios destinatarios principales, el sistema no genera un aviso de respaldo por cada fallo individual. Se ejecuta como máximo un intento de respaldo por proceso de notificación.

Si todos los envíos principales son exitosos, el respaldo no se utiliza.

Si el respaldo está deshabilitado, los fallos principales se registran normalmente, pero no se realiza ningún intento adicional.

Los campos de correo solamente son obligatorios cuando corresponden a un destino habilitado:

- `primary_email` debe contener un correo válido cuando se utiliza `lista_distribucion`.
- `backup_email` debe contener un correo válido cuando `backup_enabled` es `true`.
- Los correos asociados a opciones deshabilitadas pueden mantenerse guardados sin participar en el envío.

## Pruebas de aceptación de destinatarios y respaldo

Las pruebas de aceptación del flujo se ejecutan con:

```bash
python manage.py test backend.apps.notifications backend.apps.operational
```

La suite valida, entre otros casos:

- exclusividad y persistencia de las modalidades;
- selección exclusiva de supervisores activos;
- actualización de destinatarios ante cambios de correo, rol o estado;
- envío mediante lista de distribución;
- envío independiente a múltiples supervisores;
- ausencia de destinatarios válidos;
- éxito total;
- fallo parcial;
- fallo total;
- timeout;
- respaldo habilitado y deshabilitado;
- ejecución de un único respaldo ante múltiples fallos principales;
- permisos de administración;
- validaciones condicionales de los correos;
- persistencia de la configuración operativa.

En la ejecución de aceptación se completaron 70 pruebas sin errores.

Las pruebas utilizan direcciones reservadas para testing, como `@example.test`, correo en memoria, mocks y servicios simulados. No utilizan destinatarios reales ni realizan entregas externas. Las pruebas reales de entrega SMTP y la prueba integral de captura permanecen fuera del alcance de esta validación.