# SCRUM-72 — Agente de captura por box
## 1. Descripción y estado
SCRUM-72 implementa el **agente local de captura de audio por box** de Psycode. El agente controla OBS Studio mediante WebSocket, consume el audio que MediaMTX publica por RTSP, lo fragmenta en WAV y administra el envío de los fragmentos a la API interna de SCRUM-73.

La solución incluye configuración por box, almacenamiento local, metadatos, reintentos, seguimiento de órdenes, detención controlada y mecanismos preventivos de recuperación.

**Estado de la entrega:** implementación local desarrollada y validada mediante **103 pruebas automatizadas aprobadas** y pruebas de laboratorio con OBS, MediaMTX y FFmpeg reales. **No se ha completado la integración remota autónoma con SCRUM-71 ni una prueba integral de extremo a extremo con sesiones reales.**

## 2. Alcance y responsabilidades
El agente de SCRUM-72 se encarga de:

- Configurarse mediante variables de entorno sin cambios al código para cada box.
- Procesar órdenes de inicio y detención mediante el contrato de control de SCRUM-71.
- Controlar la grabación y el streaming de OBS usando WebSocket.
- Esperar la disponibilidad del audio RTSP antes de iniciar la captura coordinada.
- Capturar audio con FFmpeg y generar fragmentos WAV con duración y solapamiento configurables.
- Identificar cada fragmento mediante `box`, `session_id`, `sequence`, `captured_at` y checksum SHA-256.
- Conservar la identificación de los fragmentos durante los reintentos.
- Enviar los archivos mediante la API de ingesta de SCRUM-73, conservándolos hasta una confirmación válida.
- Procesar la detención, intentar finalizar los envíos pendientes y comunicar `last_sequence`.
- Registrar órdenes y confirmaciones para detectar duplicados y situaciones que requieren reconciliación.

**Fuera de alcance:** autorizar sesiones; implementar el backend de control de SCRUM-71; implementar la API de ingesta de SCRUM-73; analizar audio; generar alertas clínicas; desarrollar una interfaz gráfica propia.

## 3. Arquitectura
### Flujo de captura
```text
OBS Studio (PC del box)
  |-- Grabación local
  +-- Streaming SRT
          |
          v
       MediaMTX
          | RTSP
          v
        FFmpeg
          | PCM 16 kHz, mono, 16 bits
          v
     audio_chunker.py
          | WAV + JSON + SHA-256
          v
     FragmentStore
          |
          v
      UploadQueue / UploadWorker
          | HTTP
          v
     API interna SCRUM-73
```

### Flujo de control
```text
SCRUM-71 (backend)
        |
        | Adaptador de control (transporte remoto pendiente)
        v
     AgentLoop
        |
        v
  SessionCoordinator
        |-- CommandJournal
        |-- OBSController
        +-- CaptureRunner
              |-- audio_chunker
              |-- FragmentStore
              +-- UploadWorker
```

La captura y el envío de archivos se realizan concurrentemente. El agente no necesita una interfaz gráfica propia; OBS Studio sí debe estar instalado y ejecutándose cuando se controlan sus salidas.

### Despliegue modular en múltiples computadores

La arquitectura está diseñada para ejecutar **una instancia independiente del agente por box**, utilizando el mismo código Python y modificando solo su configuración local. `AgentConfig` controla un único `BOX_ID`, un destino OBS WebSocket y una URL RTSP por instancia; no se requiere crear una versión distinta del programa para cada sala.

Ejemplo de distribución prevista:

```text
PC Box 3 -> Agente box-3 -> OBS -> MediaMTX (ruta sala3)
PC Box 4 -> Agente box-4 -> OBS -> MediaMTX (ruta sala4)
PC Box 5 -> Agente box-5 -> OBS -> MediaMTX (ruta sala5)
PC Box 6 -> Agente box-6 -> OBS -> MediaMTX (ruta sala6)
PC Box 7 -> Agente box-7 -> OBS -> MediaMTX (ruta sala7)
                                        |
                                        v
                                Backend compartido
```

Las rutas `sala3` a `sala7` son **ejemplos**, no rutas configuradas automáticamente; cada OBS debe publicar en MediaMTX la ruta que coincida con el `STREAM_URL` de su agente. También puede emplearse otro esquema de nombres.

Ejemplos de configuración por equipo:

**PC del Box 5:**

```dotenv
BOX_ID=box-5
OBSW_HOST=127.0.0.1
STREAM_URL=rtsp://IP_MEDIAMTX:8554/sala5
```

**PC del Box 6:**

```dotenv
BOX_ID=box-6
OBSW_HOST=127.0.0.1
STREAM_URL=rtsp://IP_MEDIAMTX:8554/sala6
```

Estos fragmentos complementan la configuración general: cada instancia también requiere sus credenciales de OBS y del backend. `127.0.0.1` sirve cuando OBS corre en el mismo PC que el agente; si OBS está en otro equipo, debe configurarse una dirección accesible y proteger el acceso WebSocket.

Cada equipo debe mantener **su propio `.env`, almacenamiento de fragmentos y estado persistente**. El backend y MediaMTX pueden compartirse, siempre que soporten la carga concurrente y se configuren las rutas y credenciales correspondientes. La implementación actual se configura para **un box por proceso**, no para que una única instancia controle cinco boxes.

**Estado de validación:** se ha comprobado el flujo de laboratorio con OBS, MediaMTX y FFmpeg, pero **no se han ejecutado ni validado cinco agentes simultáneos** ni su integración remota completa con SCRUM-71. El despliegue multibox sigue sujeto a pruebas de concurrencia, conectividad y capacidad del sistema.

## 4. Componentes
| Archivo | Responsabilidad |
|---|---|
| `config.py` | Carga y validación de configuración por box. |
| `main.py` | Comandos **manuales** de consulta, inicio y detención de OBS. |
| `obs_controller.py` | Conexión OBS WebSocket, control de salidas y espera de audio RTSP mediante `ffprobe`. |
| `audio_chunker.py` | Lectura del audio con FFmpeg, fragmentación y generación de WAV/JSON. |
| `fragment_store.py` | Persistencia y consulta de fragmentos locales. |
| `capture_runner.py` | Coordinación de la captura y del worker de envío. |
| `backend_client.py` | Cliente HTTP y validación de respuestas de SCRUM-73. |
| `upload_queue.py` | Procesamiento de fragmentos pendientes y registro de aceptación. |
| `upload_worker.py` | Envíos en un hilo separado y cierre controlado. |
| `command_journal.py` | Registro persistente de órdenes y confirmaciones por box. |
| `session_coordinator.py` | Coordinación de órdenes, OBS, captura, detención y última secuencia. |
| `agent_loop.py` | Consulta de órdenes, heartbeat y manejo de fallos del control. |

## 5. Requisitos y preparación
- Python con las dependencias del repositorio Psycode instaladas y el entorno virtual activado.
- OBS Studio con **OBS WebSocket** habilitado y una contraseña configurada.
- FFmpeg y `ffprobe` accesibles desde el `PATH`.
- MediaMTX configurado para recibir el streaming SRT de OBS y exponer audio por RTSP.
- Acceso a la API de SCRUM-73 para realizar envíos HTTP autenticados.

Versiones empleadas durante la validación de laboratorio: **Windows 11, OBS 32.2.1, OBS WebSocket 5.7.4, MediaMTX v1.20.1 y FFmpeg 8.0.1**. La última suite automatizada se ejecutó con **Python 3.12.14**. Son versiones observadas, no una matriz de compatibilidad certificada.

Verificación de las herramientas de consola:

```powershell
python --version
ffmpeg -version
ffprobe -version
```

## 6. Configuración del agente
`AgentConfig.from_env()` carga variables de entorno y, mediante `python-dotenv`, lee el archivo local:

```text
backend/apps/capture/agent/.env
```

Ejemplo **mínimo de desarrollo** (reemplazar direcciones y credenciales; no copiarlas a Git):

```dotenv
BOX_ID=box-5
OBSW_HOST=127.0.0.1
OBSW_PORT=4455
OBSW_PASSWORD=REEMPLAZAR_CON_PASSWORD_LOCAL
STREAM_URL=rtsp://IP_MEDIAMTX:8554/sala1
CHUNK_DURATION=10
CHUNK_OVERLAP=1
PSYCODE_INTERNAL_BASE_URL=http://127.0.0.1:8000
PSYCODE_AGENT_TOKEN=REEMPLAZAR_CON_TOKEN_DEL_AGENTE
```

La URL del backend `127.0.0.1` es adecuada solo si el servidor Django está en el **mismo equipo** que el agente. En un despliegue distribuido debe utilizarse la dirección alcanzable del backend. Del mismo modo, `OBSW_HOST` corresponde al equipo que ejecuta OBS.

### Variables admitidas por `config.py`
| Variable | Uso | Valor predeterminado |
|---|---|---|
| `BOX_ID` | Identidad del agente: `box-3` a `box-7`. | Obligatoria. |
| `OBSW_HOST` | Host de OBS WebSocket. | `127.0.0.1` |
| `OBSW_PORT` | Puerto de OBS WebSocket. | `4455` |
| `OBSW_PASSWORD` | Contraseña de OBS WebSocket. | Obligatoria. |
| `STREAM_URL` | URL RTSP publicada por MediaMTX. | Vacía. |
| `CHUNK_DURATION` | Duración de fragmentos en segundos. | `10` |
| `CHUNK_OVERLAP` | Solapamiento en segundos. | `1` |
| `PSYCODE_INTERNAL_BASE_URL` | URL base de la API de SCRUM-73. | Vacía. |
| `PSYCODE_AGENT_TOKEN` | Token HTTP de agente. | Vacío. |
| `HTTP_TIMEOUT` | Timeout HTTP, segundos. | `15` |
| `MAX_RETRIES` | Máximo de intentos de envío. | `3` |
| `RETRY_BACKOFF` | Parámetro de espera entre reintentos. | `2` |
| `COMMAND_POLL_INTERVAL` | Intervalo de consulta de órdenes, segundos. | `5` |
| `HEARTBEAT_INTERVAL` | Intervalo de heartbeat, segundos. | `30` |
| `CONTROL_MAX_FAILURES` | Límite de fallos consecutivos del canal de control. | `6` |
| `AGENT_STATE_ROOT` | Directorio persistente del journal. | `~/.psycode/capture-agent-state` |

`CHUNK_DURATION` debe ser positivo y `CHUNK_OVERLAP` debe estar entre `0` (inclusive) y `CHUNK_DURATION` (exclusivo). Si se define `AGENT_STATE_ROOT`, debe ser una ruta absoluta.

**Las variables con valores predeterminados son opcionales en `.env`.** Por ejemplo, `COMMAND_POLL_INTERVAL`, `HEARTBEAT_INTERVAL` y `CONTROL_MAX_FAILURES` **no tienen que aparecer en tu archivo**: el agente utiliza `5`, `30` y `6`, respectivamente. Por otra parte, para ejecutar una subida autenticada sí hay que proporcionar una URL y token válidos, aunque `config.py` permita dejarlos vacíos al cargar la configuración.

## 7. Ejecución manual y alcance de `main.py`
Desde la raíz del repositorio y con el entorno Python activado:

```powershell
python backend/apps/capture/agent/main.py status
python backend/apps/capture/agent/main.py start
python backend/apps/capture/agent/main.py stop
```

Estos comandos **solo controlan OBS** y se utilizaron en la validación real de grabación y streaming. **No inician automáticamente `AgentLoop`, no crean sesiones autorizadas, no fragmentan audio por sí solos y no establecen la conexión remota definitiva con SCRUM-71.**

## 8. Captura, fragmentos y sincronización con MediaMTX
El agente recibe audio RTSP y lo convierte con FFmpeg a **PCM lineal de 16 bits, 16 kHz y mono**, guardado en archivos WAV. La duración y el solapamiento son configurables.

Los archivos se organizan por sesión en el directorio local `backend/apps/capture/agent/fragments/`:

```text
fragments/
  <session_id>/
    000000.wav
    000000.json
    000001.wav
    000001.json
```

Cada JSON incluye `box`, `session_id`, `sequence`, `filename`, `checksum_sha256`, `captured_at`, `duration_seconds`, `status` y `attempts`. El checksum se utiliza para comprobar la identidad del contenido. La fecha de captura se registra con referencia temporal proporcionada al agente; **no representa necesariamente el PTS exacto del streaming**.

### Disponibilidad RTSP
En las pruebas reales se detectó una condición de carrera: OBS comenzaba a publicar SRT y FFmpeg solicitaba el RTSP antes de que MediaMTX tuviera lista la pista de audio, lo que provocaba un `404 Not Found`.

Para el inicio **coordinado** se implementó una espera limitada mediante `ffprobe` antes de avanzar con la captura. Si no aparece la pista de audio, se rechaza el inicio y se intenta revertir las salidas de OBS. Esta corrección dispone de pruebas automatizadas; su recorrido completo desde SCRUM-71 hasta OBS real todavía no ha sido validado.

### Evidencia real de fragmentación
Durante una captura de laboratorio de aproximadamente 30 segundos, con fragmentos de 10 segundos y solapamiento de 1 segundo, se generaron:

```text
Fragmento 0: 10.000 s
Fragmento 1: 10.000 s
Fragmento 2: 10.000 s
Fragmento 3:  3.000 s
Total de fragmentos: 4
```

También se comprobó la retención local de los WAV/JSON cuando no pudo completarse su subida al backend.

## 9. Envío HTTP a SCRUM-73
El agente utiliza el endpoint de ingesta:

```http
POST /api/v1/internal/fragments
```

La autenticación utiliza una credencial de tipo `Agent`; el backend valida el agente, su asociación con el box y la sesión correspondiente. Para que la subida sea aceptada, **la sesión debe existir y estar autorizada en Django**. El agente no crea ni autoriza sesiones.

`UploadQueue` verifica los metadatos locales, registra los intentos y utiliza `BackendClient` para subir cada archivo. Una vez recibida una confirmación válida, registra su aceptación y elimina el WAV local. **Si falla la subida o no existe confirmación válida, el archivo permanece en disco.** Los reintentos conservan `session_id`, secuencia, fecha y checksum.

`UploadWorker` funciona en un hilo separado para evitar bloquear directamente la captura mientras se procesan las peticiones HTTP.

### ¿Qué se probó realmente?
- **Integración con Django mediante `WSGITransport`:** pruebas que ejecutan la aplicación Django real y su base de datos de pruebas sin establecer una conexión TCP entre equipos. Se validaron recepción, confirmaciones, idempotencia y conservación/eliminación local de fragmentos.
- **Servidor Django local por HTTP:** se comprobó el endpoint con respuestas `401` sin autenticación válida y `400` ante una solicitud autenticada pero incompleta. Esto verifica que la ruta, el servidor y la validación responden por HTTP.
- **Pendiente:** una subida completa de WAV por TCP/IP desde el agente hacia Django utilizando una **sesión real autorizada**. Los WAV del laboratorio tenían un `session_id` que no existía en la base de datos del servidor.

Por tanto, **el cliente de SCRUM-72 y el contrato de ingesta de SCRUM-73 están probados conjuntamente**, pero aún falta la validación operativa completa por red con una sesión válida.

## 10. Detención controlada y secuencia final
Cuando el coordinador recibe una orden de detención correspondiente a la sesión activa:

1. Solicita a `CaptureRunner` la detención mediante `stop_event`.
2. FFmpeg termina y `audio_chunker` guarda el último fragmento si contiene audio nuevo, evitando generar uno compuesto únicamente por solapamiento.
3. `CaptureRunner` solicita al worker una última revisión de pendientes y espera su terminación con un timeout (20 segundos en `CaptureRunner`).
4. Si el hilo de captura no termina dentro del plazo, o se detecta un fallo técnico, **no debe darse por exitosa la detención**.
5. Tras la finalización satisfactoria, el coordinador detiene OBS, consulta `FragmentStore.last_sequence(session_id)` y confirma la orden incluyendo `last_sequence`.
6. La secuencia final se conserva en `CommandJournal` para recuperar determinadas confirmaciones sin repetir la detención.

**Precisión:** `last_sequence` es la última secuencia **generada/registrada localmente**, no necesariamente la última recibida por el backend. Además, que un worker termine no significa por sí solo que todos los fragmentos hayan sido aceptados; `CaptureRunner` comprueba también el estado de fallo del worker. La entrega total y los fallos de red están sujetos a las confirmaciones de SCRUM-73.

La prueba `test_stop_drain.py` comprueba que, si aparece un segundo fragmento mientras el worker está procesando otro, ambos se procesan antes de un cierre controlado de la cola simulada. **Esto no sustituye una prueba de detención integral con los sistemas reales.**

## 11. Control de SCRUM-71: implementación y dependencia
### Implementado y probado localmente
`AgentLoop` y `SessionCoordinator` procesan órdenes según el contrato local de control y utilizan operaciones como:

| Operación | Propósito |
|---|---|
| `commands()` | Obtener órdenes pendientes. |
| `acknowledge()` | Confirmar resultado de inicio o detención. |
| `heartbeat()` | Informar actividad durante una sesión. |
| `interrupted()` | Reportar una interrupción. |

Se han probado con componentes simulados el procesamiento de órdenes, las confirmaciones, la gestión de duplicados, los reportes y determinados escenarios de recuperación.

### Pendiente para cumplir el criterio de aceptación completo
**Falta conectar y probar el adaptador del agente con el transporte remoto definitivo de SCRUM-71.** Hasta entonces, el agente no está validado recibiendo y confirmando órdenes reales de forma autónoma desde el backend.

Esto es una **dependencia de integración entre equipos**, pero la implementación del **cliente del lado del agente** forma parte del trabajo de SCRUM-72 cuando esté definido el transporte. No implica implementar el backend de SCRUM-71 ni inventar endpoints nuevos.

## 12. Persistencia, fallos y recuperación
`CommandJournal` persiste por box la intención y el resultado de las órdenes:

| Estado | Interpretación |
|---|---|
| `prepared` | Se registró la intención de ejecutar la orden. |
| `executed` | Se registró su ejecución. |
| `acknowledged` | Se registró su confirmación. |

El agente contempla la detección de sesiones sin cierre registrado, la inspección del estado de OBS al arrancar y el bloqueo de operaciones cuando resulta inseguro continuar sin reconciliación.

También implementa límites de reintentos HTTP, gestión de errores de OBS/FFmpeg, seguimiento de fallos de control y un intento de cierre seguro si se pierde la comunicación de control.

**Limitación conocida:** la reconciliación de sesiones anteriores no es completamente automática; algunos estados requieren intervención operativa. Tampoco puede garantizarse el cierre controlado si el proceso o el equipo finaliza abruptamente.

## 13. Pruebas y resultados

El agente SCRUM-72 fue validado mediante pruebas automatizadas y pruebas de integración con componentes simulados y reales.

### Pruebas automatizadas

Para ejecutar la suite completa desde la raíz del repositorio:

```powershell
python -m pytest backend/apps/capture/agent -q --ds=backend.config.test_settings
```

**Último resultado obtenido:**

```text
103 passed in 16.51s
```

Las pruebas cubren las principales funcionalidades del agente:

- Control de OBS mediante WebSocket.
- Captura de audio, fragmentación WAV y generación de metadatos.
- Envío HTTP, reintentos e integración con SCRUM-73.
- Procesamiento y confirmación de órdenes simuladas de SCRUM-71.
- Persistencia, recuperación y manejo de errores.
- Detención controlada y procesamiento de fragmentos pendientes.

### Validación con componentes reales

Se verificó el funcionamiento de OBS Studio mediante WebSocket, la transmisión SRT hacia MediaMTX y la captura de audio RTSP con FFmpeg, incluyendo la generación de fragmentos WAV.

También se realizaron pruebas de integración HTTP con Django mediante `WSGITransport` y comprobaciones de autenticación y validación utilizando un servidor HTTP local.

**Limitaciones:** queda pendiente validar el ciclo completo entre computadores, incluyendo la recepción de órdenes reales de SCRUM-71 y el envío de fragmentos a una sesión autorizada de SCRUM-73. Las 103 pruebas aprobadas no representan una validación de cinco boxes simultáneos.

## 14. Pendientes de integración y aceptación
| Actividad | Estado / dependencia |
|---|---|
| Conectar y probar recepción/confirmación remota de órdenes de SCRUM-71. | Pendiente; coordinación con SCRUM-71 y trabajo del cliente del agente. |
| Verificar heartbeat, interrupciones y `last_sequence` mediante el transporte definitivo. | Pendiente de integración con SCRUM-71. |
| Subir un WAV real al backend por HTTP usando una sesión autorizada. | Pendiente de validación conjunta con SCRUM-71/SCRUM-73. |
| Probar inicio, captura, subida y detención de extremo a extremo entre equipos. | Pendiente de validación operativa conjunta. |
| Definir y validar una reconciliación operativa para estados bloqueados. | Pendiente de procedimiento acordado por el equipo; no implica que exista una recuperación automática completa. |

La especificación de integración compartida por el equipo se encuentra en [`docs/SCRUM-72-INTEGRACION.md`](../../../../docs/SCRUM-72-INTEGRACION.md). Este README documenta la implementación del agente, no reemplaza ese contrato.

## 15. Seguridad y archivos locales
- **Nunca subir a Git** `.env`, tokens, contraseñas ni grabaciones reales o de prueba.
- Restringir el acceso a los WAV, JSON de metadatos y archivos persistentes del journal.
- Los archivos que aún no tienen confirmación válida de SCRUM-73 deben conservarse para reintentos y análisis de errores.
- El uso de datos reales requiere las autorizaciones y controles de protección de información definidos para Psycode.

## 16. Conclusión
**La implementación local de SCRUM-72 está desarrollada y validada**, con control real de OBS, lectura RTSP desde MediaMTX, fragmentación WAV y pruebas de integración del cliente de SCRUM-73. Se cuenta con **103 pruebas automatizadas aprobadas**.

**La aceptación integral del criterio «recibir y confirmar órdenes de SCRUM-71» y la validación extremo a extremo siguen pendientes**, porque requieren conectar el transporte remoto definitivo y ejecutar pruebas con una sesión real autorizada. Esto debe quedar explícito en la entrega; no se considera implementado el backend de las tareas de otros integrantes.
