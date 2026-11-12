# Backend de Psycode

Mapa del backend tal como está en este repositorio, armado a partir de la auditoría del 2026-11-08. Describe el código que corre, no los README de módulo que quedaron atrás. Esos README todavía dicen que alertas no tiene HTTP, que las notificaciones están pendientes y que la captura no ingesta archivos. El código ya hace las tres cosas.

El veredicto, ya con MongoDB en marcha y las migraciones aplicadas: el backend funciona en esta máquina. La forma de levantarlo es la del repositorio y sirve en cualquier equipo con Docker y Python 3.12 o 3.13.

## Qué es

Un solo proyecto Django (`psycode-api`) que atiende a dos clientes distintos:

- El navegador de la clínica. Profesionales y administradores consultan alertas, evalúan, administran cuentas, PCs y almacenamiento.
- El programa `psycode-agent`, que vive en otro repositorio. Se instala en los PCs de los box, abre un WebSocket de control y sube audio y agenda.

La API pública es `/api/v1/`, sin barra final. `APPEND_SLASH` está apagado. Hay una ruta extra de audio en `/api/v2/internal/fragments` y el control del agente en `/ws/v1/agents`.

Django 5.2 y Python 3.12 o 3.13. El punto de entrada es `manage.py`, con `DJANGO_SETTINGS_MODULE=backend.config.settings`. Detrás de Nginx, el VPS usa `backend.config.vps_settings`, que hereda esa configuración y confía en `X-Forwarded-Proto` solo porque Uvicorn escucha en `127.0.0.1`.

## Dos almacenes, un proceso de aplicación

No hay relación SQL entre las bases. Un identificador se copia como texto cuando hace falta recordarlo.

| Dato | Dónde vive | Quién lo escribe |
|---|---|---|
| Usuarios, contraseñas, rol, refresh, límites de login y de recuperación | SQLite | `accounts` |
| Horario clínico y destinatarios de correo | SQLite, una sola fila `operational_configuration` | `operational` |
| PCs, sesiones de captura, órdenes, fragmentos, leases, limpieza | SQLite | `capture` |
| Revisiones de agenda por box | SQLite | `agenda` |
| Alertas y bitácora de alertas, análisis y notificación | MongoDB, base `psycode`, colecciones `alerts` y `audit_events` | `alerts` |
| WAV y blobs temporales | Disco, `CAPTURE_FRAGMENT_ROOT` | `capture` |
| Estado de trabajos de Speechmatics/JEV | Disco, `ANALYSIS_STATE_ROOT` | `analysis` |
| Correos de recuperación en desarrollo | Archivos en `EMAIL_FILE_PATH` | worker de `accounts` |

SQLite usa `timeout` de 10 segundos y transacciones `IMMEDIATE`. El archivo local está en modo journal `delete`. En el VPS, Uvicorn arranca con 2 workers y además corren el coordinador y el trabajador de fragmentos sobre el mismo archivo. Esa combinación puede devolver 503 si varias escrituras coinciden. El código convierte `OperationalError` de Django en `PERSISTENCE_UNAVAILABLE`.

MongoDB no se abre al importar Django ni al arrancar `runserver`. `backend/apps/alerts/mongo.py` crea el cliente en el primer uso. Si `MONGODB_URI` está vacío o el servidor no responde en 5 segundos, la operación sale como 503. El mismo repositorio aplica validador e índices de `docs/mongodb/` la primera vez que toca una colección.

La escala vigente de una alerta es `nivel_severidad` 1, 2 o 3. El semáforo sale solo de ahí: 1 `BAJO`, 2 `MEDIO`, 3 `ALTO`. Un resultado nulo o sin riesgo no se guarda. Evaluar no cambia la severidad detectada.

## Cómo entra una petición

```text
Nginx (producción) o el puerto de desarrollo
        │
        ▼
backend.config.asgi.application
        │
        ├─ WebSocket  /ws/v1/agents ──► capture.websocket.agent_websocket
        │
        └─ HTTP ──► Django + DRF
                    MIDDLEWARE: Security, BrowserSecurity (CSP, no-store),
                    CORS solo sobre /api/v1/, Common, CSRF, X-Frame DENY
                    │
                    ▼
              backend.config.urls
```

`backend/config/urls.py` reparte así:

| Prefijo | Módulo | Quién puede entrar |
|---|---|---|
| `/api/v1/auth/` | `accounts` | Público en login, refresh y recuperación. El resto exige JWT |
| `/api/v1/alerts` y `/api/v1/audit-events` | `alerts` | Profesional activo. La bitácora solo administrador |
| `/api/v1/dashboard/` | `dashboard` | Lista vacía. Esas rutas caen en el 404 final |
| `/api/v1/configuracion-operativa` y `/api/v1/pcs` | `operational` | Administrador activo |
| `/api/v1/almacenamiento` | `capture.storage_views`, montadas desde `operational` y `web` | Administrador activo |
| `/api/v1/internal/` | `capture` y `agenda` | Agente del box, cabecera `Agent` |
| `/api/v2/internal/fragments` | `capture` | El mismo agente, con metadatos temporales del audio v2 |
| HTML (`/`, `/dashboard`, `/usuarios`, …) | `web` | El HTML se entrega sin sesión. Los datos salen de la API |

Cualquier otra ruta responde `RESOURCE_NOT_FOUND`. Los errores de la API salen por `backend/common/errors.py` con `success`, `error.code`, `error.message` y `timestamp`. `backend/common/audit.py` escribe el logger `psycode.audit`. Ese logger no es la bitácora de Mongo. La bitácora de negocio la escribe `alerts`.

`backend/config/composition.py` es el único lugar que arma los servicios entre módulos. Las vistas de cuentas reciben la fábrica desde las URLs. El trabajador de fragmentos y el coordinador llaman a las fábricas de composición. La vista HTTP de alertas construye `AlertsService` directo, sin notificador, porque solo lee y evalúa.

## Procesos que tienen que estar vivos

Un `runserver` alcanza para el HTML y la API HTTP. No atiende el WebSocket del agente ni procesa audio.

| Proceso | Comando | Qué mueve |
|---|---|---|
| Web y WebSocket | `uvicorn backend.config.asgi:application` | HTTP, cookies, ingesta, handshake del agente |
| Coordinador | `manage.py coordinate_capture` | Mira agenda y horario, abre y cierra sesiones, deja órdenes en SQL |
| Trabajador de fragmentos | `manage.py process_fragment_jobs` | Toma `FragmentJob`, llama a análisis y, si corresponde, registra la alerta |
| Limpieza | `cleanup_capture_uploads`, `cleanup_sensitive_storage` | Huérfanos de disco y retención |
| Salud | `capture_health`, `verify_sensitive_storage` | Conteos y comprobación de volúmenes cifrados |

En desarrollo, con `DJANGO_DEBUG=true`, el cifrado del disco no es obligatorio. Fuera de debug, `SENSITIVE_STORAGE_ENCRYPTION_REQUIRED` exige que audio, SQLite y análisis estén en volúmenes cifrados. `capture/encryption.py` lo comprueba con `findmnt` y `lsblk` en Linux.

El agente instalable no está en este repositorio. `scripts/check_boundaries.py` rechaza imports de `psycode_agent` y de `obsws_python` dentro de `backend/`.

## Módulos y con quién hablan

```text
web ────────────► API HTTP (no importa servicios de negocio)
accounts ───────► SQLite
                  └─ subprocess email_worker ─► SMTP o archivo

operational ────► SQLite (horario y correos)
       │          └─ usuarios de accounts, solo para saber si el actor es admin
       ▼
capture_authorization
       │ lee agenda en memoria/SQLite y el horario
       ▼
capture ────────► SQLite + disco
       │ WebSocket y HTTP de agente
       ▼
analysis ───────► Speechmatics y JEV, solo si el entorno lo enciende
       │
       ▼
alerts_service (composition)
       ├─► MongoDB alerts + audit_events
       └─► notifications
                 ├─ lee operational_configuration
                 ├─ lee correos de supervisores activos en accounts
                 └─ escribe el resultado otra vez en audit_events
```

### `config`

`settings.py` exige `DJANGO_DEBUG` explícito. Sin `DJANGO_SECRET_KEY` y con debug, genera una clave en `.local/django-secret-key`. Fuera de debug la clave es obligatoria y el origen del frontend tiene que ser HTTPS. CORS queda limitado a ese origen y a `/api/v1/`.

`CAPTURE_AGENTS` es el registro viejo de agentes: un JSON de `id -> {box, token_sha256}`. Puede ir vacío. Los PCs creados desde la pantalla se leen de `AgentRegistration` y tienen prioridad. `CAPTURE_AGENDA_SOURCES` dice qué agente recolecta qué boxes. Los boxes válidos son `box-3` … `box-7`.

### `common`

No importa módulos de negocio. Traduce excepciones, arma el JSON de respuesta y emite auditoría técnica. `PersistenceUnavailable` es el 503 compartido por SQLite y MongoDB. `BrowserSecurityMiddleware` pone CSP, `nosniff` indirecto vía cabeceras de seguridad de Django, y `Cache-Control: no-store` en HTML y en `/api/`.

### `accounts` — identidad de personas

Modelo `User` con UUID, correo único en minúsculas, rol `admin` o `supervisor`, y la contraseña de Django. `is_admin` es rol admin o superusuario. El nombre de usuario no puede llevar `@`.

Tablas propias: `RefreshSession` (solo el `jti`, nunca el JWT completo), `PasswordReset` (digest SHA-256, uno vigente por usuario), `PasswordResetRateLimit` y `AuthRateLimit`. Las claves de límite son HMAC. No se guarda la IP en claro.

Flujo de login:

1. `LoginView` consume cupo por IP antes de mirar el JSON.
2. `AccountsService.login` busca el usuario y consume cupo por cuenta. Un acierto también gasta cupo.
3. Si el usuario no existe, igual calcula un hash para no adelantar la respuesta.
4. Dentro de una transacción vuelve a leer la contraseña. Si cambió mientras se verificaba, no emite tokens.
5. Un usuario inactivo recibe 403.
6. Emite access (1 hora) y refresh (24 horas). El refresh rota: el `jti` anterior se revoca.

En el navegador la petición lleva `X-Psycode-Browser: 1`. La respuesta solo dice `authenticated: true`. Las cookies `HttpOnly` guardan los JWT: access en `/api/v1/`, refresh en `/api/v1/auth/`. Cada request con cookie pasa por CSRF. Un access de cookie también se contrasta con `RefreshSession`, así que el logout lo invalida al momento. Un cliente que manda `Authorization: Bearer` sigue recibiendo los tokens en JSON. Ese access Bearer puede vivir hasta una hora después del logout. Cambiar la contraseña revoca las dos modalidades.

La recuperación responde siempre 202 si el correo no se puede distinguir. Solo el primer intento de la ventana envía correo. El envío corre en un subprocess (`email_worker`) con tope `EMAIL_TIMEOUT_SECONDS`, para no sostener el bloqueo de escritura de SQLite durante SMTP. Si el envío falla, se borra solo el token que no salió. Hay un `print` de depuración en `EmailClient` cuando ese subprocess falla.

Administrar usuarios (`/api/v1/auth/admin/users`) exige administrador. No hay registro público.

### `web` — cáscara HTML

`backend/apps/web` renderiza login, dashboard, evaluaciones, usuarios, bitácora, configuración y el panel de almacenamiento. El JavaScript de `static/web/js/` llama a la API. El dashboard de pantalla usa `GET /api/v1/alerts`, no los agregados de `/api/v1/dashboard/`. Esas dos rutas de contrato siguen sin vista.

### `alerts` — lectura, evaluación y bitácora

Dominio en `domain.py`, sin Django ni PyMongo. Puertos en `ports.py`. `AlertsRepository` los implementa.

HTTP autenticado:

- `GET /api/v1/alerts`
- `GET /api/v1/alerts/{alerta_id}`
- `GET` y `POST /api/v1/alerts/{alerta_id}/evaluacion`
- `GET /api/v1/audit-events` y `GET /api/v1/audit-events/export`

No hay `POST /api/v1/alerts`. El alta entra por `AlertsService.register_alert`, llamado desde el trabajador de análisis.

`alerta_id` es un UUID en minúsculas. El `_id` de Mongo no sale de la API. `box` es texto. `sesion_id` es un UUID clínico, distinto de la sesión JWT. La evaluación se incrusta en el mismo documento y solo pasa de `pendiente` a `correcta`, `falso_positivo` o `neutro` con un `updateOne` condicionado. La segunda escritura concurrente es conflicto. El autor (`usuario_id`, `usuario`) se copia desde SQLite en ese momento. Después no hay join.

La búsqueda `q` es una expresión regular acotada sobre id, box y tipo de riesgo. No hay un buscador aparte.

`audit_events` es append-only. Un fallo al escribir la bitácora no borra la alerta. El mismo `event_id` queda en el logger para poder correlacionar. La consulta y el Excel de bitácora son solo de administrador activo. El texto de `ARCHITECTURE.md` que incluye al supervisor está viejo. La tabla de `API_CONTRACTS.md` y el permiso `AuditPermission` dejan la bitácora en admin.

`seed_demo_alerts` solo corre con debug y con MongoDB alcanzable.

### `dashboard`

`urls.py` está vacío a propósito. `services.py` no tiene casos de uso. El contrato sigue describiendo `resumen` y `estadisticas`. La pantalla no los necesita porque pagina las alertas.

### `notifications`

No tiene rutas. Implementa `AlertNotifier`. `composition.alerts_service()` le inyecta el mismo repositorio de alertas.

Antes de enviar, vuelve a leer la alerta en Mongo y arma el mensaje solo con semáforo, tipo fijo `riesgo_suicida`, box y fecha. No manda descripción, sesión, audio ni transcripción. `TEAMS_ENABLED` está fijo en `False`. El adaptador de Teams existe y no participa.

`NOTIFICATIONS_ENABLED` sale en false. Con eso `notify_alert` registra omisión y no abre SMTP. Si se enciende, `RecipientResolver` lee la fila operativa:

- modo `lista_distribucion`: el `primary_email`
- modo `supervisores_activos`: correos de usuarios activos con rol supervisor

Cada intento va a un solo destinatario. Un fallo de correo no revierte la alerta. El resumen queda en `audit_events` como `notifications.send` y `notifications.result`.

### `operational` — horario, correos y autorización de captura

Una sola configuración, `id = 1`: días habilitados, apertura, cierre, zona `America/Santiago`, modo de notificación y correos. `GET` y `PUT /api/v1/configuracion-operativa` son de administrador.

`CaptureAuthorizationService.evaluate_box` junta dos fuentes:

1. La agenda del box, si hay una cita que cubre el instante.
2. Si no, el horario clínico, si ese día y esa hora están abiertos.

El resultado es `BoxCaptureAuthorization`: autorizado o no, inicio, término y origen `agenda` u `horario_clinico`. No habla con el agente. Se lo entrega a captura.

También cuelga aquí el CRUD de PCs (`/api/v1/pcs`): alta, revocación, renovación e historial de conectividad. El secreto del agente se devuelve una sola vez, al crear o renovar. En SQLite queda el SHA-256.

### `agenda`

El colector designado pide una recolección en `POST /api/v1/internal/agenda-collections` y devuelve el Excel en `POST /api/v1/internal/agenda-reports`. Las dos rutas exigen identidad de agente. El reporte original se guarda en `AgendaCollection.report`. La ocupación usable queda en `AgendaBoxRevision`, una fila por box.

`composition.durable_agenda()` recarga eso en un `AgendaService` en memoria. El coordinador de captura lee esa copia. Una carga nueva reemplaza la revisión del box. La autorización de captura no abre el Excel por su cuenta.

### `capture` — sesiones, audio y disco

Identidad del agente, HTTP y WebSocket, en `authentication.py`. La cabecera es `Agent <id>.<secreto>`. Primero busca un `AgentRegistration` cuyo id sea UUID. Si no está, cae a `CAPTURE_AGENTS`. El hash se compara con `hmac.compare_digest`. Un fallo gasta límite por IP y por identidad. El WebSocket rechaza query string, exige una sola cabecera y cierra `4401` o `4429`. La ruta tiene que ser `/ws/v1/agents`.

El coordinador, por cada box, llama a `evaluate_box` y `CaptureSessionService.apply_authorization`. Si la ventana es válida, crea o mantiene una `CaptureSession` y encola `AgentCommand`. El WebSocket solo entrega las órdenes del box autenticado y confirma los ACK en la misma transacción que el lease `RuntimeLease`. Dos conexiones del mismo box no confirman a la vez: la nueva reemplaza el lease.

La ingesta:

1. `POST /api/v1/internal/fragments` o la v2 con muestras y solapamiento.
2. El box del multipart tiene que ser el box del agente.
3. El WAV se valida sin decodificar audio: PCM, mono, 16 kHz, 16 bits, y un tope de tamaño.
4. El archivo se publica en disco y después la transacción SQL inserta `AcceptedSequence` y `FragmentJob`. La respuesta HTTP sale después del commit.
5. Si el proceso muere entre el disco y el commit, queda un archivo huérfano. `cleanup_capture_uploads` lo recoge cuando envejece y nadie lo tiene bloqueado. No borra un trabajo activo.

`FragmentJobProcessor` reclama el trabajo, construye el `Fragment` y llama a `AnalysisService`. Reintenta con tope. Un checkpoint en la fila permite retomar. `storage_views` deja al administrador ver el inventario, pedir una vista previa y liberar con un token de esa vista previa. La liberación queda en `StorageCleanupRun` y `StorageDeletion`.

### `analysis`

No tiene URLs. `AnalysisService.process` es secuencial por trabajador. Transcribe con Speechmatics, redacta el texto y consulta JEV. `PSYCODE_EXTERNAL_PROCESSING_ENABLED` tiene que ser exactamente `1`. Si no, el proveedor se niega a salir a la red. Las claves no se imprimen: van marcadas `repr=False`.

La matriz de lenguaje está en `matrix.json`. Una señal de riesgo 1–3 llama a `alerts.register_alert`. Nulo o sin riesgo se queda fuera. Si MongoDB falla, no hay notificación. Si la alerta se guardó y el correo falla, la alerta permanece y la bitácora anota `alerts.flow` o `notifications.send`.

## Recorridos completos

### Un profesional entra y evalúa

`login.js` pide `POST /api/v1/auth/login` con la marca de navegador. `accounts` escribe el refresh en SQLite y deja las cookies. El dashboard pide `GET /api/v1/alerts`. `AccountJWTAuthentication` valida el access de la cookie, el CSRF y que la `RefreshSession` siga viva. `AlertsRepository` lee MongoDB. `POST .../evaluacion` toma el usuario del token, no del JSON, y hace el `updateOne` condicionado. La bitácora de esa evaluación va a `audit_events` con el UUID del profesional.

### Un box captura y aparece una alerta

1. Un administrador registra el PC. SQLite guarda el hash. El agente recibe el secreto una vez.
2. El agente abre `/ws/v1/agents`. Captura comprueba el hash contra `accounts` solo en el sentido de los límites de `AuthRateLimit`. La credencial está en `AgentRegistration`.
3. El mismo agente, si es el colector de `CAPTURE_AGENDA_SOURCES`, sube la agenda. `operational` todavía no entra.
4. `coordinate_capture` pregunta a `CaptureAuthorizationService`. Ese servicio lee la revisión de agenda y, si no hay cita, la fila de horario.
5. Captura abre la sesión y el WebSocket entrega la orden de inicio.
6. El agente sube fragmentos. Disco y `FragmentJob` quedan ligados a la sesión y al box.
7. `process_fragment_jobs` llama a análisis. Análisis, si el entorno externo está encendido, habla con Speechmatics y JEV.
8. Una señal 1–3 entra a `AlertsService.register_alert`, que escribe MongoDB.
9. `NotificationService` relee esa alerta. Con notificaciones apagadas se detiene ahí y deja constancia. Con notificaciones encendidas usa los correos de `operational` o los supervisores de `accounts`.

SQLite, el archivo WAV, MongoDB y el SMTP no comparten una transacción. Una caída entre el alta y el correo deja la alerta sin aviso. El propio diseño lo acepta.

### Un administrador cambia a quién se avisa

`PUT /api/v1/configuracion-operativa` actualiza la fila única. El próximo `notify_alert` lee esa fila. No hay caché de destinatarios en el proceso de alertas. El horario de la misma fila también cambia lo que el coordinador autorizará en la pasada siguiente, cuando no haya una cita de agenda encima.

## Qué garantizan las pruebas y qué quedó fuera

`manage.py check` no reportó problemas. `makemigrations --check` no encontró modelos sin migración. `scripts/check_boundaries.py` validó que el backend no importa al agente y que los contratos de `contracts/` conservan su SHA-256.

La suite Django, con `backend.config.test_settings` y `PSYCODE_TEST_MONGODB_URI` apuntando al MongoDB local, ejecutó 462 pruebas y pasó. Quedó omitida solo la muestra opcional de Excel de agenda. Las pruebas de integración contra MongoDB real corrieron en la base `psycode_test`.

La suite cruzada de `tests/cross/` no se corrió. Pide el wheel de `psycode-agent`.

## Estado de esta máquina

La primera revisión encontró el entorno atrasado. Después se alineó con el método del repositorio, el mismo en Linux, macOS y Windows: contenedor Docker `mongo:7` publicado en `127.0.0.1:27017`, y `manage.py migrate`.

- MongoDB 7.0.43 quedó en marcha (`docker start psycode-mongo`).
- Quedaron aplicadas todas las migraciones de accounts, agenda, capture y operational. La SQLite pasó de 11 tablas a 27. El usuario local `autonoma` quedó con rol `supervisor`.
- Las cinco alertas de demostración que ya estaban en Mongo usaban la escala vieja 0–7. El dominio actual solo lee 1–3, así que `seed_demo_alerts` fallaba al rehidratarlas. `seed_demo_alerts --reset` las reemplazó por la escala vigente. En otra máquina con alertas reales de esa escala hay que correr antes la conversión de `docs/MONGODB.md`, no borrar la colección.
- Con el servidor de desarrollo en `127.0.0.1:8000` se probó login, listado, detalle, alta de evaluación, conflicto 409, 401 sin token, 403 de supervisor en bitácora, PCs, almacenamiento y configuración, y 404 de `/api/v1/dashboard/resumen` y `estadisticas`. El login de navegador dejó cookies y no devolvió el JWT en el JSON.
- La suite completa contra ese MongoDB terminó `OK`: 462 pruebas, 1 omitida (la muestra opcional de Excel). Las pruebas de integración con MongoDB real, que antes se saltaban, esta vez corrieron.
- El `runserver` de esa prueba se detuvo al terminar. MongoDB sigue levantado.

## Dónde mirar si hay que cambiar algo

| Si el cambio es… | Empieza en |
|---|---|
| Una ruta o un permiso | `backend/config/urls.py` y la `urls.py` del módulo |
| Armar un servicio con sus dependencias | `backend/config/composition.py` |
| Reglas de una alerta, sin base de datos | `backend/apps/alerts/domain.py` |
| Forma de los documentos Mongo | `backend/apps/alerts/documents.py` y `docs/mongodb/` |
| Quién recibe un correo | `operational/models.py` y `notifications/recipients.py` |
| Cuándo un box puede grabar | `operational/capture_authorization.py` |
| El audio ya aceptado | `capture/ingestion.py`, `capture/processing.py` |
| Speechmatics, JEV y la matriz | `backend/apps/analysis/` |
| Cookies, CSRF y límites de login | `accounts/authentication.py`, `accounts/services.py`, `accounts/rate_limits.py` |
