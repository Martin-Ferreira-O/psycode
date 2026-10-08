# Contratos de API — Psycode API

**Nombre técnico:** `psycode-api`. **API:** v1. **Revisión documental:** 1.2, escala de severidad actualizada el 2026-10-08. **Implementación actual:** las operaciones descritas se implementan por sus tareas SCRUM correspondientes.

**Base URL:** `/api/v1/`. **Autenticación:** JWT `Authorization: Bearer <access_token>`. **JSON:** `application/json`. [Arquitectura](ARCHITECTURE.md) · [Aceptación](docs/ACCEPTANCE.md).

## 0. Convenciones comunes

### Rutas y acceso

Endpoints sin barra final; el prefijo sí se escribe `/api/v1/`. No depender de redirecciones para POST. Se conservan nombres públicos en inglés/español del borrador.

| Método | Ruta completa | Nombre Django | Acceso |
|---|---|---|---|
| POST | `/api/v1/auth/login` | `accounts:login` | Público |
| POST | `/api/v1/auth/refresh` | `accounts:refresh` | Refresh válido, no exige access |
| POST | `/api/v1/auth/logout` | `accounts:logout` | Access válido + refresh propio |
| GET | `/api/v1/auth/me` | `accounts:me` | Protegido |
| POST | `/api/v1/auth/password-reset` | `accounts:password_reset` | Público |
| POST | `/api/v1/auth/password-reset/confirm` | `accounts:password_reset_confirm` | Token de recuperación |
| GET | `/api/v1/alerts` | `alerts:list` | Protegido |
| GET | `/api/v1/alerts/{alerta_id}` | `alerts:detail` | Protegido |
| GET, POST | `/api/v1/alerts/{alerta_id}/evaluacion` | `alerts:evaluation` | Protegido |
| GET | `/api/v1/dashboard/resumen` | `dashboard:summary` | Protegido |
| GET | `/api/v1/dashboard/estadisticas` | `dashboard:statistics` | Protegido |

Protegido significa profesional autenticado y activo. No hay roles adicionales definidos: todos los usuarios activos acceden a consulta y evaluación. No existe registro público de usuarios. GET lee y POST acciona o crea evaluación. PUT/PATCH/DELETE no están definidos para estos recursos.

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

Frontend elimina su par local y vuelve al login. El access previamente emitido conserva su vigencia restante; no se promete cierre inmediato de access ni de otros dispositivos. Si access venció, el frontend puede descartar los tokens sin esperar logout exitoso.

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

RegistrationResult contiene `alerta` (AlertDetail) y `notificacion` (NotificationResult). Duplicado → `AlertAlreadyExists`, sin nuevo envío; datos inválidos → `ValidationError`; persistencia caída → `PersistenceUnavailable`, sin envío. Tras guardar, fallo de notificación se expresa en resultado, no como fallo de persistencia.

Prototipo: las alertas válidas de nivel 1–3 pueden notificar. NULO/sin riesgo no se registra como alerta ni se envía. NOTIFICATIONS_ENABLED=false omite todos los envíos de desarrollo y datos sintéticos. Repositorios no envían mensajes.

### notify_alert(alerta_id, payload) → NotificationResult

UUID es contexto interno de auditoría. Payload acepta exclusivamente:

~~~json
{
  "tipo": "alerta_riesgo",
  "box": "box-3",
  "tipo_riesgo": "riesgo_suicida",
  "nivel_urgencia": "BAJO",
  "fecha_hora": "2026-09-12T14:05:22Z"
}
~~~

Tipo constante; urgencia igual al semáforo derivado y fecha UTC de detección. Adaptador traduce al formato de Teams Workflows o correo. No enviar descripción, sesión, pacientes, audio, transcripción ni detalles operativos. UUID de alerta se mantiene solo en auditoría interna.

Un intento Teams; ante timeout, rechazo, fallo de red o configuración ausente, auditar y probar correo. **Máximo 10 segundos de tiempo total por canal/intento**, incluyendo conexión y respuesta; timeout de socket por sí solo no garantiza este límite. Sin reintentos automáticos; ambos canales suman hasta 20 segundos de comunicación, excluyendo persistencia y logging.

2xx del workflow indica aceptación por proveedor, no publicación final ni lectura humana. SMTP aceptado tampoco garantiza entrega.

NotificationResult siempre tiene:

| Campo | Tipo / regla |
|---|---|
| `estado` | aceptada, fallida u omitida |
| `canal` | teams, email o null; canal que aceptó, null si ninguno |
| `contingencia` | booleano; true cuando se intentó correo por fallo Teams |
| `motivo` | null, sin_riesgo, deshabilitada o ningun_canal_acepto |
| `intentos` | Lista ordenada: canal, resultado (aceptado/fallido), error_code (string o null), duracion_ms (integer no negativo) |

Ejemplo interno:

~~~json
{
  "estado": "aceptada",
  "canal": "email",
  "contingencia": true,
  "motivo": null,
  "intentos": [
    { "canal": "teams", "resultado": "fallido", "error_code": "NOTIFICATION_TIMEOUT", "duracion_ms": 10000 },
    { "canal": "email", "resultado": "aceptado", "error_code": null, "duracion_ms": 250 }
  ]
}
~~~

- Teams acepta: un intento, canal teams, contingencia false.
- Ambos fallan: estado fallida, canal null, motivo ningun_canal_acepto, dos intentos, contingencia true.
- Omisión: canal null, contingencia false, intentos vacíos; motivo sin_riesgo para NULO (precedencia), o deshabilitada.
- Payload inválido: ValidationError interno antes de enviar.
- Cada intento registra UUID de alerta, canal, hora, resultado, duración y contingencia.

Errores internos de intento: `NOTIFICATION_TIMEOUT`, `NOTIFICATION_CONNECTION_FAILED`, `NOTIFICATION_REJECTED`, `NOTIFICATION_NOT_CONFIGURED`, `NOTIFICATION_INTERNAL_ERROR`. No exponer secretos ni cuerpo libre de error del proveedor. Fallo inesperado Teams también permite contingencia.

Ningún fallo de envío elimina la alerta. No se implementa cola duradera ni se garantiza entrega tras caída entre persistencia y envío.

## 5. Seguridad, compatibilidad y cambios

- HTTPS en producción y CORS restringido al origen del frontend.
- No guardar audio; no registrar contraseñas, tokens ni URLs secretas. Notificaciones con contenido mínimo.
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
