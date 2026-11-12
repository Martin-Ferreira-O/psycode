# Sesiones de captura e ingesta interna

> La política actual de desconexiones, recepción de siete días y cierre físico independiente está en [Continuidad de captura](../../../docs/CONTINUIDAD-CAPTURA.md). Sustituye los plazos de cierre definitivo históricos descritos más abajo.

> Actualización de separación: [operación vigente](../../../docs/OPERACION-SEPARADA.md). Agente en el repositorio independiente `psycode-agent`; control WS autenticado, audio v1/v2 y agenda durable. Las instrucciones históricas incompatibles quedan sustituidas por ese runbook.


Persistencia SQL de la autorización de SCRUM-70 hasta el cierre (SCRUM-71) e
ingesta autenticada de fragmentos a almacenamiento privado y cola SQL. No lee
Excel, controla OBS ni ejecuta análisis. En SQL guarda identificadores, box,
origen, estados, fechas, secuencias, metadatos de archivo y códigos técnicos.
El audio queda solo en archivos privados temporales. Los UUID de captura son
distintos de las sesiones JWT.

Para implementar el agente del box, consultar el
[traspaso de integración SCRUM-72](../../../docs/SCRUM-72-INTEGRACION.md),
que distingue la API de archivos disponible del control WebSocket implementado para
transportar órdenes y definir duración/solapamiento.

## Integración con SCRUM-70

`OperationalService.authorize_box_capture()` y `authorize_box_transition()`
conservan su contrato de autorización y ahora sincronizan la sesión persistente.
`CaptureAuthorizationService.evaluate_box()` sigue siendo una consulta sin
crear sesiones. Para un coordinador nuevo, usar la composición siguiente:

```python
from backend.config.composition import capture_session_service

# Compartir la MISMA instancia de AgendaService que ya usa SCRUM-70.
coordinator = capture_session_service(agenda_service=agenda)

# En cada tick del coordinador, para las salas conocidas del registro y la configuración:
session = coordinator.reconcile_box("box-3")
```

El coordinador debe ejecutarse periódicamente y ante cambios de autorización.
La agenda sigue siendo responsabilidad de SCRUM-70; construir otra instancia
vacía de agenda activa su política de respaldo por horario clínico.
No se inicia ningún trabajador en WSGI, AppConfig ni al importar módulos.

La sesión y su orden de inicio se guardan en una transacción, insertando primero
la sesión. La orden solo es visible para otra conexión después del commit.
Un índice único parcial impide dos sesiones abiertas por box, incluyendo
`iniciada`, `activa` y `finalizando`. Otra restricción identifica la ventana
por `(box, origen, inicio programado, término programado)` mientras su
`authorization_ended_at` sea nulo: repetir un tick o reiniciar el proceso no
reabre una sesión completada o fallida dentro de la misma autorización.
Una revocación o cambio de ventana/origen registra el fin de la autorización,
incluso si la sesión ya falló. Una autorización posterior puede crear otra sesión
con un UUID y una orden de inicio nuevos dentro de la misma ventana, una vez
cerrada la anterior y confirmadas las detenciones pendientes. Volver de agenda
al horario de respaldo también permite una nueva sesión en ese horario.

Una revocación, vencimiento o cambio de ventana/origen deja la sesión en
`finalizando`, cancela el inicio pendiente y crea una única detención. El contexto
original se conserva. Una ventana nueva puede iniciar en el próximo tick después
del cierre; no se solapan ventanas durante la finalización.

## Contrato del agente

`ports.BoxAgentControl` define la interfaz interna de control, implementada por
`CaptureSessionService`. Todos los métodos validan el box y la pertenencia del
identificador recibido. El transporte de órdenes/confirmaciones debe autenticar
al agente y fijar el box desde esa identidad; no se agregan rutas HTTP para esas
operaciones. Para archivos ya existe `POST /api/v1/internal/fragments`, con
credencial `Agent` vinculada al box; no admite JWT de profesionales. Su contrato
completo está en [API_CONTRACTS.md, sección 5](../../../API_CONTRACTS.md#5-ingesta-interna-de-fragmentos).

```python
# El adaptador invoca esta interfaz en el backend; no comparte SQL con el box.
from backend.apps.capture.ports import BoxAgentControl

control: BoxAgentControl = coordinator
for order in control.commands("box-3"):
    # Transmitir order al agente; ejecutar por command_id de forma idempotente.
    # Tras recibir la confirmación del inicio:
    if order.kind == "inicio":
        control.acknowledge("box-3", order.command_id, occurred_at=started_at)

control.heartbeat("box-3", session.session_id)
# El agente envía el archivo a POST /api/v1/internal/fragments.
# La API registra la secuencia y el trabajo juntos; no llamar además a
# accept_sequence() para ese mismo fragmento.

# Después de recibir una orden de detención y la respuesta del agente:
control.acknowledge(
    "box-3", stop_order.command_id, occurred_at=stopped_at, last_sequence=0,
)
```

| Operación | Contrato |
|---|---|
| `commands(box)` | Tupla de DTO `Command`, sin ORM ni contenido clínico. Registra cada entrega. |
| `acknowledge(box, command_id, ...)` | Confirma la ejecución de una orden previamente entregada; devuelve un DTO `Session`. |
| `accept_sequence(box, session_id, number, captured_at)` | `True` al aceptar; `False` para un reintento idéntico ya aceptado. |
| `heartbeat(box, session_id)` | Actualiza actividad; una sesión vencida se cierra sin revivirla. |
| `interrupted(box, session_id, error_code=...)` | Registra interrupción, marca fallida y genera detención de limpieza. |

Las órdenes llevan `command_id`, `session_id`, `box`, `kind` (`inicio` o
`detencion`) y ventana programada. Se reentregan con los mismos UUID hasta
confirmación; la entrega es **al menos una vez**. El agente debe deduplicar por
`command_id`, aplicar las órdenes exclusivamente a su `session_id` y rechazar
inicios fuera de su ventana. Una consulta no prueba que el agente ejecutó la
orden. Si el backend cae después de publicarla, el siguiente poll la repite.

`accept_sequence` conserva su contrato anterior para integraciones internas sin
archivo. La API de ingesta usa la misma regla de secuencia bajo la transacción
que crea `FragmentJob`. Un registro histórico creado solo por ese puerto no se
convierte en trabajo al reintentarlo por HTTP: devuelve
`SEQUENCE_ALREADY_REGISTERED`, sin reemplazarlo.

Las confirmaciones idénticas son idempotentes; las contradictorias se rechazan.
`occurred_at` es el instante real de ejecución con zona horaria, distinto del
instante de recepción. Si se omite, se usa el instante de recepción del backend;
se recomienda enviarlo para respuestas retrasadas. El inicio confirmado permite
`iniciada → activa`. Una respuesta tardía no reactiva sesiones finalizando o
fallidas. Una detención exitosa exige `last_sequence`, desde `0`, o `-1` si no
hubo secuencias. Los fallos usan `success=False` y un código técnico permitido;
nunca se aceptan mensajes de error libres.

Un fallo de detención deja la sesión fallida, conserva el intento en bitácora y
reentrega la misma orden. Una confirmación exitosa posterior puede reconocer la
limpieza; la sesión permanece fallida. Hasta confirmar esa limpieza se bloquean
nuevos inicios en el box. Las detenciones tienen prioridad en las entregas.

## Secuencias y cierre

Las secuencias aceptadas son consecutivas desde `0`. Un salto debe reintentarse
después de aceptar las anteriores. `captured_at` representa un instante de captura,
no la llegada al backend. Debe ser consciente de zona, no futuro, no anterior al
inicio real ni a la secuencia previa, y no posterior al fin programado, revocación
o detención confirmada. Se admiten secuencias retrasadas durante `finalizando`.

Una restricción SQL única `(session_id, number)` y el bloqueo transaccional de
sesión impiden duplicados y actualizaciones perdidas entre procesos. Repetir un
número con distinta fecha es conflicto. Un reintento idéntico no vuelve a generar
eventos ni efectos; devuelve `False`, incluso tras completar la sesión.

Solo se completa cuando existe confirmación exitosa de detención y se han
aceptado **todas** las secuencias hasta `last_sequence`. Ambas llegadas pueden
ocurrir en cualquier orden o concurrentemente. Se rechazan nuevas secuencias en
sesiones completadas o fallidas. No se invoca ningún analizador al aceptarlas.

## Ingesta HTTP y cola persistente

`POST /api/v1/internal/fragments` recibe multipart con `archivo`, `box`,
`session_id`, `secuencia`, `formato`, `checksum` y `captured_at`. Todos son
obligatorios. `captured_at` permite comprobar la ventana real de captura incluso
si el fragmento llega durante la finalización. Solo se admite WAV RIFF PCM mono
a 16 kHz y 16 bits, alineado con Speechmatics; se valida su estructura real,
tamaño y SHA-256. El nombre original y el MIME no se usan como evidencia.

`authentication.py` valida `Authorization: Agent <agent_id>.<secret>` antes de
leer audio. Admite el registro administrable y las identidades existentes de
`CAPTURE_AGENTS`, siempre ligadas a su box. La BD guarda solo la huella SHA-256;
las instalaciones nuevas obtienen su credencial mediante código temporal y
activación recuperable. La revocación administrativa corta conexiones activas y
cancela preparaciones. No necesita editar el entorno ni reiniciar el servidor.
Los JWT de profesionales no autorizan máquinas. Ver
[Gestión de PCs](../../../docs/GESTION-DE-PCS.md).

`uploads.py` limita los bytes mientras escribe el multipart a un temporal
privado y comprueba que la carga tenga su cierre completo. `storage.py` valida
el archivo y sincroniza sus bytes y publicación antes de aceptar. `ingestion.py`
registra la secuencia, contador, trabajo pendiente y eventos en una única
transacción SQL durable. La vista responde solo después del commit.

`FragmentJob.sequence` es uno a uno con `AcceptedSequence`, cuya clave única es
`(session_id, number)`. Un reintento idéntico devuelve 200 con el mismo `job_id`
y datos originales; uno nuevo devuelve 201. Otro checksum, formato, tamaño o
instante de captura para esa clave devuelve conflicto. Los reintentos no cambian
el trabajo aunque ya esté en procesamiento o la sesión haya cerrado. Una vez
confirmada `last_sequence`, se rechaza cualquier secuencia superior.

No hay transacción distribuida con el filesystem: el orden archivo → commit
SQL evita confirmar trabajos sin archivo aceptado. Una caída previa al commit
puede dejar un huérfano recuperable. Si el resultado del commit es incierto,
se conserva el archivo para no romper un trabajo ya persistido y se devuelve
error; el agente debe reintentar la misma clave y contenido.

La cola es SQL (`FragmentJob`) y sobrevive reinicios. La API crea únicamente
estado `pendiente`; el modelo contempla `procesando`, `completado` y `fallido`
para el consumidor `manage.py process_fragment_jobs`. El consumidor se ejecuta
separadamente, adquiere trabajos en orden y elimina el audio tras su finalización.
Un fallo previo de la misma sesión termina las secuencias siguientes con
`PREVIOUS_FRAGMENT_FAILED`, sin llamar proveedores, y aplica la misma limpieza.
La vista HTTP no ejecuta análisis, alertas ni notificaciones. Para operación continua
y recuperación de contexto, consultar el [runbook](../../../docs/OPERACION-SEPARADA.md).

## Configuración y limpieza

| Variable | Predeterminado / uso |
|---|---|
| `CAPTURE_AGENTS` | `{}`; objeto JSON de identidades a `{box, token_sha256}`. Detalle y restricciones en el contrato. |
| `CAPTURE_FRAGMENT_ROOT` | `.local/capture-fragments`; volumen persistente privado, fuera de estáticos/media. |
| `CAPTURE_FRAGMENT_MAX_BYTES` | `26214400` (25 MiB); archivo, incluyendo cabecera WAV. Cuerpo multipart limitado a este valor + 64 KiB. |
| `CAPTURE_ORPHAN_MAX_AGE_SECONDS` | `3600`; antigüedad mínima para eliminar huérfanos. |

En macOS/Linux el directorio es 0700 y los archivos 0600. En Windows la
privacidad depende de las ACL del directorio privado del usuario o servicio.
API y limpieza deben compartir base SQL y volumen local persistente. Se usan
los bloqueos compartidos/exclusivos de Django (`flock` en POSIX y `LockFileEx`
en Windows), sin dependencias adicionales. Los nombres de almacenamiento
son aleatorios; no incluyen nombres recibidos, sesiones ni contexto clínico.
Audio, transcripciones, checksums, rutas y secretos no aparecen en la bitácora.

El staging usa archivos `incoming-*.part`. Antes de crear el trabajo se hace
`fsync` del archivo, se cierra y se publica con el nombre definitivo: en POSIX
se sincroniza el directorio; en Windows se usa `MoveFileExW` con
`MOVEFILE_WRITE_THROUGH`. El lock de asignación protege el cambio de nombre
y la adquisición de la nueva lease. La limpieza cierra los handles antes de
borrar, manteniendo su lock global exclusivo, como requiere Windows.

El request elimina temporales en errores y al interrumpirse la carga. Ejecutar
al arrancar y periódicamente para recuperar archivos abandonados por caídas:

```sh
uv run python manage.py cleanup_capture_uploads
uv run python manage.py cleanup_capture_uploads --older-than-seconds 3600
```

`cleanup.py` solo elimina nombres gestionados y antiguos sin trabajo asociado.
Cada carga mantiene un lock exclusivo de archivo hasta terminar su aceptación;
la limpieza omite esos locks sin esperar, aun cuando la carga sea muy lenta.
El lock de asignación evita eliminar un archivo entre su creación y la toma
de su lease. No sigue enlaces simbólicos. Ante error SQL falla sin inferir que
el archivo no tiene trabajo. Conserva archivos de todos los estados de trabajo;
no implementa expiración de archivos aceptados. La salida contiene solo conteos.

## Recuperación y bitácora

Ejecutar una pasada al arrancar el coordinador y periódicamente (por ejemplo,
cada 15 segundos) mediante `coordinator.recover()` o el comando:

```sh
uv run python manage.py recover_capture_sessions
```

No inicia sesiones nuevas ni necesita cargar agenda. Valores por defecto:

| Límite | Valor | Resultado |
|---|---|---|
| Confirmación de inicio | 120 s desde autorización | Fallida: `AGENT_UNAVAILABLE` |
| Ausencia de actividad | 120 s desde heartbeat, confirmación o secuencia | Fallida: `SESSION_ABANDONED` |
| Finalización | 300 s desde solicitud de detención, aunque sigan heartbeats | Fallida: `SESSION_ABANDONED` o `FINAL_SEQUENCE_TIMEOUT` |

Se configuran con `start_timeout`, `heartbeat_timeout` y `finalization_timeout`
(objetos `timedelta`) en la composición; el comando acepta los mismos nombres
como `--start-timeout`, `--heartbeat-timeout`, `--finalization-timeout` en segundos.
La entrega de órdenes y las respuestas también verifican vencimientos para
evitar revivir sesiones si un tick se retrasa. Una caída del proceso se detecta
por estos plazos; no se presupone que reiniciar el backend detuvo al agente.

`CaptureEvent` conserva en SQL la bitácora del fin de autorización, creación, órdenes, entregas,
confirmaciones, secuencias aceptadas, finalización y fallos. Cada evento se guarda
en la misma transacción que el cambio y se emite a `psycode.audit` solo después
del commit. Un rollback elimina también el evento; un fallo del logger no pierde
la copia SQL. Esta bitácora técnica se consulta internamente por
`CaptureSession.events`; no modifica el endpoint MongoDB `/api/v1/audit-events`,
que sigue siendo la bitácora de alertas. Los errores son códigos de lista cerrada,
sin excepciones, audio, transcripciones, nombres, pacientes o payloads arbitrarios.

## Instalación y pruebas

```sh
uv run python manage.py migrate
uv run python manage.py test backend.apps.capture backend.apps.operational --settings=backend.config.test_settings --noinput
```

Las pruebas de concurrencia usan `TransactionTestCase`, barreras y conexiones SQL
independientes contra un archivo SQLite de pruebas; no simulan la persistencia.
La configuración existente usa `transaction_mode=IMMEDIATE` y timeout para
serializar escritores SQLite. También se bloquean filas con `select_for_update`
en motores que lo soporten. No se necesitan MongoDB, agentes ni credenciales.

Las pruebas de ingesta usan audio sintético y directorios temporales aislados.
Cubren autenticación y revocación, pertenencia/estado/ventanas de sesiones,
última secuencia, estructura/tamaño/formato/checksum, multipart truncado,
reintentos y conflictos concurrentes, rollback, commit de resultado incierto,
privacidad y limpieza concurrente. Una prueba termina abruptamente un proceso
para verificar la recuperación posterior de su temporal sin ejecutar finalizers.
Una prueba adicional ejecuta `check` y migraciones sin permitir importar `fcntl`.

## Fragmentos configurables y negociación

La migración `0021` añade `capture_chunk_config`, separado de `audio_profile`,
y `capture_chunk_negotiated`. Solo una autorización nueva toma un snapshot de
`OperationalConfiguration`: duración mínima 10 s, predeterminada 60 s y modo
`fixed`/`session`. Cambiar la configuración web no altera sesiones existentes.
Las sesiones anteriores a la migración conservan `{}` y el comportamiento legacy.

`commands()` resuelve `fixed` como `min(configured, max(10, ceil(window_seconds)))`
y `session` como `max(10, ceil(window_seconds))`, usando la ventana original,
sin reducir la duración por reconexiones o por el tiempo transcurrido.
El ASGI real es `backend.config.asgi:application`. Solo un hello con
`audio.chunk-config.v1` **y** `audio.v2` recibe esa capacidad en `ready`.
El campo entero opcional `audio_chunk_duration` aparece solo en `inicio`, tanto
en polling como en `sync`. La decisión de la primera entrega queda persistida:
una sesión entregada a un agente antiguo no se actualiza a mitad de captura.
Sin negociación el comando omite el campo y el agente conserva su perfil local;
no se impone el valor web ni se infiere una negociación desde el audio recibido.
Si una sesión ya negociada tiene un inicio pendiente y la conexión pierde alguna
de las capacidades requeridas, el servidor rechaza su entrega con
`CAPABILITIES_CHANGED` y cierra el WebSocket; no degrada el inicio a legacy ni
borra la negociación persistida. Las detenciones siguen entregándose sin el
campo a conexiones legacy. Las sesiones sin negociación conservan compatibilidad.

Para sesiones negociadas se exige temporal v2, exactamente los samples de la
duración solicitada y el solapamiento negociado: 0 en
`audio.chunk-config.v2`, 16000 samples (1 s) en v1. El perfil recibido
queda estable. Se admiten duraciones superiores a 600 s y archivos mayores de
25 MiB únicamente con negociación persistida. El límite exacto del archivo es
`duration * 32000 + 65536` bytes (PCM y margen de cabecera); se conservan checksum,
RIFF completo, formato PCM, secuencias, continuidad, ventana efectiva, ACK de
inicio, recepción y confirmación durable. El límite legacy de almacenamiento
configurado y el máximo temporal de 600 s siguen vigentes sin negociación.

El multipart no garantiza que `session_id` preceda al WAV. Antes de conocerlo,
el parser usa como máximo la mayor cota de las sesiones negociadas del **box
autenticado**, solo en endpoints v2. Tras parsear, la ingesta aplica la cota de
la sesión exacta antes de publicar el archivo. Esto puede permitir escribir un
temporal mayor que el límite legacy cuando ese mismo box tiene otra sesión
negociada; no permite aceptarlo ni ampliar sus límites de formato o tiempo.
El parser limita bytes efectivos, no solo Content-Length, y limpia temporales
al fallar. Una carga usa archivo temporal de parser más copia de staging.

### Proxy, disco y análisis

`deployment/nginx-capture.conf` y `deployment/vps/nginx.conf` mantienen `26m`
para el resto del servidor. La excepción exacta `/api/v2/internal/fragments`
usa `client_max_body_size 3g` y `proxy_request_buffering off`; las cotas de capture
se aplican durante parseo y almacenamiento. El alias v1 `/fragments/v2` mantiene
el límite del proxy; para sesiones grandes usar la ruta canónica v2.
No se despliega automáticamente ninguna plantilla.

**ASGI de Django primero recibe el cuerpo completo en un spool, antes de ejecutar
la autenticación y el parser.** Desactivar buffering de Nginx no elimina ese spool.
El límite finito de Nginx acota cada petición antes de la aplicación a 3 GiB,
suficiente para una ventana clínica de hasta 25 h (cambio horario incluido),
con margen para WAV y multipart.
Ajustar ese límite a la máxima ventana institucional. El rechazo del proxy no es
un ACK: el agente debe conservar el WAV pendiente e intervenir/reintentar sin
regenerar ni renumerar audio. Se requieren capacidad de disco, cuotas/monitorización
y control de concurrencia; el acceso directo a ASGI debe quedar restringido al proxy. Dimensionar el temporal ASGI, el directorio
privado de capture y el espacio de staging; 10 min PCM son 19,2 MB y 1 hora,
115,2 MB, sin contar copias ni multipart. Permanecen los timeouts de proxy de 90 s
para inactividad de lectura/escritura. No se verificaron cargas reales a través
de Nginx ni cuotas del servidor.

El análisis mantiene offsets locales del WAV separados del origen de sesión.
Speechmatics puede cargar PCM y WAV completos en memoria; dimensionar también RAM
y los plazos/límites del proveedor para sesiones largas. Las nuevas sesiones operativas pasan `analysis_unit=fragment` al trabajador:
JEV evalúa el bloque completo en una solicitud y conserva un único resultado.
Las intervenciones de 15 s sirven para preservar turnos, no disparan llamadas
individuales en este modo. Los checkpoints legacy en curso se conservan. Un
exceso de contexto requiere revisión sin truncar texto ni eliminar audio. No se cambian estos límites ni se envía
audio a servicios externos durante las pruebas.
