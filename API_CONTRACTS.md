# Contratos de API — Psycode API

> Separación implementada: el agente instalable está en el repositorio independiente
> `psycode-agent`. El control remoto y la operación vigente se describen en
> [OPERACION-SEPARADA.md](docs/OPERACION-SEPARADA.md) y
> [CONTROL-Y-AUDIO.md](docs/CONTROL-Y-AUDIO.md). Las secciones históricas que
> presentaban el transporte como pendiente quedan sustituidas por esos contratos.


**Nombre técnico:** `psycode-api`. **API:** v1. **Revisión documental:** 1.6, modalidades de notificación y respaldo de configuración operativa actualizadas el 2026-10-28. **Implementación actual:** las operaciones descritas se implementan por sus tareas SCRUM correspondientes.

**Base URL:** `/api/v1/`. **Autenticación:** JWT `Authorization: Bearer <access_token>`. **JSON:** `application/json`. La ingesta interna de la sección 5 utiliza credenciales `Agent` y `multipart/form-data`. [Arquitectura](ARCHITECTURE.md) · [Aceptación](docs/ACCEPTANCE.md).

## 0. Convenciones comunes

### Rutas y acceso

Endpoints sin barra final; el prefijo sí se escribe `/api/v1/`. No depender de redirecciones para POST. Se conservan nombres públicos en inglés/español del borrador.

| Método | Ruta completa | Nombre Django | Acceso |
|---|---|---|---|
| POST | `/api/v1/internal/fragments` | `capture:fragment_upload` | Agente autorizado y vinculado al box; multipart |
| POST | `/api/v1/auth/login` | `accounts:login` | Público |
| POST | `/api/v1/auth/refresh` | `accounts:refresh` | Refresh válido, no exige access |
| POST | `/api/v1/auth/logout` | `accounts:logout` | Access válido + refresh propio |
| GET | `/api/v1/auth/me` | `accounts:me` | Protegido |
| POST | `/api/v1/auth/password-reset` | `accounts:password_reset` | Público |
| POST | `/api/v1/auth/password-reset/confirm` | `accounts:password_reset_confirm` | Token de recuperación |
| GET | `/api/v1/auth/admin/users` | `accounts:admin_user_list` | Protegido (solo rol admin) |
| POST | `/api/v1/auth/admin/users` | `accounts:admin_user_create` | Protegido (solo rol admin) |
| PATCH | `/api/v1/auth/admin/users/{user_id}` | `accounts:admin_user_update` | Protegido (solo rol admin) |
| PATCH | `/api/v1/auth/admin/users/{user_id}/toggle-active` | `accounts:admin_user_toggle_active` | Protegido (solo rol admin) |
| GET | `/api/v1/audit-events` | `alerts:audit-list` | Protegido (solo rol admin) |
| GET, PUT | `/api/v1/configuracion-operativa` | `operational:configuracion_operativa` | Protegido (solo rol admin) |
| GET | `/api/v1/alerts` | `alerts:list` | Protegido |
| GET | `/api/v1/alerts/{alerta_id}` | `alerts:detail` | Protegido |
| GET, POST | `/api/v1/alerts/{alerta_id}/evaluacion` | `alerts:evaluation` | Protegido |
| GET | `/api/v1/dashboard/resumen` | `dashboard:summary` | Protegido |
| GET | `/api/v1/dashboard/estadisticas` | `dashboard:statistics` | Protegido |

Protegido significa profesional autenticado y activo. No hay roles adicionales definidos para alertas y métricas: todos los usuarios activos acceden a consulta y evaluación. Las rutas bajo `/api/v1/auth/admin/` y `/api/v1/configuracion-operativa` exigen rol `admin` (`403 AUTH_FORBIDDEN` para supervisores). La configuración operativa permite GET y PUT; su formulario administra días habilitados, horario local y destinatarios de alertas, sin credenciales SMTP. No existe registro público de usuarios. GET lee y POST acciona o crea evaluación. PUT/PATCH/DELETE no están definidos para los demás recursos, salvo PATCH en la administración de cuentas.

### Tipos, validación y respuestas

- UUID: string canónico con guiones. UUID de ruta mal formado → 400; UUID válido inexistente → 404 específico. El enrutamiento deberá permitir distinguir ambos casos.
- Fechas/hora de respuesta: ISO 8601 UTC terminadas en Z. `timestamp` es la hora de emisión de respuesta.
- POST recibe objeto JSON. Campos obligatorios no aceptan ausencia, null ni string vacío. Campos extra se rechazan. GET no usa cuerpo.
- Parámetros desconocidos, repetidos, tipos inválidos y rangos invertidos retornan 400. Clientes toleran campos adicionales de respuesta futuros.
- Se recortan extremos de búsquedas, nombres de usuario y correos. Nunca contraseñas ni tokens.
- Éxito JSON: siempre `success`, `data`, `message`, `timestamp`. Error: `success`, `error`, `timestamp`. Excepción: **204 sin cuerpo ni envelope**.
- `message` es texto para personas; el frontend decide por HTTP y `error.code`.
- Campos de respuesta obligatorios salvo indicación contraria. Listas sin resultados retornan 200.

### Catálogo común de errores

Aplica a todas las operaciones según sus requisitos de acceso y formato; cada operación agrega sus errores específicos.

| HTTP | Código | Situación |
|---|---|---|
| 400 | `VALIDATION_ERROR` | JSON, campos, UUID o parámetros inválidos |
| 401 | `AUTH_REQUIRED` | Falta access en ruta protegida |
| 401 | `AUTH_INVALID_TOKEN` | Access inválido, expirado o revocado |
| 403 | `AUTH_USER_INACTIVE` | Usuario desactivado |
| 403 | `AUTH_FORBIDDEN` | Operación sobre credencial ajena |
| 404 | `RESOURCE_NOT_FOUND` | Ruta desconocida; no sustituye errores específicos de alerta |
| 405 | `METHOD_NOT_ALLOWED` | Método no soportado; incluir cabecera Allow |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | POST con contenido distinto de JSON |
| 503 | `PERSISTENCE_UNAVAILABLE` | SQLite/MongoDB no disponibles; nunca simular lista vacía |
| 500 | `INTERNAL_ERROR` | Fallo inesperado sin exponer trazas ni secretos |

401 incluye `WWW-Authenticate: Bearer`. Las rutas públicas no exigen access; refresh y recuperación validan su propia credencial.

Ejemplo HTTP 400:

~~~json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Datos de entrada inválidos",
    "details": { "fields": { "password": ["Este campo es requerido"] } }
  },
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Ejemplo HTTP 404:

~~~json
{
  "success": false,
  "error": {
    "code": "ALERTA_NO_ENCONTRADA",
    "message": "La alerta especificada no existe",
    "details": { "alerta_id": "11111111-1111-4111-8111-111111111111" }
  },
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Sin detalles seguros, `details` es un objeto vacío. Los errores de campos usan `details.fields`, objeto de listas de mensajes. Nunca devolver valores rechazados de contraseñas o tokens.

## 1. Autenticación

SCRUM-31 y SCRUM-35. Django sobre SQLite y Simple JWT, adaptando respuestas al contrato.

### Política de tokens y usuario

Access dura 3600 segundos; refresh 24 horas desde su emisión. Renovar entrega nuevo par y revoca el refresh anterior; el nuevo refresh dura 24 horas desde esa renovación. No se define un máximo absoluto adicional de sesión en v1. El cliente reemplaza el par y evita renovaciones concurrentes.

Se comprueba usuario activo también al renovar y en cada petición protegida. Cambiar contraseña invalida tokens anteriores mediante versión/huella de credencial contrastada con el usuario, tanto en access como refresh; no basta revocar refresh.

Login acepta usuario o correo institucional. Nombres de usuario sin @ y comparación exacta; correos únicos normalizados a minúsculas y comparación sin distinguir mayúsculas. Contraseña se compara exactamente. El comando seed_demo_user de SCRUM-31 crea una cuenta sintética exclusivamente local.

### Protección de acceso y modalidad de navegador

Login admite 30 solicitudes por IP y 10 por cuenta cada 15 minutos; usuario y correo comparten presupuesto entre IP distintas. El presupuesto incluye éxitos y errores, y el límite de IP se aplica antes de parsear JSON. Refresh admite 120 solicitudes por IP/15 minutos; solicitud y confirmación de recuperación, 20 cada una. Se mantiene además el límite existente por correo/IP de recuperación. Los nuevos límites responden `429 AUTH_RATE_LIMITED` con `details.retry_after` y cabecera `Retry-After`. Persisten en SQL entre procesos y reinicios. [Configuración y alcance](docs/SEGURIDAD-AUTENTICACION.md).

Los ejemplos JSON de tokens siguientes corresponden al cliente API Bearer. La interfaz usa `X-Psycode-Browser: 1`: login y refresh devuelven `data: {"authenticated": true}` y escriben cookies JWT HttpOnly, SameSite=Strict, Secure en producción. En esta modalidad, refresh y logout envían `{}`; el servidor lee el refresh de la cookie. GET `/` inicializa CSRF y las escrituras envían `X-CSRFToken`; se comprueba CSRF incluso en login. El access autenticado mediante cookie se contrasta con la sesión persistida y se invalida tras logout. Las respuestas HTML/API tienen `Cache-Control: no-store, private`.

### POST /api/v1/auth/login

Ambos strings obligatorios; usuario máximo 254 caracteres.

Solicitud:

~~~json
{ "usuario": "psicologo@clinica.cl", "password": "clave-sintetica-no-utilizable" }
~~~

Respuesta 200; tokens de ejemplo son marcadores, no credenciales reales:

~~~json
{
  "success": true,
  "data": {
    "access_token": "<access_token>",
    "refresh_token": "<refresh_token>",
    "token_type": "Bearer",
    "expires_in": 3600
  },
  "message": "Sesión iniciada",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Errores: `401 AUTH_INVALID_CREDENTIALS` si usuario inexistente o contraseña incorrecta; `403 AUTH_USER_INACTIVE` solo después de verificar contraseña. Aplican también errores comunes.

### POST /api/v1/auth/refresh

Refresh string obligatorio. No requiere access.

~~~json
{ "refresh_token": "<refresh_token>" }
~~~

Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "access_token": "<new_access_token>",
    "refresh_token": "<new_refresh_token>",
    "token_type": "Bearer",
    "expires_in": 3600
  },
  "message": "Sesión renovada",
  "timestamp": "2026-09-12T16:20:00Z"
}
~~~

Errores: `401 AUTH_INVALID_REFRESH_TOKEN` si no es refresh válido, expiró, fue usado/revocado, el usuario no existe o sus credenciales cambiaron; `403 AUTH_USER_INACTIVE`. No renovar usando un access en el cuerpo.

### POST /api/v1/auth/logout

Access válido y refresh propio obligatorio:

~~~json
{ "refresh_token": "<refresh_token>" }
~~~

Respuesta **204 sin cuerpo**. Revoca el refresh presentado. Repetir con el mismo refresh ya revocado y un access aún válido retorna 204; refresh mal formado/expirado → `401 AUTH_INVALID_REFRESH_TOKEN`; refresh válido ajeno → `403 AUTH_FORBIDDEN`.

La interfaz elimina las cookies mediante la respuesta de logout y vuelve al login; la sesión de cookie queda revocada inmediatamente. Para clientes Bearer, el access previamente emitido conserva su vigencia restante; no se promete cierre inmediato de access Bearer ni de otros dispositivos.

### GET /api/v1/auth/me

Sin cuerpo ni parámetros. Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "id": "22222222-2222-4222-8222-222222222222",
    "usuario": "psicologo",
    "nombre": "Profesional de prueba",
    "correo": "psicologo@clinica.cl",
    "activo": true
  },
  "message": "Usuario autenticado",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

ID UUID; usuario/nombre/correo strings; activo booleano. Aplican errores comunes de autenticación.

### POST /api/v1/auth/password-reset

Correo obligatorio, formato email, máximo 254 caracteres:

~~~json
{ "correo": "psicologo@clinica.cl" }
~~~

Respuesta 202:

~~~json
{
  "success": true,
  "data": {},
  "message": "Si el correo está registrado, recibirás las instrucciones para recuperar tu contraseña.",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Normalizar correo y aplicar límites por IP y correo; comprobar existencia y estado activo internamente. Solo entonces emitir token opaco de recuperación distinto del JWT. Enlace frontend configurable con `FRONTEND_BASE_URL` y `PASSWORD_RESET_PATH`. No devolver token en respuesta ni logs. Solicitudes repetidas para el mismo correo durante la ventana no reemplazan el token vigente.

202 y el mismo mensaje se devuelven para correo registrado, inexistente e inactivo. El envío es síncrono con plazo máximo configurable. 202 no garantiza recepción por el destinatario.

Al superar el límite se responde `429 PASSWORD_RESET_RATE_LIMITED` sin información sobre la cuenta. Un fallo de entrega elimina el token emitido y conserva la respuesta pública 202; el tiempo de una entrega SMTP puede variar respecto a una solicitud sin entrega.

### POST /api/v1/auth/password-reset/confirm

Ambos strings obligatorios. Token de un solo uso, 1 hora; emitir otro invalida el anterior. Contraseña mínima de 12 caracteres, no exclusivamente numérica, común ni similar a datos de usuario, mediante validadores Django.

~~~json
{ "token": "<password_reset_token>", "nueva_password": "Clave-sintetica-distinta-2026" }
~~~

Respuesta 200:

~~~json
{
  "success": true,
  "data": {},
  "message": "Contraseña actualizada",
  "timestamp": "2026-09-12T15:40:00Z"
}
~~~

Actualizar contraseña y consumir token atómicamente en SQLite. Invalidar sesiones previas según política; no iniciar sesión automáticamente. Frontend vuelve al login.

Errores: `400 AUTH_INVALID_RESET_TOKEN` por inválido, expirado, usado o sustituido; `400 VALIDATION_ERROR` por contraseña rechazada; `403 AUTH_USER_INACTIVE` si fue desactivado. Un fallo de validación de contraseña no consume token.

## 1.1 Administración de usuarios

SCRUM-42 y SCRUM-43. Gestión de cuentas sobre SQLite y Django REST Framework mediante `StrictSerializer` y patrón de servicios. Requiere access token válido de un usuario con rol `admin` y estado activo. No disponible para supervisores.

### Esquema UserDetail

| Campo | Tipo / significado | Presencia / regla |
|---|---|---|
| `id` | UUID | Canónico con guiones; inmutable |
| `usuario` | string | Nombre de usuario único; 1–150 caracteres; inmutable tras creación |
| `nombre` | string | 1–150 caracteres; se divide internamente en `first_name` y `last_name` |
| `correo` | string | Correo institucional único normalizado a minúsculas; máximo 254 caracteres |
| `rol` | enum | `admin` o `supervisor` |
| `activo` | booleano | Estado operativo de la cuenta (`is_active`) |

### GET /api/v1/auth/admin/users

Sin cuerpo ni parámetros en v1. Retorna la colección completa de usuarios.

Respuesta 200:

~~~json
{
  "success": true,
  "data": [
    {
      "id": "4ebbdb08-dd54-4f7e-949b-d8a249d97c17",
      "usuario": "autonoma",
      "nombre": "Equipo Autonoma",
      "correo": "autonoma@example.test",
      "rol": "admin",
      "activo": true
    }
  ],
  "message": "Usuarios recuperados",
  "timestamp": "2026-10-09T13:22:00Z"
}
~~~

Sin registros devuelve lista vacía `[]` con código 200. Errores: `401 AUTH_REQUIRED`, `401 AUTH_INVALID_TOKEN`, `403 AUTH_USER_INACTIVE`, `403 AUTH_FORBIDDEN` ante rol insuficiente.

### POST /api/v1/auth/admin/users

Creación de nuevas cuentas por parte de un administrador. `password` se almacena exclusivamente hasheada; nunca se devuelve en la respuesta. Campos desconocidos se rechazan.

| Campo payload | Tipo | Regla |
|---|---|---|
| `usuario` | string | Obligatorio; 1–150 caracteres; único; sin `@` |
| `nombre` | string | Obligatorio; 1–150 caracteres |
| `correo` | string | Obligatorio; formato email; normalizado a minúsculas; único |
| `password` | string | Obligatorio; mínimo 12 caracteres mediante validadores de Django |
| `rol` | enum | Opcional; `admin` o `supervisor`; predeterminado `supervisor` |
| `activo` | booleano | Opcional; predeterminado `true` |

Solicitud:

~~~json
{
  "usuario": "psicologo_demo",
  "nombre": "Constanza Silva",
  "correo": "csilva@clinica.cl",
  "password": "Clave-segura-2026-psycode",
  "rol": "supervisor",
  "activo": true
}
~~~

Respuesta 201:

~~~json
{
  "success": true,
  "data": {
    "id": "9439c603-cf13-4749-8ab7-132728ca7182",
    "usuario": "psicologo_demo",
    "nombre": "Constanza Silva",
    "correo": "csilva@clinica.cl",
    "rol": "supervisor",
    "activo": true
  },
  "message": "Usuario creado",
  "timestamp": "2026-10-09T13:22:00Z"
}
~~~

Errores: `400 VALIDATION_ERROR` si falta algún campo obligatorio, si `usuario` o `correo` ya están en uso, si `rol` no es `admin` o `supervisor`, o ante contraseña rechazada.

### PATCH /api/v1/auth/admin/users/{user_id}

Actualización parcial (`partial=True`). Todos los campos del cuerpo son opcionales. No permite modificar `usuario` ni `id`.

| Parámetro / Campo | Tipo | Ubicación | Regla |
|---|---|---|---|
| `user_id` | UUID | Ruta | UUID canónico del usuario objetivo |
| `nombre` | string | Payload | Opcional; 1–150 caracteres |
| `correo` | string | Payload | Opcional; formato email; no colisiona con otro usuario |
| `rol` | enum | Payload | Opcional; `admin` o `supervisor`. Un administrador no puede quitarse su propio rol |
| `activo` | booleano | Payload | Opcional. Un administrador no puede desactivarse a sí mismo por esta vía |

Solicitud:

~~~json
{
  "nombre": "Constanza Silva Henriquez",
  "rol": "admin"
}
~~~

Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "id": "9439c603-cf13-4749-8ab7-132728ca7182",
    "usuario": "psicologo_demo",
    "nombre": "Constanza Silva Henriquez",
    "correo": "csilva@clinica.cl",
    "rol": "admin",
    "activo": true
  },
  "message": "Usuario actualizado",
  "timestamp": "2026-10-09T13:22:00Z"
}
~~~

Errores: `400 VALIDATION_ERROR` por UUID mal formado, correo ya registrado, rol no perteneciente al catálogo (`admin`/`supervisor`), o auto-revocación del rol `admin`; `404 RESOURCE_NOT_FOUND` si el `user_id` válido no existe.

### PATCH /api/v1/auth/admin/users/{user_id}/toggle-active

Invierte el estado de activación de la cuenta (`true` a `false`, o `false` a `true`). Sin cuerpo de petición.

- Parámetro de ruta: `user_id` (UUID canónico).
- Solicitud: sin cuerpo.

Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "id": "9439c603-cf13-4749-8ab7-132728ca7182",
    "usuario": "psicologo_demo",
    "nombre": "Constanza Silva Henriquez",
    "correo": "csilva@clinica.cl",
    "rol": "admin",
    "activo": false
  },
  "message": "Estado de usuario actualizado",
  "timestamp": "2026-10-09T13:22:00Z"
}
~~~

Errores específicos:
- `400 VALIDATION_ERROR`: Si el usuario autenticado intenta modificar su propia cuenta (`"No puedes modificar el estado activo de tu propia cuenta."`) o UUID mal formado.
- `404 RESOURCE_NOT_FOUND`: Si el usuario objetivo no existe.

## 1.2 Configuración operativa

`GET` y `PUT /api/v1/configuracion-operativa`, sin barra final, con JWT de un
administrador activo. Supervisor → `403 AUTH_FORBIDDEN`; sin autenticación →
`401 AUTH_REQUIRED`; JWT de usuario inactivo → `403 AUTH_USER_INACTIVE`.
La restricción de modificación también se aplica en el servicio interno.

Esta API guarda la modalidad principal y la activación independiente del correo
de respaldo. No selecciona ni consulta supervisores, no envía notificaciones y no
modifica la pantalla. El servicio de notificaciones consume la selección guardada
al preparar cada alerta habilitada y aplica el respaldo opcional de SCRUM-80.

### Campos de configuración

| Campo | Tipo / regla |
|---|---|
| `notification_mode` | String único: `lista_distribucion` o `supervisores_activos`. No acepta listas, ambas modalidades, null ni otros valores. |
| `primary_email` | String, máximo 254 caracteres. Se conserva este nombre por compatibilidad; representa el correo de la lista de distribución. Obligatorio y con formato de correo válido cuando la modalidad resultante es `lista_distribucion`. |
| `backup_enabled` | Booleano JSON estricto (`true`/`false`). Independiente de la modalidad principal; no admite strings, números ni null. |
| `backup_email` | String, máximo 254 caracteres. Obligatorio y con formato de correo válido cuando el respaldo resultante está habilitado. |
| `enabled_days` | Lista de enteros 0–6 (lunes–domingo); se guarda ordenada y sin duplicados. |
| `open_time`, `close_time` | Strings de hora local `HH:MM`; apertura anterior al cierre. Si solo se envía uno de los extremos, se valida junto con el otro guardado. |
| `timezone` | String de zona horaria guardada. Solo lectura, como en la API anterior. |
| `updated_at` | Fecha/hora de última modificación en UTC, solo lectura. |

Los correos se recortan y normalizan a minúsculas. Si el destino está inactivo,
su correo puede ser `""` o conservar un valor para reutilizarlo; no se exige
formato de correo en ese estado. Los límites de longitud y el tipo string siguen
aplicando, y null siempre se rechaza. Al reactivar un destino se valida el correo
resultante, incluso si no se incluye en la solicitud. Desactivar un destino no
borra automáticamente su correo.

### GET /api/v1/configuracion-operativa

Devuelve todos los campos anteriores en el envelope común. Si no existe fila,
crea la configuración inicial con modalidad `lista_distribucion`, respaldo
deshabilitado, ambos correos vacíos, lunes a viernes, horario `08:00`–`18:00` y
zona `America/Santiago`. Los correos iniciales vacíos no impiden consultar; el
primer PUT debe satisfacer las condiciones de los destinos activos.

Ejemplo de respuesta 200 para una configuración guardada:

~~~json
{
  "success": true,
  "data": {
    "enabled_days": [0, 1, 2, 3, 4],
    "open_time": "08:00",
    "close_time": "18:00",
    "notification_mode": "lista_distribucion",
    "primary_email": "lista@example.test",
    "backup_enabled": true,
    "backup_email": "respaldo@example.test",
    "timezone": "America/Santiago",
    "updated_at": "2026-10-28T19:00:00Z"
  },
  "message": "Configuración operativa recuperada",
  "timestamp": "2026-10-28T19:00:01Z"
}
~~~

### PUT /api/v1/configuracion-operativa

Recibe un objeto JSON con los campos editables. Mantiene el comportamiento
existente de actualización parcial: los campos omitidos conservan su valor
guardado, incluidos `notification_mode` y `backup_enabled`. No admite campos
desconocidos ni los campos de solo lectura. No se agrega PATCH.

Se combinan los valores recibidos y guardados antes de validar. Toda la operación
es atómica: si hay errores, no cambian correos, preferencias, días, horario ni
`updated_at`. Una primera actualización inválida tampoco crea la fila.
Un cambio exclusivo de preferencias conserva días, horario y zona horaria.

Lista de distribución con respaldo habilitado, conservando el horario:

~~~json
{
  "notification_mode": "lista_distribucion",
  "primary_email": "lista@example.test",
  "backup_enabled": true,
  "backup_email": "respaldo@example.test"
}
~~~

Supervisores activos sin respaldo ni correos:

~~~json
{
  "notification_mode": "supervisores_activos",
  "primary_email": "",
  "backup_enabled": false,
  "backup_email": ""
}
~~~

Ambas modalidades también permiten habilitar el respaldo. No se reciben IDs de
supervisores ni se exige que existan supervisores activos para guardar la modalidad.

Respuesta 200: mismo esquema `data` de GET, con
`message="Configuración operativa actualizada"` y `updated_at` actualizado.
Errores de entrada → `400 VALIDATION_ERROR`, con `error.details.fields` para
los campos afectados. Por ejemplo, al habilitar el respaldo sin correo guardado
ni recibido:

~~~json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Datos de entrada inválidos",
    "details": {
      "fields": {
        "backup_email": ["Este campo no puede estar en blanco."]
      }
    }
  },
  "timestamp": "2026-10-28T19:00:00Z"
}
~~~

El texto de los mensajes puede variar con el idioma; frontend debe usar HTTP,
`error.code` y las claves de `error.details.fields`. Para horarios invertidos o
inválidos se conserva el error existente `400 VALIDATION_ERROR` sin campos.
Aplican también los errores comunes de autenticación y persistencia.

### Migración y compatibilidad para frontend

La migración `operational.0002_notification_preferences` asigna
`notification_mode="lista_distribucion"` y `backup_enabled=true` a las filas
existentes. Conserva exactamente ambos correos, días, horas, zona y `updated_at`,
sin copiar el correo principal a otro campo ni tomar destinatarios del entorno.
También migra los registros antiguos con correos vacíos; su siguiente PUT debe
completar los destinos activos o cambiar la modalidad/deshabilitar el respaldo.

Las configuraciones nuevas tienen respaldo deshabilitado. La migración no crea
una fila si no existía; su reversión conserva los campos anteriores y elimina
los dos nuevos. Aplicar con `uv run python manage.py migrate` antes de iniciar
la versión actualizada del servidor.

Los clientes anteriores pueden continuar usando `primary_email` y `backup_email`
y omitir los campos nuevos: no restablecen la modalidad ni la activación del
respaldo. Deben tolerar los campos adicionales de respuesta. Esta entrega deja
el contrato disponible para las tareas de frontend; el formulario actual sigue
sin controles para las nuevas preferencias.

## 2. Alertas y evaluaciones

SCRUM-32, 33, 34, 37, 39 y 40. Todas requieren autenticación. No hay creación, modificación general ni borrado públicos de alertas. Persistencia: [esquema MongoDB](docs/MONGODB.md).

### Esquemas

| Campo de alerta | Tipo | Presencia / regla |
|---|---|---|
| `alerta_id` | UUID | Listado y detalle; único e inmutable |
| `box` | string | Listado y detalle; 1–64 caracteres |
| `tipo_riesgo` | string | Listado y detalle; 1–100; sin catálogo inventado |
| `nivel_severidad` | integer | Listado y detalle; solo 1, 2 o 3; no booleano |
| `semaforo` | enum | Listado y detalle; BAJO, MEDIO o ALTO; derivado unívocamente del nivel |
| `fecha_hora` | fecha/hora UTC | Listado y detalle; detección, no evaluación |
| `estado_evaluacion` | enum | Listado y detalle; pendiente, correcta, falso_positivo, neutro |
| `evaluacion` | Evaluation o null | Listado y detalle; null si pendiente |
| `sesion_id` | UUID | Solo detalle; referencia de sesión clínica, no sesión JWT |
| `descripcion` | string o null | Solo detalle; fragmento relevante de transcripción asociado a la alerta; máximo 500 caracteres; se normalizan espacios y Unicode; ausente o vacío se normaliza a null | 
| `trazabilidad` | objeto | Solo detalle: registrada_en, actualizada_en (UTC), origen (string 1–100) |

Evaluation tiene la misma forma en GET/POST y dentro de alertas:

| Campo | Tipo / significado |
|---|---|
| `alerta_id` | UUID de alerta |
| `evaluacion` | correcta, falso_positivo o neutro |
| `usuario_id` | UUID profesional; adición para trazabilidad estable |
| `usuario` | Nombre de usuario profesional al evaluar, string; campo del borrador |
| `fecha_hora` | UTC de evaluación asignada por servidor |
| `estado_evaluacion` | Igual a evaluacion |

Para SCRUM-40, “resultado de revisión” es evaluacion; no se inventa otra puntuación. La revisión no modifica severidad detectada.

### GET /api/v1/alerts

Total cuenta coincidencias antes de paginar. Orden fijo: fecha_hora descendente, alerta_id ascendente como desempate. Offset no garantiza una instantánea frente a inserciones entre peticiones.

| Parámetro | Tipo / predeterminado | Semántica |
|---|---|---|
| `q` | string 1–100; omitido | Subcadena literal sin distinguir mayúsculas sobre alerta_id, box o tipo_riesgo; OR entre esos campos |
| `fecha_desde` | YYYY-MM-DD; sin límite inferior | Día inicial inclusivo en Santiago |
| `fecha_hasta` | YYYY-MM-DD; sin límite superior | Día final inclusivo en Santiago |
| `box` | string 1–64; omitido | Coincidencia exacta, sensible a mayúsculas |
| `estado_evaluacion` | enum de estado; omitido | Coincidencia exacta |
| `revisadas` | true o false; omitido | true: distinto de pendiente; false: pendiente |
| `limit` | integer, 50 | Entre 1 y 100 |
| `offset` | integer, 0 | Mayor o igual a cero |

Filtros se combinan con AND. Combinaciones contradictorias como revisadas=true y estado_evaluacion=pendiente son válidas y devuelven cero coincidencias. No interpretar q como regex ni consulta MongoDB.

Rango invertido o fecha inválida → 400. Inicio del primer día local se convierte a UTC; fin se expresa como inicio del día posterior al último, exclusivo. Respetar cambios de hora: un día local no siempre dura 24 horas. Sin fechas no se limita período.

Ejemplo: `GET /api/v1/alerts?box=box-3&revisadas=true&fecha_desde=2026-09-01&fecha_hasta=2026-09-30&limit=50&offset=0`.

Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "total": 1,
    "limit": 50,
    "offset": 0,
    "items": [
      {
        "alerta_id": "11111111-1111-4111-8111-111111111111",
        "box": "box-3",
        "tipo_riesgo": "riesgo_suicida",
        "nivel_severidad": 2,
        "semaforo": "BAJO",
        "fecha_hora": "2026-09-12T14:05:22Z",
        "estado_evaluacion": "correcta",
        "evaluacion": {
          "alerta_id": "11111111-1111-4111-8111-111111111111",
          "evaluacion": "correcta",
          "usuario_id": "22222222-2222-4222-8222-222222222222",
          "usuario": "psicologo",
          "fecha_hora": "2026-09-12T15:10:00Z",
          "estado_evaluacion": "correcta"
        }
      }
    ]
  },
  "message": "Lista paginada de recursos",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Sin coincidencias: total cero e items vacío, limit/offset solicitados. Offset posterior a última coincidencia: items vacío y total real, aunque no sea cero. Aplican errores comunes; no 404 por lista vacía.

### GET /api/v1/alerts/{alerta_id}

Sin parámetros ni cuerpo. Ejemplo pendiente, respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "alerta_id": "11111111-1111-4111-8111-111111111111",
    "box": "box-3",
    "tipo_riesgo": "riesgo_suicida",
    "nivel_severidad": 2,
    "semaforo": "BAJO",
    "fecha_hora": "2026-09-12T14:05:22Z",
    "estado_evaluacion": "pendiente",
    "evaluacion": null,
    "sesion_id": "33333333-3333-4333-8333-333333333333",
    "descripcion": null,
    "trazabilidad": {
      "registrada_en": "2026-09-12T14:05:23Z",
      "actualizada_en": "2026-09-12T14:05:23Z",
      "origen": "datos_sinteticos"
    }
  },
  "message": "Detalle de alerta",
  "timestamp": "2026-09-12T14:06:00Z"
}
~~~

Si evaluada, evaluacion contiene Evaluation y estado correspondiente. Error específico: `404 ALERTA_NO_ENCONTRADA`.
`descripcion` representa únicamente el fragmento relevante de transcripción que originó la posible alerta. No corresponde a la transcripción completa de la sesión ni al audio original. El campo se entrega solo en el endpoint de detalle y no forma parte del listado general de alertas.

### POST /api/v1/alerts/{alerta_id}/evaluacion

Único campo permitido y obligatorio:

~~~json
{ "evaluacion": "correcta" }
~~~

Valores: correcta, falso_positivo, neutro. Autor y fecha vienen del contexto autenticado y reloj UTC; rechazar usuario, usuario_id, fecha_hora o estado enviados por cliente.

Respuesta 201:

~~~json
{
  "success": true,
  "data": {
    "alerta_id": "11111111-1111-4111-8111-111111111111",
    "evaluacion": "correcta",
    "usuario_id": "22222222-2222-4222-8222-222222222222",
    "usuario": "psicologo",
    "fecha_hora": "2026-09-12T15:10:00Z",
    "estado_evaluacion": "correcta"
  },
  "message": "Evaluación registrada",
  "timestamp": "2026-09-12T15:10:00Z"
}
~~~

Cabecera Location para este ejemplo: `/api/v1/alerts/11111111-1111-4111-8111-111111111111/evaluacion`.

Errores: `400 VALIDATION_ERROR`, `404 ALERTA_NO_ENCONTRADA`, `409 EVALUACION_YA_REGISTRADA`. Una evaluación por alerta, sin edición en v1. Repetir el mismo resultado también produce 409; si se perdió la respuesta, consultar GET evaluación.

Dos POST concurrentes sobre pendiente deben producir un 201 y un 409, salvo fallo de infraestructura. Evaluación, estado y fecha de actualización se guardan atómicamente.

### GET /api/v1/alerts/{alerta_id}/evaluacion

Sin cuerpo ni parámetros. Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "alerta_id": "11111111-1111-4111-8111-111111111111",
    "evaluacion": "correcta",
    "usuario_id": "22222222-2222-4222-8222-222222222222",
    "usuario": "psicologo",
    "fecha_hora": "2026-09-12T15:10:00Z",
    "estado_evaluacion": "correcta"
  },
  "message": "Evaluación de alerta",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Errores: `404 ALERTA_NO_ENCONTRADA` si falta alerta; `404 EVALUACION_NO_ENCONTRADA` si existe y sigue pendiente.

## 3. Dashboard

SCRUM-36; autenticación obligatoria. Ambos GET aceptan:

| Parámetro | Regla |
|---|---|
| `periodo` | semanal o mensual; predeterminado semanal |
| `fecha_referencia` | YYYY-MM-DD dentro del período deseado; predeterminado hoy en Santiago |

Semana lunes–domingo; mes calendario completo. Respuestas agregan fecha_desde y fecha_hasta inclusivas y zona_horaria America/Santiago. Usar mismo intervalo convertido a UTC en ambas consultas. Fecha futura válida se consulta normalmente: sin registros, ceros.

Se cuenta por fecha de detección y evaluación **actual**, no por fecha de evaluación ni estado histórico al cerrar el período. Revisadas incluye correcta, falso_positivo y neutro. No excluir falsos positivos de totales ni alterar su severidad.

### GET /api/v1/dashboard/resumen

Ejemplo: `?periodo=semanal&fecha_referencia=2026-09-12`.

Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "periodo": "semanal",
    "fecha_desde": "2026-09-07",
    "fecha_hasta": "2026-09-13",
    "zona_horaria": "America/Santiago",
    "total_alertas": 3,
    "pendientes": 1,
    "revisadas": 2,
    "por_severidad": { "nulo": 0, "bajo": 1, "medio": 1, "alto": 1 }
  },
  "message": "Resumen de alertas",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Conteos enteros no negativos. Pendientes + revisadas = total_alertas; suma de severidades = total_alertas. Se conservan las cuatro claves minúsculas del contrato anterior; `nulo` se mantiene en cero porque los resultados sin riesgo no se almacenan como alertas. Sin datos todas las cantidades son cero.

### GET /api/v1/dashboard/estadisticas

Mismos parámetros. Respuesta 200:

~~~json
{
  "success": true,
  "data": {
    "periodo": "semanal",
    "fecha_desde": "2026-09-07",
    "fecha_hasta": "2026-09-13",
    "zona_horaria": "America/Santiago",
    "total": 3,
    "registros": [
      { "fecha": "2026-09-08", "total": 1 },
      { "fecha": "2026-09-12", "total": 2 }
    ]
  },
  "message": "Estadísticas de alertas",
  "timestamp": "2026-09-12T15:30:00Z"
}
~~~

Una fila por día local con alertas, orden ascendente; omitir días sin datos. Suma de registros = total. Frontend puede rellenar días faltantes con cero para gráfico. Sin datos: total cero, registros vacío, conservando período/límites/zona.

Para alertas individuales del período usar GET alerts con fechas devueltas. Ambas rutas: 400 por período/fecha inválidos y errores comunes. No se define tiempo real ni caché en esta fase.

## 4. Registro y notificaciones: contratos internos

No son HTTP ni usan envelope público. Conectan SCRUM-32 y SCRUM-41; no implican un productor automático.

### register_alert(input) → RegistrationResult

Entrada tipada obligatoria: alerta_id, box, tipo_riesgo, nivel_severidad (1–3), fecha_hora, sesion_id, origen; descripcion opcional. `descripcion` corresponde al fragmento relevante de transcripción asociado a la alerta, con máximo 500 caracteres. No se admite como sustituto de una transcripción completa ni del audio original.
Tipos y límites del esquema de alerta. El llamador aporta UUID para detectar duplicados. No aceptar semáforo, estado, evaluación ni fechas de trazabilidad como autoridad del llamador. Resultados NULO o sin riesgo se omiten antes de llamar a `register_alert`; no se guardan como alertas de riesgo.

Flujo: validar nivel 1–3 → derivar semáforo → estado pendiente y evaluación null → fechas de trazabilidad del servidor → persistir → notificar si corresponde. Un nivel fuera del rango se rechaza; NULO/sin riesgo no entra a este flujo.

La implementación `AlertsService.register_alert` devuelve la alerta persistida. El resultado detallado de envío se obtiene mediante `NotificationService.notify_alert`; los intentos quedan en la bitácora. Duplicado → `AlertAlreadyExists`, sin nuevo envío; datos inválidos → `ServiceError(VALIDATION_ERROR)`; persistencia caída → `PersistenceUnavailable`, sin envío. Un fallo de notificación conserva la alerta. La composición del trabajador inyecta el notificador; el seed lo omite.

Prototipo: las alertas válidas de nivel 1–3 pueden notificar. NULO/sin riesgo no se registra como alerta ni se envía. NOTIFICATIONS_ENABLED=false omite todos los envíos de desarrollo y datos sintéticos. Repositorios no envían mensajes.

### notify_alert(alerta_id, payload) → NotificationResult

UUID es contexto interno de auditoría. `NotificationPayload` contiene `nivel_riesgo` (BAJO, MEDIO o ALTO), `tipo_riesgo`, `box` y `fecha_hora`. Se omiten NULO/sin riesgo y niveles desconocidos. El notificador verifica primero que el UUID exista en MongoDB y reconstruye el mensaje desde esa alerta, con tipo constante `riesgo_suicida`; no utiliza texto libre del llamador. No se envían descripción, sesión, identificadores personales, audio ni transcripción.

Antes de cada notificación habilitada se consulta la configuración y los destinatarios actuales. En `supervisores_activos` se incluyen únicamente cuentas habilitadas con rol Supervisor, excluyendo superusuarios, sin requerir sesión. Se validan los correos registrados y se deduplican ignorando mayúsculas y espacios externos. En `lista_distribucion` se usa `primary_email`; si falta configuración operativa no hay destinatarios. `NOTIFICATION_EMAIL_TO` nunca sustituye la selección guardada. Sin destinatarios principales válidos no se hacen intentos principales: en modalidad de supervisores con respaldo habilitado se intenta el respaldo; en los demás casos se devuelve `SIN_DESTINATARIOS_VALIDOS` sin envíos. Cada dirección recibe un mensaje independiente sin direcciones ajenas; rechazos, timeouts y excepciones individuales no detienen los siguientes intentos. No se cambia de modalidad ante errores. Un fallo principal total o parcial activa un único intento de respaldo si está habilitado; no recibe copia cuando todos los envíos principales son exitosos. Teams no participa, incluso si existe un webhook configurado. Sin reintentos automáticos. Cada intento SMTP tiene un plazo completo `EMAIL_TIMEOUT_SECONDS` (10 segundos por defecto) mediante proceso cancelable; `EMAIL_TIMEOUT` limita además los sockets. La aceptación SMTP no garantiza entrega ni lectura.

`NotificationResult` contiene:

| Campo | Tipo / regla |
|---|---|
| `alerta_id` | UUID de la alerta |
| `enviado` | bool: al menos un envío aceptado |
| `canal_exitoso` | `email` o null |
| `intentos` | Lista ordenada de `AttemptResult(canal, exitoso, duracion_ms, error)` |
| `motivo_omision` | null, `NULO_O_SIN_RIESGO`, `ALERTA_NO_ALMACENADA`, `NOTIFICATIONS_DISABLED`, `SIN_DESTINATARIOS_VALIDOS` |
| `estado` | `EXITO_TOTAL`, `FALLO_PARCIAL`, `FALLO_TOTAL`, `SIN_DESTINATARIOS_VALIDOS` u `OMITIDA` |

`EXITO_TOTAL` significa que todos los destinatarios fueron aceptados; `FALLO_PARCIAL`, que al menos uno fue aceptado y otro falló; `FALLO_TOTAL`, que todos fallaron. `OMITIDA` cubre las condiciones previas sin intentos. `enviado=true` también en fallo parcial.

Cada intento genera un evento `notifications.send` con UUID de alerta/sesión, timestamp UTC, actor Sistema, canal email, resultado, duración y código estable. `contingencia=false` identifica los intentos principales y `true` los de respaldo; nunca se guarda la dirección destinataria. El arreglo histórico `intentos` se conserva vacío: cada intento ocupa su propio evento. El objeto `notification={id,mode,phase,reason,attempt}` sirve para correlacionar los intentos de una ejecución y registrar su modalidad. Al terminar se emite `notifications.result` con el mismo `id`, `phase=resumen`, `status` y los conteos `primary_successes`, `primary_failures`, `backup_successes`, `backup_failures`, sin `attempt`. La ausencia de principales válidos se conserva como `reason=SIN_DESTINATARIOS_VALIDOS`, incluso cuando el respaldo recupera el envío. [Formato y semántica completos](backend/apps/notifications/README.md#trazabilidad-de-notificaciones).

Errores: `NOTIFICATION_TIMEOUT`, `NOTIFICATION_CONNECTION_FAILED`, `NOTIFICATION_REJECTED`, `NOTIFICATION_NOT_CONFIGURED`, `NOTIFICATION_INTERNAL_ERROR`. No se almacenan errores libres ni respuestas de proveedor. Los fallos de envío no eliminan la alerta. No hay cola duradera ni garantía de entrega tras una caída entre persistencia y envío.

### Consulta de bitácora (SCRUM-65)

`GET /api/v1/audit-events`, JWT obligatorio; solo usuarios activos con rol `admin`, o superusuarios. Anónimo → 401, rol no autorizado → 403, persistencia indisponible → 503. Otros métodos → 405.

| Parámetro | Regla |
|---|---|
| `fecha_desde`, `fecha_hasta` | ISO 8601 fecha/hora; extremos inclusivos, convertidos a UTC. Sin zona se interpreta UTC. Desde no puede superar hasta. |
| `alerta_id` | UUID válido |
| `action` | `alerts.register`, `alerts.evaluate`, `notifications.send`, `notifications.result`, `analysis.speechmatics`, `analysis.jev`, `alerts.flow` |
| `outcome` | `success`, `failure`, `skipped` |
| `order` | `asc` por defecto, o `desc`; timestamp y event_id como desempate |
| `limit` | 1–100, por defecto 50 |
| `offset` | ≥ 0, por defecto 0 |

Parámetros desconocidos, repetidos o inválidos → 400. Los filtros se combinan con AND. Devuelve el envelope habitual con `data={total, limit, offset, items}`. Una consulta sin coincidencias devuelve 200 y lista vacía. Paginación por offset: nuevas inserciones entre consultas pueden desplazar páginas.

Cada item incluye `event_id`, `timestamp`, `action`, `outcome`, `actor` (nombre de usuario, `Sistema` o identificación alternativa `Usuario (UUID)`), `actor_id` (UUID original o null), `alerta_id` (UUID o null), `sesion_id` (UUID o null), `sequence` (entero no negativo o null), `channel`, `contingencia`, `error_code`, `duration_ms` y `notification` (objeto técnico de notificación o null si el evento no lo registró).

El campo `actor` se resuelve al consultar la bitácora utilizando el UUID del actor y las cuentas existentes. Si la cuenta está disponible, devuelve su `username`. Si la cuenta original ya no existe o su UUID no corresponde a una cuenta disponible, devuelve `Usuario (UUID original)` como identificación alternativa, sin atribuir el evento a otra persona.

La resolución también se aplica a eventos históricos que solo almacenan `actor_id`, sin modificar los documentos originales. Las cuentas se consultan en un único lote por página para evitar consultas individuales por evento.

Las fechas se expresan en UTC. La evaluación utiliza el usuario autenticado. No se incluyen nombres completos, correos, cuerpos de mensajes ni campos ajenos a la lista permitida. Los campos históricos de sesión o secuencia ausentes se presentan como null.

Ejemplo: `/api/v1/audit-events?alerta_id=11111111-1111-4111-8111-111111111111&action=notifications.send&outcome=failure&order=asc&limit=20&offset=0`.

## 5. Ingesta interna de fragmentos

Implementada: `POST /api/v1/internal/fragments`, sin barra final. Recibe un archivo,
lo valida y lo deja en almacenamiento privado temporal con un trabajo SQL
`pendiente`. No controla OBS, analiza audio, genera alertas ni envía notificaciones.
La respuesta utiliza el envelope JSON común. No hay descarga pública del archivo
ni rutas HTTP de administración de la cola.

### Autenticación y autorización de agentes

Cabecera obligatoria: `Authorization: Agent <agent_id>.<secret>`. No se admiten
JWT de profesionales, sesiones de navegador ni tokens en query string o campos
multipart. La autenticación ocurre antes de leer o almacenar la carga.

`CAPTURE_AGENTS` es un objeto JSON del entorno, vacío por defecto; vacío deniega
todo acceso. Cada clave identifica un agente y su valor tiene exactamente
`box` y `token_sha256`. El identificador usa 1–64 caracteres ASCII alfanuméricos,
`_` o `-`. El secreto usa 43–128 caracteres de ese alfabeto; provisionar al menos
32 bytes aleatorios, por ejemplo con `secrets.token_urlsafe(32)`.
`token_sha256` contiene el SHA-256 hexadecimal en minúsculas de **todo** el token
`<agent_id>.<secret>`, sin el prefijo `Agent `, comparado en tiempo constante.
El backend conserva el hash; el agente recibe el token por un canal privado.

Ejemplo de estructura, cuyos marcadores deben sustituirse al provisionar:

~~~json
{
  "agent-box-3": {
    "box": "box-3",
    "token_sha256": "<SHA-256 del token completo: 64 caracteres hexadecimales>"
  }
}
~~~

Cada identidad solo puede enviar para su box asignado (`box-3` a `box-7`).
Se comprueba además que `session_id` pertenezca al mismo box. Quitar o rotar la
credencial exige actualizar el entorno y reiniciar todos los procesos API.
Una configuración mal formada impide arrancar, con un error fijo sin secretos.
Usar HTTPS y publicar esta ruta únicamente en la red de los agentes.

### Campos y límites

Content-Type: `multipart/form-data; boundary=...`. Exactamente un archivo y los
seis campos de texto siguientes, todos obligatorios y sin repeticiones. Los
campos desconocidos se rechazan. Se exige el cierre multipart completo, sin
epílogo. El nombre del archivo y su MIME declarado no determinan el formato y
no se guardan ni aparecen en respuestas o errores.

| Campo | Tipo y regla |
|---|---|
| `archivo` | Archivo no vacío; WAV RIFF completo, PCM lineal sin compresión, mono, 16 kHz y 16 bits. Debe contener datos no vacíos y frames de 2 bytes completos. Se comprueban longitudes reales de RIFF y chunks. |
| `box` | Texto exacto `box-3`, `box-4`, `box-5`, `box-6` o `box-7`; debe coincidir con la identidad autenticada. |
| `session_id` | UUID de sesión de captura persistente, distinto de una sesión JWT. |
| `secuencia` | Entero decimal desde `0` hasta `9223372036854775806`, sin decimales ni ceros iniciales. Consecutivo por sesión desde `0`. |
| `formato` | `wav`. Otros formatos o perfiles PCM se rechazan. |
| `checksum` | SHA-256 de todos los bytes del archivo: exactamente 64 caracteres `[0-9a-f]`, sin prefijo. Se recalcula en el backend. |
| `captured_at` | Fecha/hora ISO 8601 con zona horaria, máximo 40 caracteres. Es el instante de captura; se exige para validar fragmentos retrasados durante la finalización. |

Límite inclusivo de archivo: **25 MiB (26.214.400 bytes)** por defecto, configurable
con `CAPTURE_FRAGMENT_MAX_BYTES` (entero positivo). El cuerpo multipart completo
no puede superar ese límite más **64 KiB (65.536 bytes)**. Se verifican tanto
Content-Length como los bytes realmente leídos; declarar un tamaño menor no
evita el límite. La carga se escribe en streaming a un temporal privado, sin
acumular el audio completo en memoria.

Ejemplo de envío; las variables contienen la URL interna HTTPS, credencial,
UUID de sesión, checksum real e instante de captura proporcionados por el agente:

~~~sh
curl --request POST "$PSYCODE_INTERNAL_BASE_URL/api/v1/internal/fragments" \
  --header "Authorization: Agent $PSYCODE_AGENT_TOKEN" \
  --form 'archivo=@fragment.wav;type=audio/wav' \
  --form 'box=box-3' \
  --form "session_id=$CAPTURE_SESSION_ID" \
  --form 'secuencia=0' \
  --form 'formato=wav' \
  --form "checksum=$FRAGMENT_SHA256" \
  --form "captured_at=$FRAGMENT_CAPTURED_AT"
~~~

Una secuencia nueva requiere sesión `activa` o `finalizando` e inicio real
confirmado. Se recuperan vencimientos antes de aceptarla. `captured_at` no puede
ser futuro, anterior al inicio real ni anterior a la secuencia previa; tampoco
puede superar el fin programado, la solicitud de detención o la detención
confirmada. Se aplica el menor límite disponible. Los tiempos se comparan como
instantes con zona horaria.

La última secuencia se informa mediante la confirmación de detención de
`BoxAgentControl.acknowledge(..., last_sequence=N)`, ya existente; no es un campo
del upload. Una vez informada, **ninguna secuencia mayor que N se acepta**,
aunque la sesión siga finalizando por fragmentos pendientes. `N=-1` significa
que no hubo fragmentos. Se completa la sesión solo al confirmar la detención y
haber aceptado todas las secuencias hasta N; el procesamiento de los trabajos
es independiente del cierre de captura.

### Aceptación, reintentos y consistencia

La clave única SQL es **(`session_id`, `secuencia`)**. Una relación uno a uno
impide más de un trabajo por secuencia. La API serializa las actualizaciones
con el bloqueo transaccional de sesión y las restricciones SQL entre procesos.

| Caso | Resultado |
|---|---|
| Secuencia nueva válida | 201; archivo aceptado, secuencia y trabajo `pendiente` persistidos. |
| Misma clave, checksum, tamaño, formato e instante de captura | 200; misma confirmación, sin crear archivo permanente adicional, trabajo ni evento de aceptación. Se vuelve a validar el archivo enviado. |
| Misma clave con otro checksum o metadatos de captura contradictorios | 409 `SEQUENCE_CONFLICT`; conserva el archivo y trabajo originales. |
| Secuencia registrada antes mediante el puerto interno sin trabajo de ingesta | 409 `SEQUENCE_ALREADY_REGISTERED`; no se reemplaza ni se adjunta un archivo a un registro histórico. |
| Salto de secuencia o número superior al último informado | 409; no crea trabajo. Reintentar saltos después de las secuencias anteriores. |

Los reintentos idénticos siguen devolviendo 200 si la sesión ya se completó o
falló, o si el trabajo cambió de estado. La credencial debe seguir autorizada.
El `estado` de la respuesta es la confirmación fija `aceptado`, no el estado
actual del procesamiento. El `timestamp` del envelope corresponde a cada
respuesta; los campos de `data` se conservan.

Antes del commit SQL, el archivo validado se sincroniza a disco y se publica
con el nombre definitivo: `fsync` del directorio en POSIX y `MoveFileExW` con
`MOVEFILE_WRITE_THROUGH` en Windows. Secuencia, contador de sesión, trabajo y bitácora se
guardan en **una transacción SQL**. Se responde con éxito solo tras el commit;
la vista no participa en una transacción externa que pueda revertir después.
No se introduce una transacción distribuida entre archivos y SQL: una caída
previa al commit puede dejar un huérfano que elimina la limpieza. Si el resultado
del commit es incierto, se devuelve error y se conserva el archivo; un reintento
resuelve si quedó aceptado sin duplicar el trabajo.

### Respuestas

201 para creación; 200 para reintento idéntico. `job_id` identifica el trabajo
durable, `size_bytes` incluye todos los bytes WAV y `accepted_at` es la primera
aceptación en UTC. No se exponen rutas, nombres originales ni contenido.

~~~json
{
  "success": true,
  "data": {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "session_id": "11111111-1111-4111-8111-111111111111",
    "box": "box-3",
    "secuencia": 0,
    "formato": "wav",
    "checksum": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 364,
    "accepted_at": "2026-10-24T15:00:20Z",
    "estado": "aceptado"
  },
  "message": "Fragmento recibido",
  "timestamp": "2026-10-24T15:00:20Z"
}
~~~

### Errores

Todos usan el envelope común con `details={}`; no reflejan campos, valores,
nombres de archivos, credenciales, excepciones, audio ni contenido clínico.
401 utiliza **`WWW-Authenticate: Agent`**, excepción al esquema Bearer público.

| HTTP | Código | Situación |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Multipart incompleto o inválido, campos ausentes, desconocidos, repetidos, UUID/checksum/fecha/secuencia inválidos, o más de un archivo. |
| 401 | `AUTH_REQUIRED` | Sin credencial de agente. |
| 401 | `AUTH_INVALID_TOKEN` | Credencial inválida, desconocida o revocada; incluye JWT de profesionales. |
| 403 | `AUTH_FORBIDDEN` | Box enviado distinto del autorizado para el agente. |
| 404 | `SESSION_NOT_FOUND` | Sesión inexistente o que no pertenece al box autorizado. |
| 405 | `METHOD_NOT_ALLOWED` | Método distinto de POST/OPTIONS; incluye Allow. |
| 409 | `SESSION_NOT_ACCEPTING_SEQUENCES` | Secuencia nueva en sesión iniciada, completada, fallida o vencida. |
| 409 | `SEQUENCE_OUT_OF_ORDER` | Secuencia no consecutiva o superior al último número informado. |
| 409 | `SEQUENCE_OUTSIDE_CAPTURE_WINDOW` | Instante de captura fuera de la ventana permitida. |
| 409 | `INVALID_TIMESTAMP` | Instante de captura anterior al de la secuencia previa. |
| 409 | `SEQUENCE_CONFLICT` | La clave ya existe con otro checksum o metadatos contradictorios. |
| 409 | `SEQUENCE_ALREADY_REGISTERED` | Registro histórico sin trabajo de ingesta. |
| 413 | `FRAGMENT_TOO_LARGE` | Límite de archivo, cuerpo o memoria de campos multipart excedido. |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Content-Type distinto de multipart/form-data. |
| 415 | `FRAGMENT_FORMAT_UNSUPPORTED` | Formato declarado o perfil de audio no admitido. |
| 422 | `EMPTY_FRAGMENT` | Archivo de cero bytes. |
| 422 | `INVALID_FRAGMENT_FILE` | RIFF/WAV corrupto, truncado, sin datos o con tamaños inconsistentes. |
| 422 | `CHECKSUM_MISMATCH` | SHA-256 calculado distinto del declarado. |
| 503 | `FRAGMENT_STORAGE_UNAVAILABLE` | Almacenamiento privado no disponible o fallo de sincronización. |
| 503 | `PERSISTENCE_UNAVAILABLE` | Persistencia SQL no disponible o commit sin confirmación. |
| 500 | `INTERNAL_ERROR` | Fallo inesperado; no confirma recepción. |

Cuando coinciden varias causas, el primer control que falla determina el error.
En sesiones cerradas una secuencia posterior puede responder
`SESSION_NOT_ACCEPTING_SEQUENCES`; nunca se acepta por haber cerrado.

### Almacenamiento temporal, limpieza y cola

`CAPTURE_FRAGMENT_ROOT` apunta a un directorio privado fuera de estáticos y media,
por defecto `.local/capture-fragments`. En POSIX se usan directorio 0700 y
archivos 0600; en Windows deben protegerse mediante las ACL del directorio
privado del usuario o servicio. Los nombres son aleatorios sin contexto clínico.
Debe residir en un volumen local persistente que soporte sincronización y
bloqueos de archivo (`flock` en POSIX, `LockFileEx` en Windows). Todos los
procesos API y de limpieza comparten ese volumen y la misma base SQL.
Se soportan Windows nativo, macOS y Linux, sin instalar `fcntl` por separado.
La bitácora registra solo identificadores técnicos, estado, secuencia y códigos
permitidos; nunca nombres, bytes, checksum, transcripciones ni secretos. No
habilitar registro de cuerpos de solicitudes en proxies o instrumentación.

Las cargas interrumpidas se eliminan al cerrar el request. Para recuperar
temporales abandonados por caídas, ejecutar al arrancar y periódicamente:

~~~sh
uv run python manage.py cleanup_capture_uploads
# Ajuste opcional para una ejecución:
uv run python manage.py cleanup_capture_uploads --older-than-seconds 3600
~~~

`CAPTURE_ORPHAN_MAX_AGE_SECONDS` fija la antigüedad mínima por defecto (3600 s).
Solo se eliminan archivos de nombres gestionados, antiguos, sin lease activo
y sin trabajo SQL que los referencie. Se conservan los archivos de **todos**
los trabajos, incluidos pendientes y en procesamiento; no se sigue symlinks.
Un error de SQL impide tratar un archivo como huérfano. El comando informa
solo cantidades, y no inicia captura, análisis ni otros procesos.

`FragmentJob` es la cola persistente SQL con estados `pendiente`, `procesando`,
`completado` y `fallido`; la API solo crea `pendiente`. Su consumidor, reintentos
de procesamiento y eliminación de archivos aceptados tras procesar corresponden
a la integración del trabajador, fuera de esta entrega. Hasta entonces los
archivos referenciados permanecen disponibles y la limpieza no los vence.

## 6. Seguridad, compatibilidad y cambios

- HTTPS en producción y CORS restringido al origen del frontend.
- Audio solo en el almacenamiento temporal privado de ingesta descrito en la sección 5; nunca en logs, errores, bitácoras o respuestas. No registrar contraseñas, tokens ni URLs secretas. Notificaciones con contenido mínimo.
- Auditoría técnica de operaciones críticas; evaluación con trazabilidad persistida.
- UUID de profesional estable aunque cambie nombre visible; sin joins ni transacción entre bases.
- Validación de contratos con datos sintéticos no implica validación diagnóstica ni autorización clínica.
- Cambios incompatibles tras adoptar v1 requieren coordinación y nueva versión. Revisión documental 1.1 no crea /api/v1.1/.

Frente al borrador: nombre Psycode API; envelopes completos/excepción 204; nombres Django; comportamiento de tokens y recuperación; revisadas, Evaluation uniforme y usuario_id; nulabilidad; límites de filtros; fecha_referencia y límites/zona del dashboard; errores coherentes; resultado interno de envíos.

Se conserva 404 de recuperación. Usuario de evaluación se define como nombre de usuario, aunque el ejemplo anterior usaba correo; no cambia nombre ni tipo de campo. Se reemplazan marcadores “uuid” por UUID válidos. ALERTA_NO_ENCONTRADA sustituye el uso contradictorio de RESOURCE_NOT_FOUND para alertas; este último queda para rutas desconocidas.

## Anexo A — Niveles de riesgo del proyecto

El campo persistido `nivel_severidad` usa la escala operativa acordada para alertas de riesgo. No replica el gradiente 0–7 de los documentos fuente ni constituye una escala diagnóstica. NULO/sin riesgo no es una alerta y debe omitirse antes de `register_alert`.

| `nivel_severidad` | Categoría operativa | `semaforo` |
|---|---|---|
| 1 | Riesgo bajo | BAJO |
| 2 | Riesgo medio | MEDIO |
| 3 | Riesgo alto | ALTO |

La relación es única y automática. Los valores menores que 1, mayores que 3, no enteros y booleanos se rechazan. La conversión o retiro de documentos históricos 0–7 se describe en [MONGODB.md](docs/MONGODB.md#actualización-de-la-escala-histórica).

Los materiales fuente pueden organizar categorías clínicas con otra numeración; no se debe inferir equivalencia exacta con C-SSRS ni diagnóstico. Cualquier clasificación requiere validación clínica, cultural y externa antes de producción.


## Continuidad de captura: extensiones aditivas

La política de vencimientos de recepción descrita en secciones anteriores queda
actualizada por [Continuidad de captura](docs/CONTINUIDAD-CAPTURA.md). Los estados,
mensajes WS, uploads y recibos v1/v2 conservan su formato. Una ausencia de red
produce diagnóstico; no invalida automáticamente audio capturado dentro de la
ventana original. La recepción automática dura siete días desde el límite de
captura; después requiere `resume_capture_reception`, conservando pendientes.

| Método | Ruta interna | Uso |
|---|---|---|
| GET | `/api/v1/internal/sessions/<uuid>` | Captura, recepción y procesamiento separados, limitado al box autenticado. |
| POST | `/api/v1/internal/sessions/<uuid>/capture-ended` | Evidencia física durable de detención, independiente del ACK y los uploads. |
| POST | `/api/v1/internal/agent-events` | Hasta 64 eventos técnicos, JSON de hasta 64 KiB, deduplicación por agente/evento. |

Todas usan `Authorization: Agent <agent_id>.<secret>`, sin JWT de profesionales.
`capture-ended` admite `last_sequence: null` para un manifiesto desconocido; no
lo convierte en `-1` ni inventa una confirmación de orden. Conserva fecha/motivo
y permite enriquecer únicamente la secuencia desconocida. El recibo devuelve
la proyección de sesión. El cierre físico libera el box para otra captura
central autorizada; no completa recepción ni procesamiento pendientes.

`agent-events` recibe `{version: "1.0", events: [...]}` conforme al esquema
versionado. Fija identidad/box desde la credencial. La confirmación contiene
`data.accepted_event_ids` con todos los UUID del lote. Repetir contenido idéntico
mantiene el evento y su fecha de recepción originales; cambiar una identidad
existente devuelve `409 EVENT_CONFLICT` y revierte el lote. Causas/tipos tienen
lista cerrada; se rechazan campos adicionales y contenido libre. No contiene
audio, rutas, tokens ni transcripciones.

Los schemas `contracts/agent-events-v1.schema.json` y
`contracts/capture-ended-v1.schema.json`, incluidos en `manifest.json`, son la
referencia para solicitudes. El `ready` anuncia `agent.events.v1` y
`sessions.capture-ended.v1`. Desplegar/migrar primero central y después agentes.


## Almacenamiento del servidor

Solo administrador activo, con la autenticación vigente y CSRF al usar cookies.
Todas las respuestas son privadas y `no-store`.

| Método y ruta | Función |
|---|---|
| `GET /api/v1/almacenamiento/panel` | Panel HTML protegido en servidor. |
| `GET /api/v1/almacenamiento` | Bytes ocupados/disponibles del volumen, material gestionado, liberable, protegido por motivo; última/próxima ejecución, retraso, deudas, revisión, vencimientos, cifrado y outbox. |
| `POST /api/v1/almacenamiento/vista-previa` | Sin borrar: entrega `preview_token`, `preview_bytes`, `preview_files`, `expires_in_seconds=300` y métricas. Máximo 1000 archivos por vista previa. |
| `POST /api/v1/almacenamiento/liberar` | JSON `{ "preview_token": "…" }`. Revalida identidad, tamaño/mtime, SQL, conservación y locks antes de cada borrado. Devuelve bytes liberados, archivos, fallos, protecciones y contexto retirado. |

La entrada `/configuracion-operativa/almacenamiento` redirige al panel protegido dentro del ámbito de la cookie HttpOnly `/api/v1/`.

El token está firmado y vinculado al administrador; no autoriza archivos nuevos ni
reemplazados. Sin token: `400 STORAGE_PREVIEW_REQUIRED`; vencido/manipulado/otro
actor: `409 STORAGE_PREVIEW_EXPIRED`; limpieza concurrente: `409 STORAGE_CLEANUP_BUSY`.
La pérdida de una respuesta no autoriza repetir envíos de audio. Consultar estado
y generar una vista previa nueva. La política es idéntica a la automática y no
puede editarse por API. El evento `storage.cleanup` comparte bitácora/exportación,
con subdocumento técnico `storage` y outbox SQL para reintentar si Mongo cae.

[Política, plazos, claves y pruebas](docs/CONSERVACION-Y-ALMACENAMIENTO.md).
