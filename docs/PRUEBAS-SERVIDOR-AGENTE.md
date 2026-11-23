# Cómo probar el servidor junto con psycode-agent

Esta es la guía de entrada para probar la comunicación entre **psycode**
(servidor central) y **psycode-alterno** (programa instalado en cada sala).
Se puede hacer la prueba automática en una sola computadora.

## 1. Elegir la prueba

| Prueba | Para qué sirve | Qué necesita |
|---|---|---|
| Pruebas propias de cada repo | Detectar errores dentro de cada proyecto. | Python y uv. |
| **Integración automática entre repositorios** | Comprobar que el paquete del agente funciona con el servidor por HTTP y WebSocket. Es la primera prueba que debe hacer el equipo. | Ambos repositorios, Python, uv e Internet para instalar dependencias. |
| Captura manual con equipo real | Comprobar OBS, audio RTSP, permisos y recepción de WAV en el servidor. | Además, OBS, FFmpeg/ffprobe y una fuente RTSP operativa. |

La integración automática levanta sus propios procesos y usa audio y agenda
sintéticos. **No hay que abrir OBS, iniciar Django manualmente, configurar tokens,
crear usuarios, copiar `.env` ni conectarse a Smile para ejecutarla.** Tampoco
requiere MongoDB, correo ni claves de Speechmatics/JEV.

## 2. Preparar los repositorios

Necesitas Python **3.12 o 3.13**, [uv instalado](https://docs.astral.sh/uv/getting-started/installation/)
y una copia actualizada de cada repositorio. Pide al equipo la ubicación de ambos
repositorios y la rama que se va a probar; aquí no se supone un remoto ni una rama.

Las carpetas pueden estar en cualquier lugar y no necesitan ser hermanas. Cada
una tiene su propio `.venv`; no copies entornos ni añadas un repo al `PYTHONPATH`
del otro. Los comandos siguientes se ejecutan en la raíz indicada, donde está
`pyproject.toml`. `cd` significa cambiar a esa carpeta.

Comprueba que uv está disponible:

```sh
uv --version
```

## 3. Probar y construir el agente

Abre una terminal **en la raíz de psycode-agent** y ejecuta, uno por uno:

```sh
uv sync --locked --no-editable --extra smile --reinstall-package psycode-agent
uv run --no-sync pytest -q
uv run --no-sync psycode-agent --help
uv build --wheel
```

Estos comandos también se pueden ejecutar en PowerShell. La instalación incluye
las dependencias de desarrollo y el extra Smile, pero no instala ni abre el
navegador. Las pruebas ordinarias simulan OBS, FFmpeg y Smile.

Debe aparecer un resumen de pytest sin fallos, la ayuda de la CLI y un archivo
como este dentro de `dist/`:

```text
psycode_agent-1.0.0-py3-none-any.whl
```

Un **wheel** (`.whl`) es el paquete instalable del agente. La suite del servidor
prueba ese archivo, no el código de la carpeta del agente. Si cambias `src/`,
repite la instalación con `--reinstall-package`, las pruebas y la construcción.
Reutilizar un wheel antiguo probaría otra versión aunque el nombre sea igual.

Guarda la **ruta absoluta** del archivo recién construido. Si cambia la versión,
usa su nuevo nombre. No elijas un wheel solo porque ya existía en `dist/`.

## 4. Probar el servidor

Abre otra terminal **en la raíz de consultoria-bn**, donde está `manage.py`:

```sh
uv sync --locked --no-dev
npm ci --prefix frontend
npm run build --prefix frontend
uv run --no-sync python scripts/check_boundaries.py
uv run --no-sync python manage.py test --settings=backend.config.test_settings --noinput --exclude-tag=mongo --timing --durations 15
uv run --no-sync python manage.py makemigrations --check --dry-run --settings=backend.config.test_settings
```

Los resultados esperados son: comprobación de límites sin errores, suite Django
con `OK` y ninguna migración pendiente. Las pruebas de integración con MongoDB
requieren una instancia de pruebas. El número de pruebas cambia con el código.

Los ajustes de prueba omiten la carga del `.env` y preparan su propia base.
Cada invocación simultánea de Django necesita un `PSYCODE_TEST_SQLITE_PATH`
diferente. El CI de Linux usa `--parallel 4` dentro de una sola invocación
y Django crea una copia de SQLite por proceso.

## 5. Ejecutar la integración entre ambos

Continúa **en consultoria-bn**. Sustituye la ruta de ejemplo por la ruta absoluta
del wheel generado en el paso 3. Conserva las comillas si hay espacios.

macOS/Linux:

```sh
uv run --no-sync python -m tests.cross.run --agent-wheel "/ruta/psycode-agent/dist/psycode_agent-1.0.0-py3-none-any.whl"
```

Windows PowerShell:

```powershell
uv run --no-sync python -m tests.cross.run --agent-wheel "C:\ruta\psycode-agent\dist\psycode_agent-1.0.0-py3-none-any.whl"
```

**No hace falta arrancar `runserver`, Uvicorn, el coordinador ni el agente aparte.**
La suite crea bases, credenciales, archivos y un entorno del agente temporales;
elige puertos locales libres y arranca dos procesos ASGI, procesos del agente y
revisiones del coordinador. Al terminar cierra los procesos supervisados por la
suite y elimina el directorio temporal. uv puede conservar sus cachés de paquetes.
Para esta prueba, usa una terminal de desarrollo sin variables de producción
exportadas: no leer `.env` no elimina variables ya presentes en el entorno.

### Cómo reconocer que pasó

El comando debe terminar con **código de salida 0** y mostrar un JSON que incluya:

```json
{"result": "passed", "agent_wheel_sha256": "...", "coverage": ["..."]}
```

Ese fragmento ilustra las claves; el hash y la lista reales son más largos.
Que aparezca `uploaded` o que arranque el servidor no basta: hay comprobaciones
posteriores y seis casos históricos HTTP/ACK antes del resultado final.
Un traceback, una aserción fallida o un código distinto de cero significa fallo.
Para consultar el código inmediatamente después del comando:

```sh
echo $?
```

En PowerShell:

```powershell
$LASTEXITCODE
```

### Qué demuestra y qué queda fuera

| Se comprueba automáticamente | Se necesita otra validación |
|---|---|
| Agente instalado y aislado, sin Django/backend/MongoDB. | Instalación y permisos en las PCs institucionales. |
| Control WebSocket y HTTP interno v2 entre procesos. | Certificados, proxy y red del despliegue real. |
| Reconexión, sustitución de conexión y ACK perdido tras commit. | Comportamiento físico de OBS/MediaMTX ante fallos. |
| Upload idempotente, última secuencia y cierre de sesión. | Audio real, latencia y límite físico del corte. |
| Agenda sintética Excel/JSON recibida y observada por otro coordinador. | Login y descarga en Smile institucional. |
| Runtime del agente con OBS/FFmpeg simulados y procesamiento simulado. | Speechmatics/JEV, MongoDB, SMTP y alertas clínicas completas. |

Una suite aprobada en macOS no demuestra que se haya probado Windows o Linux.

## 6. Si algo falla

| Síntoma | Qué revisar |
|---|---|
| `uv` no se reconoce | Instalar uv y abrir de nuevo la terminal. |
| No encuentra `manage.py`, `tests.cross.run` o `backend` | Ejecutar el paso 5 desde la raíz de consultoria-bn, sin copiar los tests al agente. |
| No encuentra el wheel o aparece `AssertionError` al comienzo | Comprobar la ruta absoluta, las comillas y que el paso 3 haya terminado. |
| Falla instalando dependencias | Comprobar Internet, acceso al índice de paquetes y versión Python. La prueba usa red local; la instalación puede necesitar Internet. |
| No encuentra `pytest` | En el agente, repetir el `uv sync` del paso 3, que incluye desarrollo; no usar `--no-dev` para sus pruebas. |
| Un cambio del agente no aparece en la prueba | Reinstalar el paquete no editable y reconstruir el wheel. Verificar la ruta y el hash que informa la suite. |
| SQLite bloqueado o una base de pruebas ya existe | Detener otra suite que use la misma base y ejecutar en serie; no borrar una base operativa. |
| Falla el upload por falta de inicio confirmado | Comprobar que ambos repos estén actualizados. El fixture actual registra el inicio y su ACK; no desactivar esa protección ni editar journals para forzar envíos. |
| `PROCESS_ALREADY_RUNNING` en una prueba manual | Revisar si ya hay un coordinador/trabajador o agente con la misma base/raíz de estado. |

Para compartir un fallo, guarda el comando, la salida completa, el sistema
operativo, la versión Python y las revisiones de ambos repositorios. No incluyas
tokens, `.env`, audio real ni reportes institucionales.

## 7. Prueba manual de captura con OBS y audio real

Este recorrido es **opcional** y requiere tener operativa la topología
[OBS → SRT → MediaMTX → RTSP](../../psycode-agent/docs/CAPTURA-LOCAL.md).
Ese enlace local supone carpetas hermanas; si están en otro lugar, abre
`docs/CAPTURA-LOCAL.md` dentro del agente. Esta guía no instala ni configura
MediaMTX, y la prueba automática anterior no lo necesita.

Usa una computadora de prueba y una fuente de audio sintética. El objetivo es
ver una orden central iniciar y detener OBS y recibir WAV; no evaluar pacientes.

### 7.1 Configurar un servidor local de pruebas

Usa un checkout dedicado a esta prueba y su propio `.env`, basado en
`.env.example`. No reemplaces un `.env` existente ni uses la base de producción.
Configura estos valores y deja las claves de proveedores vacías:

```dotenv
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]
FRONTEND_BASE_URL=http://127.0.0.1:8000
SQLITE_PATH=.local/manual-integration.sqlite3
CAPTURE_FRAGMENT_ROOT=.local/manual-integration-fragments
MONGODB_URI=
EMAIL_BACKEND=file
NOTIFICATIONS_ENABLED=false
PSYCODE_EXTERNAL_PROCESSING_ENABLED=0
```

Genera una identidad solo para esta prueba, desde consultoria-bn:

```sh
uv run --no-sync python -c "import hashlib,json,secrets; t='manual-box-3.'+secrets.token_urlsafe(32); print('PSYCODE_AGENT_TOKEN='+t); print('CAPTURE_AGENTS='+json.dumps({'manual-box-3':{'box':'box-3','token_sha256':hashlib.sha256(t.encode()).hexdigest()}}))"
```

Reemplaza la línea `CAPTURE_AGENTS=...` del `.env` del **servidor** y la línea
`PSYCODE_AGENT_TOKEN=...` del archivo privado del **agente** con las generadas.
No dejes varias definiciones de la misma variable. El servidor guarda
el hash del token completo; el agente necesita el token original. No los
intercambies ni los subas a Git. El token no sirve para iniciar sesión web.

Aplica migraciones a esa base de pruebas:

```sh
uv run --no-sync python manage.py migrate
```

### 7.2 Configurar el agente de prueba

Parte del `.env.example` del agente y guarda la copia fuera del checkout, con
acceso solo para tu cuenta. Completa al menos:

```dotenv
BOX_ID=box-3
PSYCODE_INTERNAL_BASE_URL=http://127.0.0.1:8000
PSYCODE_WEBSOCKET_URL=ws://127.0.0.1:8000/ws/v1/agents
PSYCODE_AGENT_TOKEN=<token original generado en 7.1>
OBSW_HOST=127.0.0.1
OBSW_PORT=4455
OBSW_PASSWORD=<contraseña de OBS de prueba>
STREAM_URL=rtsp://127.0.0.1:8554/sala3
AGENT_STATE_ROOT=<ruta absoluta nueva y privada para esta prueba>
CHUNK_DURATION=10
CHUNK_OVERLAP=1
```

Sustituye los valores entre `<...>` y usa la URL RTSP que realmente publique
audio en tu instalación. Los valores `127.0.0.1` suponen que ambos programas
están en la misma computadora; HTTP/WS solo se admiten en loopback. Para PCs
distintas, configura HTTPS/WSS con certificados válidos según
[operación separada](OPERACION-SEPARADA.md).

Selecciona el archivo **en cada terminal del agente** antes de ejecutar comandos:

macOS/Linux:

```sh
export PSYCODE_ENV_FILE="/ruta/privada/agent-manual.env"
```

PowerShell:

```powershell
$env:PSYCODE_ENV_FILE = 'C:\ruta\privada\agent-manual.env'
```

Las variables ya exportadas prevalecen sobre el archivo. Abre una terminal
limpia si antes configuraste otro box o servidor. No reutilices journals ni
pendientes de otra instalación.

### 7.3 Arrancar y autorizar una ventana corta

1. Abre OBS con su WebSocket habilitado y la salida hacia MediaMTX preparada.
   Desde la raíz del agente ejecuta `uv run --no-sync psycode-agent diagnose`.
   El JSON debe mostrar `ffmpeg: true`, `ffprobe: true` y un objeto `obs` con el
   estado de sus salidas. Si `obs` vale `unavailable`, corrige la conexión antes
   de seguir. Esto aún no demuestra que llegue audio.
2. En una terminal del servidor, deja Uvicorn ejecutándose:

   ```sh
   uv run --no-sync uvicorn backend.config.asgi:application --host 127.0.0.1 --port 8000
   ```

3. En la terminal del agente, deja ejecutándose:

   ```sh
   uv run --no-sync psycode-agent run
   ```

   El agente debe esperar órdenes; arrancarlo por sí solo no autoriza grabación.
4. En otra terminal del servidor, crea una ventana de **cinco minutos** para
   hoy. En el siguiente comando, **cambia `09:00` y `09:05`** por horas próximas
   de Santiago: inicio uno o dos minutos después de la hora actual y fin cinco
   minutos después del inicio, dentro del mismo día.

   ```sh
   uv run --no-sync python manage.py shell -c "from backend.apps.operational.models import OperationalConfiguration; OperationalConfiguration.objects.update_or_create(pk=1, defaults={'enabled_days':list(range(7)), 'open_time':'09:00', 'close_time':'09:05', 'primary_email':'synthetic@example.test', 'backup_enabled':False})"
   ```

   Sobre una base nueva sin agenda, el servidor usa el horario clínico como
   respaldo. La ventana se crea en el servidor; no se fabrican órdenes ni ACK
   locales. El coordinador evalúa los boxes 3–7 y puede crear sesiones para los
   otros boxes sin agente; en este recorrido se comprueba solo `box-3`.
5. En esa terminal del servidor, deja ejecutándose el coordinador:

   ```sh
   uv run --no-sync python manage.py coordinate_capture
   ```

   Al comenzar la ventana, debe emitir el inicio. Al terminar, debe pedir el corte.
   No uses `runserver` para reemplazar Uvicorn: no atiende este WebSocket.

### 7.4 Comprobar recepción y cierre

Desde una terminal adicional del servidor:

```sh
uv run --no-sync python manage.py capture_health
uv run --no-sync python manage.py shell -c "from backend.apps.capture.models import CaptureSession, FragmentJob; print(list(CaptureSession.objects.filter(box='box-3').values('session_id','state','actual_start','actual_end','final_sequence','error_code'))); print(list(FragmentJob.objects.filter(sequence__session__box='box-3').values('sequence__number','state','result')))"
```

Para `box-3`, espera observar:

- La sesión pasa de `iniciada` a `activa`, después a `finalizando` y `completada`.
- OBS inicia sus salidas, se recibe audio y se detiene al terminar la ventana.
- Aparecen trabajos de fragmentos en el servidor con secuencias consecutivas.
- El agente conserva sus manifiestos y elimina cada WAV local solo después de
  una aceptación durable y coincidente del servidor.

En este recorrido **no arranques `process_fragment_jobs`**: los trabajos quedan
`pendiente` y los WAV recibidos permanecen en el servidor de pruebas. Eso permite
comprobar recepción sin activar análisis. Una alerta clínica no es un criterio
de éxito de esta prueba. El trabajador y los proveedores tienen otro alcance,
descrito en [la integración de análisis](INTEGRACION-SPEECHMATICS-JEV.md).

Si necesitas cortar antes, detén el coordinador con `Ctrl+C`: solicita cortes
sin generar nuevos inicios. Mantén Uvicorn y el agente activos hasta que la
sesión cierre y se reciban los pendientes; la finalización tiene un plazo
central de 300 s. Después solicita `uv run --no-sync psycode-agent stop` desde
otra terminal del agente con el mismo `PSYCODE_ENV_FILE`, comprueba que `run`
terminó y por último detén Uvicorn. Conserva el estado si hubo un fallo; no borres
journals ni renumeres WAV para forzar la aceptación.

El inicio automático Windows, las caídas de red, el disco lleno y Smile real
requieren las comprobaciones adicionales de `docs/REVISION-FUNCIONAMIENTO.md`
del agente. No quedan acreditados por este recorrido básico.

## 8. Qué registrar y qué está automatizado

Al compartir un resultado, indica fecha, sistema operativo, `uv --version`,
`uv run --no-sync python --version`, revisiones de ambos repositorios
(`git rev-parse HEAD` y `git status --short` dentro de cada uno), comando ejecutado,
JSON final y SHA-256 del wheel. Indica si hubo cambios sin commit y distingue
simulación de captura real.

El CI del servidor (`.github/workflows/ci.yml`) ejecuta Django en Linux con
Python 3.12 y 3.13. MongoDB y los recorridos de navegador del servidor se
ejecutan en jobs independientes.

El workflow **Server and agent** construye el wheel desde `main` del agente
o desde la revisión indicada por `PSYCODE_AGENT_REF`, ejecuta la suite
cruzada y comprueba en Chromium el emparejamiento de un PC por HTTPS y WSS.
Para habilitarlo, configura en el repositorio del servidor el secreto
`PSYCODE_AGENT_READ_TOKEN` con permiso de lectura de contenidos sobre el
repositorio privado `Martin-Ferreira-O/psycode-alterno`. Puedes iniciarlo
manualmente desde Actions. La variable de repositorio
`PSYCODE_AGENT_TESTS=true` habilita además las ejecuciones automáticas
ante cambios relevantes en `main`.

Los reportes de separación del 27 de octubre son antecedentes. La revisión del
agente registró un fallo de fixture HTTP/ACK que después fue corregido en el
servidor, como documenta [su revisión funcional](REVISION-FUNCIONAMIENTO-SERVIDOR.md).
Para validar otra revisión, construye su wheel y vuelve a ejecutar la suite.

Comprobación de esta actualización documental, **28 de octubre de 2026, macOS**:
la suite cruzada terminó con código 0 y `result: passed` usando el wheel con
SHA-256 `2b3acf48a1d795a2ac496b9ffa89f45faba14a4332b2a681e288947a2d1528d4`.
Sus módulos Python se compararon con `src/psycode_agent/` y coincidieron byte a
byte. Esto valida el comando y la integración simulada en ese entorno; el
recorrido manual con OBS no se ejecutó en esta actualización.

Referencias de uv: [sincronización y paquetes no editables](https://docs.astral.sh/uv/concepts/projects/sync/)
y [construcción de distribuciones](https://docs.astral.sh/uv/guides/package/).
