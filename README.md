# Psycode API

> Separación implementada: el agente instalable está en el repositorio independiente
> `psycode-agent`. El control remoto y la operación vigente se describen en
> [OPERACION-SEPARADA.md](docs/OPERACION-SEPARADA.md) y
> [CONTROL-Y-AUDIO.md](docs/CONTROL-Y-AUDIO.md). Las secciones históricas que
> presentaban el transporte como pendiente quedan sustituidas por esos contratos.


Servidor central del proyecto Psycode, desarrollado en Python y Django. Incluye la interfaz web, autenticación, recuperación de contraseña, alertas en MongoDB, consulta y evaluación HTTP, bitácora protegida y notificación por correo a destinatarios de la configuración operativa (envíos desactivados por defecto). El programa instalable en los PCs de psicología se mantiene por separado en `psycode-agent`.

Para el VPS, seguir [instalación y operación separada](docs/OPERACION-SEPARADA.md): se necesitan ASGI para HTTP/WebSocket, el coordinador de captura y el trabajador de fragmentos. Las instrucciones de `runserver` de este README son para desarrollo local.

Para probar este servidor con el otro repositorio, comienza por
[Cómo probar el servidor junto con psycode-agent](docs/PRUEBAS-SERVIDOR-AGENTE.md).
Incluye preparación de ambos entornos, construcción del paquete del agente,
comandos para macOS/Linux y PowerShell, resultados esperados y una prueba manual
opcional con OBS. La integración automática no necesita OBS ni credenciales reales.

La [revisión funcional posterior a la separación](docs/REVISION-FUNCIONAMIENTO-SERVIDOR.md) registra las correcciones, pruebas ejecutadas y validaciones pendientes en el entorno institucional.

La integración interna de Speechmatics Batch y JEV está documentada en [implementación y pruebas sin credenciales](docs/INTEGRACION-SPEECHMATICS-JEV.md). Incluye el contrato de salida 1.0, procedencia del código y conexión a alertas/bitácora; no añade una interfaz ni habilita envíos externos por defecto.

## Primera instalación

Abre una terminal en la carpeta del proyecto, donde está `manage.py`. Necesitas Python 3.12 o 3.13. Elige una de las dos opciones siguientes; ambas instalan las mismas dependencias.

### Opción 1: uv

Si ya tienes [uv instalado](https://docs.astral.sh/uv/getting-started/installation/), ejecuta:

```sh
uv sync --locked
```

Crea el archivo de configuración **solo si todavía no tienes `.env`**:

- macOS/Linux: `cp .env.example .env`
- Windows PowerShell: `Copy-Item .env.example .env`

Luego crea las tablas, el usuario de prueba y arranca el servidor:

```sh
uv run python manage.py migrate
uv run python manage.py seed_demo_user
uv run python manage.py runserver
```

uv crea el entorno `.venv` y usa la versión de Python indicada en `.python-version`.

### Opción 2: venv + pip

En macOS/Linux:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
```

En Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
```

Si tienes Python 3.13, sustituye `python3.12` por `python3.13` o `py -3.12` por `py -3.13`.

Crea `.env` **solo si no existe**:

- macOS/Linux: `cp .env.example .env`
- Windows PowerShell: `Copy-Item .env.example .env`

En macOS/Linux, con el entorno activado:

```sh
python manage.py migrate
python manage.py seed_demo_user
python manage.py runserver
```

En Windows PowerShell:

```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_demo_user
.venv\Scripts\python.exe manage.py runserver
```

Deja esa terminal abierta. El servidor escucha en http://127.0.0.1:8000 y la dirección raíz muestra el inicio de sesión web. Para detenerlo, presiona `Ctrl+C`. `runserver` no atiende el control WebSocket de los agentes; para probarlo, usar Uvicorn según el runbook del VPS.

## Volver a arrancar el proyecto

Desde la carpeta que contiene `manage.py`, usa el comando de tu instalación:

| Instalación | Comando |
|---|---|
| uv | `uv run python manage.py runserver` |
| pip, macOS/Linux | Ejecuta `source .venv/bin/activate` y luego `python manage.py runserver` |
| pip, Windows PowerShell | `.venv\Scripts\python.exe manage.py runserver` |

Después de actualizar el código, vuelve a instalar las dependencias con el comando de tu opción y ejecuta `manage.py migrate` antes de arrancar. No vuelvas a copiar `.env`.

Windows nativo está soportado, incluida la ingesta y limpieza de fragmentos.
Los bloqueos de archivos usan `LockFileEx` en Windows y `flock` en macOS/Linux;
no hay que instalar `fcntl`. Si una versión anterior falla con
`ModuleNotFoundError: No module named 'fcntl'`, actualiza desde PowerShell:

```powershell
git pull
uv sync --locked
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py runserver
```

## Speechmatics Batch y JEV: configuración y pruebas

Las variables de análisis están incluidas en [`.env.example`](.env.example). Si ya tienes `.env`, incorpora únicamente las variables nuevas que necesites, conservando su contenido; no lo reemplaces ni subas claves a Git. El análisis externo viene deshabilitado y las claves del ejemplo están vacías.

| Variable | Valor de ejemplo / función |
|---|---|
| `PSYCODE_EXTERNAL_PROCESSING_ENABLED` | `0`. Solo `1` habilita envíos externos autorizados. |
| `SPEECHMATICS_API_KEY` | Vacía. Clave de Speechmatics, requerida para uso real. |
| `SPEECHMATICS_REGION` | `eu1`. Admite `eu1`, `us1`, `au1`; confirmar la región autorizada antes de usar datos reales. |
| `SPEECHMATICS_MODEL` | `enhanced`. También admite `standard`. |
| `SPEECHMATICS_POLL_INTERVAL` | `2` segundos entre consultas; rango 0,1–30. |
| `PSYCODE_PROVIDER_TIMEOUT` | `300` segundos por etapa; rango 1–540. El borrado tiene hasta 30 segundos adicionales. |
| `JEV_PROVIDER` | `auto`, `typesafe` u `openrouter`. En `auto`, prefiere Typesafe si existen ambas claves; no cambia de cuenta ante fallos. |
| `TYPESAFE_API_KEY` | Vacía. Necesaria al elegir Typesafe. |
| `JEV_MODEL` | `jev-1.13.0`. Versión explícita para Typesafe. |
| `OPENROUTER_API_KEY` | Vacía. Necesaria al elegir OpenRouter. |
| `OPENROUTER_JEV_MODEL` | `typesafe/jev-1.13`. Versión para la Decisions API de OpenRouter. |
| `PSYCODE_REDACT_TERMS` | `[]`. Lista JSON de nombres/direcciones conocidos para redactar antes de JEV; no garantiza anonimización completa. |

Para JEV basta la clave del proveedor seleccionado. **Las pruebas no requieren claves, MongoDB ni habilitar procesamiento externo**:

```sh
uv run python manage.py test backend.apps.analysis --settings=backend.config.test_settings --noinput
```

Con pip y el entorno activado, usa `python` en lugar de `uv run python`; en Windows también puedes usar `.venv\Scripts\python.exe`. La configuración de pruebas omite la carga de `.env` y los casos de integración bloquean las conexiones de red.

El consumidor central se ejecuta con `manage.py process_fragment_jobs --continuous --idle-seconds 1` en un proceso separado; recibe los trabajos creados por la ingesta HTTP del agente. `runserver` no lo inicia. También se conserva `backend.config.composition.analysis_worker()` y `worker.process(fragment, roles=...)` para integración interna. El rol del paciente debe confirmarlo un llamador confiable; la diarización por sí sola no lo identifica. El trabajador ordinario conserva los roles desconocidos y, sin esa atribución, no genera alertas clínicas.

Consulta [componentes adaptados, recuperación y pendientes de Jira](docs/INTEGRACION-SPEECHMATICS-JEV.md) y el [contrato de salida 1.0](docs/analysis/OUTPUT-1.0.md).

## Bitácora y notificaciones (SCRUM-65)

Consulta `GET /api/v1/audit-events` con JWT de administrador o supervisor activo. Admite período UTC (`fecha_desde`, `fecha_hasta`), `alerta_id`, `action`, `outcome`, `limit`, `offset` y `order`. [Contrato y ejemplos](API_CONTRACTS.md#consulta-de-bitácora-scrum-65).

Para habilitar correo, configura `NOTIFICATIONS_ENABLED=true` y guarda la modalidad en la configuración operativa: `lista_distribucion` usa exclusivamente `primary_email`; `supervisores_activos` envía un mensaje individual a cada supervisor habilitado con correo válido. Los destinatarios se consultan en cada notificación. Los fallos individuales no detienen los demás intentos y el resultado distingue éxito total, fallo parcial y fallo total. Sin destinatarios principales válidos se registra esa condición; en modalidad de supervisores puede intentarse el respaldo habilitado. Las variables antiguas de destinatarios no sustituyen la configuración y el respaldo solo se intenta si está habilitado y hay un fallo principal o no hay supervisores destinatarios válidos. `EMAIL_BACKEND=file` permite probar sin SMTP; para SMTP configura únicamente las credenciales del remitente/relay. Teams permanece deshabilitado.

Pruebas sin servicios externos:

```sh
uv run python manage.py test --settings=backend.config.test_settings --noinput
```

Para incluir persistencia y filtros contra un MongoDB de pruebas aislado (usa la base `psycode_test`):

```sh
PSYCODE_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 uv run python manage.py test --settings=backend.config.test_settings --noinput
```

La bitácora no almacena correos, contenido de mensajes, transcripciones ni secretos. El logger conserva el event_id original si MongoDB falla; no hay recuperación automática de eventos ni entrega garantizada tras una caída del proceso. [Detalles de notificaciones](backend/apps/notifications/README.md).

### Trazabilidad de notificaciones

Cada ejecución registra su modalidad y relaciona los intentos y el resumen por
`notification.id`, junto con la alerta y la sesión. El resumen distingue éxitos
y fallos principales y de respaldo, y conserva la ausencia de destinatarios
válidos. La bitácora muestra el motivo de uso del respaldo, incluido un fallo
parcial, sin correos ni contenido clínico. Los eventos anteriores siguen
consultables. [Campos y validación](docs/MONGODB.md#6-colección-audit_events-bitácora).

## Usuario de prueba

Cada integrante crea esta cuenta en su propia base local con `seed_demo_user`:

| Campo | Valor |
|---|---|
| Usuario | `autonoma` |
| Contraseña | `autonoma` |
| Correo | `autonoma@example.test` |

La cuenta no tiene permisos de administrador. El comando requiere `DJANGO_DEBUG=true`, como viene en `.env.example`; estas credenciales son solo para desarrollo local.

Si ya tenías el proyecto instalado, ejecuta:

```sh
uv run python manage.py seed_demo_user
```

Las cuentas anteriores se conservan. Si repites el comando, no cambia los datos ni la contraseña del usuario existente. Para volver a la contraseña de la tabla después de haberla cambiado:

```sh
uv run python manage.py seed_demo_user --reset-password
```

Con pip, sustituye `uv run python` por `python` en el entorno activado, o por `.venv\Scripts\python.exe` en Windows.

## Alertas de prueba (MongoDB)

La persistencia de alertas usa MongoDB. En local, con Docker:

```sh
docker run --name psycode-mongo -p 27017:27017 -d mongo:7
uv run python manage.py seed_demo_alerts
```

`.env.example` ya trae `MONGODB_URI=mongodb://127.0.0.1:27017` y `MONGODB_DATABASE=psycode`. El comando exige `DJANGO_DEBUG=true`, crea cinco alertas sintéticas (boxes, tipos, severidades y estados distintos) y las vuelve a leer para comprobarlas. No guarda audio ni datos de pacientes. Si las alertas ya existen, no las modifica. Para recrearlas: `seed_demo_alerts --reset`.

`runserver` no se conecta a MongoDB al arrancar. `GET /api/v1/alerts` está implementado, requiere autenticación y necesita MongoDB disponible. Detalle del seed: [comandos de alerts](backend/apps/alerts/management/commands/README.md).

## Probar el inicio de sesión

Con el servidor abierto, envía desde Postman u otro cliente HTTP:

- Método: `POST`
- URL: `http://127.0.0.1:8000/api/v1/auth/login`
- Body: selecciona **raw → JSON** y pega:

```json
{"usuario":"autonoma","password":"autonoma"}
```

La respuesta debe tener estado `200`, `success: true` y los campos `data.access_token` y `data.refresh_token`.

Para comprobar la sesión, envía `GET http://127.0.0.1:8000/api/v1/auth/me`. En Authorization, selecciona **Bearer Token** y pega el valor de `data.access_token`, sin comillas. Debes recibir los datos del usuario. Las rutas no llevan `/` al final.

## Probar la recuperación de contraseña

1. Envía `POST http://127.0.0.1:8000/api/v1/auth/password-reset` con un body JSON que contenga `correo` y el correo de la tabla anterior. Debe responder `202`.
2. Abre el archivo de correo más reciente de `.local/emails/`. El correo se guarda en tu equipo; no llega a una bandeja de entrada.
3. Copia el valor que aparece después de `token=` en el enlace del mensaje.
4. Envía `POST http://127.0.0.1:8000/api/v1/auth/password-reset/confirm` con ese valor en `token` y una contraseña nueva en `nueva_password`:

```json
{"token":"PEGA_AQUI_EL_TOKEN","nueva_password":"Prueba-Equipo-2026!"}
```

El token vence en una hora y solo se puede usar una vez. Al cambiar la contraseña, vuelve a iniciar sesión: los tokens de sesión anteriores dejan de servir. La contraseña nueva debe cumplir los validadores de la aplicación; el comando de usuario local permite restaurar la contraseña sencilla de prueba.

La pantalla de acceso incluye la solicitud de recuperación y `/password-reset/confirm` permite confirmar el cambio desde el enlace recibido. En desarrollo con la interfaz Django, configurar `FRONTEND_BASE_URL=http://127.0.0.1:8000` para que ese enlace apunte al servidor local. Para configurar archivos locales o SMTP, consulta [SCRUM-31](docs/SCRUM-31.md#correo-y-configuración) y [la cuenta técnica de pruebas](docs/SMTP_TEST_ACCOUNT.md).

## Agenda compartida y carga desde Excel

El servicio [agenda](backend/apps/agenda/README.md) conserva el lector manual de
`citas.xlsx`. La operación separada recibe reportes Smile JSON o Excel del colector
designado, persiste revisiones SQL y reconstruye la ocupación en cada proceso.
Ver [alcance, reintentos y agenda vacía](docs/OPERACION-SEPARADA.md#smile-y-agenda-entre-procesos).

```sh
uv run python manage.py test backend.apps.agenda --settings=backend.config.test_settings
```

## Sesiones de captura (SCRUM-71)

La autorización de SCRUM-70 se integra con sesiones persistentes, órdenes de
inicio/detención y confirmaciones mediante una interfaz interna del agente.
Incluye secuencias sin duplicados por concurrencia, bitácora técnica SQL y
recuperación de sesiones interrumpidas. La ingesta interna guarda fragmentos
de audio en almacenamiento temporal privado y trabajos pendientes en SQL.
[Contrato, integración y límites](backend/apps/capture/README.md).

Después de actualizar, ejecuta `manage.py migrate`. `manage.py coordinate_capture`
evalúa autorizaciones y recupera vencimientos periódicamente; debe ejecutarse como
proceso separado. La recuperación también puede ejecutarse con
`manage.py recover_capture_sessions`, que no crea nuevos inicios. `runserver` no
arranca un coordinador automáticamente.

`POST /api/v1/internal/fragments` recibe WAV PCM mono, 16 kHz y 16 bits,
checksum y metadatos de captura mediante multipart. Exige una credencial de
agente vinculada al box, independiente de los JWT de profesionales. Configura
`CAPTURE_AGENTS` y `CAPTURE_FRAGMENT_ROOT` según el
[contrato de ingesta](API_CONTRACTS.md#5-ingesta-interna-de-fragmentos);
sin agentes configurados se deniega todo acceso. El límite por defecto es 25 MiB.

Un reintento idéntico devuelve la confirmación existente sin duplicar trabajo;
un checksum distinto para la misma sesión/secuencia genera conflicto. La API
confirma solo tras guardar archivo y trabajo, y no ejecuta análisis ni envíos.
Ejecuta `manage.py cleanup_capture_uploads` al arrancar y periódicamente para
eliminar huérfanos antiguos; conserva cargas en curso y archivos de trabajos.
`manage.py process_fragment_jobs` consume la cola y elimina los archivos al terminar
cada trabajo, conservando el estado técnico y el resultado en SQL. El modo
`--continuous` espera nuevos trabajos; el modo por lote permite acotar la ejecución.
El [contrato de audio v2](docs/CONTROL-Y-AUDIO.md#audio) añade tiempos de sesión y
solapamiento; la ruta v1 se conserva para compatibilidad.

## Comprobar los cambios

Ejecuta desde la raíz:

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python scripts/check_boundaries.py
uv run python manage.py test --settings=backend.config.test_settings --noinput
node --test backend/apps/web/tests/*.test.cjs
```

Con pip, usa el mismo reemplazo de `uv run python` indicado arriba. Las pruebas crean una base separada y no modifican tu usuario local. Las pruebas JavaScript requieren Node.js 18 o superior. Para verificar HTTP y WebSocket con el agente, sigue la [guía de pruebas entre repositorios](docs/PRUEBAS-SERVIDOR-AGENTE.md); esa suite requiere uv y un wheel actualizado del agente. Si cambias modelos, genera y revisa la migración correspondiente antes de comprobar que no quedan migraciones pendientes.

## Dependencias y documentación

La estructura del código está en [backend](backend/README.md) y los documentos de referencia en [docs](docs/README.md). `.env`, la base SQLite y los correos locales no se suben a Git. La base y la clave Django local se guardan en `.local/` con la configuración predeterminada.

Solo si necesitas cambiar dependencias, edita `pyproject.toml` y ejecuta con uv:

```sh
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
```

Incluye `pyproject.toml`, `uv.lock` y `requirements.txt` en el mismo cambio. `requirements.txt` se genera; no se edita a mano.

La recuperación de audio pendiente y el despliegue coordinado de estas extensiones están descritos en [Continuidad de captura](docs/CONTINUIDAD-CAPTURA.md).
