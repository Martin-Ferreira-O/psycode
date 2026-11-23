# Contratos de control 1.0 y audio v2

Fuente canónica: `contracts/` del servidor. El agente copia la versión soportada;
`manifest.json` fija hashes y la revisión de origen. Las pruebas verifican esos
hashes y ejemplos sintéticos. Al cambiar el contrato, actualizar ambas copias y
la matriz de compatibilidad, sin imports entre paquetes.

## Control

`wss://servidor/ws/v1/agents`, iniciado por el agente. Autenticación de handshake:
`Authorization: Agent <agent_id>.<secret>`. No se admiten credenciales en query ni
JWT profesionales. El box se deriva de la identidad; se rechaza un box ajeno.
Un lease SQL por box sustituye la conexión anterior al negociar una nueva. Cada
operación comprueba propiedad bajo bloqueo. No requiere Redis ni memoria compartida.

Sobre JSON con `protocol_version`, UUID `message_id`, `type`, fecha `sent_at` con
zona, objeto `payload` y UUID `correlation_id` en respuestas a solicitudes.
Límite 65536 bytes, colas de frames 16, solicitudes concurrentes 32 y órdenes
pendientes locales 64. La entrega SQL se revisa cada 1 s; las detenciones tienen
prioridad. El cliente mantiene un lector independiente y detiene FFmpeg al recibir
un corte de la sesión correcta, antes de esperar confirmaciones o drenajes.

Mensajes y payloads están definidos en el [schema](../contracts/control-v1.schema.json):
`hello/ready`, `sync/state`, `command`, `command_ack/command_receipt`,
`heartbeat/heartbeat_receipt`, `interrupted/interruption_receipt`, `status`, `error`.
La recolección de agenda se asigna por HTTP; no existe un tercer kind de captura.
`inicio` usa la ventana autorizada; en `detencion`, `scheduled_end` es el mínimo
entre fin original y revocación central. Esto permite recortar el último WAV con
el instante de corte central. `sync` no autoriza ni confirma actividad de captura.

La capacidad negociada `audio.chunk-config.v2` (junto con `audio.v2`) permite
`audio_chunk_duration` y `audio_chunk_overlap=0` en `inicio`; v1 conserva solapamiento de 1 s. Se congela por sesión; predeterminado
60 s, mínimo 10 s y opción sesión completa. Sin negociación se omite el campo.
[Operación, despliegue y límites](FRAGMENTOS-CONFIGURABLES.md).

La respuesta `command_receipt` sale tras commit. El journal separa preparación,
ejecución física y confirmación; un outbox adicional conserva los ACK incluso
si ya no hay reentrega SQL. El reenvío conserva el contenido. La reconexión
sincroniza; nunca reinicia OBS a ciegas. Un journal inconcluso requiere recuperación
explícita. El reloj local se compara con el del servidor (máximo 30 s por defecto)
y el plazo de captura usa reloj monotónico. El watchdog funciona aunque un ACK
esté bloqueado. El primer audio real de FFmpeg se espera antes del ACK de inicio;
los uploads esperan confirmación central.

Códigos de sesión conservados: `AGENT_START_FAILED`, `AGENT_STOP_FAILED`,
`AGENT_INTERRUPTED`, `AGENT_UNAVAILABLE`, `SESSION_ABANDONED`, `FINAL_SEQUENCE_TIMEOUT`.
No enviar códigos de transporte en esos campos. Errores operativos:
`PROTOCOL_INCOMPATIBLE` (cierre 4406), `CONNECTION_REPLACED` (4409),
`INVALID_MESSAGE` (4409), `BOX_FORBIDDEN`, `COMMAND_NOT_FOUND`, `CLOCK_SKEW`,
`CONTROL_DISCONNECTED`, `CONTROL_RECEIPT_TIMEOUT`, `CONTROL_QUEUE_FULL`,
`CONTROL_RETRIES_EXHAUSTED`, `RECOVERY_REQUIRED`, `DISK_LOW`, `UPLOAD_INTERVENTION`,
`SMILE_UNAVAILABLE`, `CAPABILITIES_CHANGED`. Credencial inválida se rechaza antes de aceptar el handshake
(4401 a nivel ASGI; Uvicorn responde 403 HTTP si aún no hubo upgrade).
Se transmite solo el código, correlación y recuperabilidad, sin excepción libre.

## Audio

`POST /api/v2/internal/fragments` recibe WAV RIFF PCM mono de 16 kHz y 16 bits.
El agente publica siempre los metadatos v2 y mantiene el perfil durante toda la
sesión. El límite por defecto es 25 MiB. Las sesiones con duración negociada
usan una cota calculada desde la duración autorizada, además del límite del proxy.

El multipart exige seis campos temporales enteros: `session_start_sample`,
`session_end_sample` (exclusivo), `new_audio_start_sample`, `sample_rate`,
`chunk_samples`, `overlap_samples`. Perfil v2 operativo: 960000/0 muestras (60 s sin solapamiento).
Ejemplo compatible configurando 10 s/1 s: `[0,160000)` nuevo desde 0; `[144000,304000)` nuevo desde 160000;
`[288000,448000)` nuevo desde 304000. El último puede ser parcial, pero debe
contener audio nuevo. No hay secuencias posteriores a un parcial final.

`captured_at` es la referencia UTC del primer bloque válido de audio y se desplaza
por muestras. No se afirma precisión PTS del streaming. El servidor comprueba
muestras WAV, continuidad, perfil, timestamps (tolerancia de una muestra), identidad
y fin completo contra la autorización/corte, con tolerancia técnica máxima de
0.1 s. Datos temporales distintos en un reintento generan conflicto. Los bytes,
checksum, fecha y sesión no cambian tras guardar el manifiesto.

La orden de corte reduce el límite local antes de finalizar el parcial. FFmpeg
observa stop cada 0.1 s; terminate/kill tiene plazos de 2 s. Los RPC de OBS tienen
su propio timeout de 5 s y espera de salidas de 10 s: la cota física exacta en
hardware institucional debe validarse. Un fragmento ya cerrado antes de conocer
una revocación remota no se reescribe: si cruza el corte central se rechaza y se
conserva para intervención. No se amplía la autorización para admitirlo. Esta
carrera de latencia necesita revisión durante la prueba institucional.

En análisis, `start/end/context_start` continúan siendo offsets locales de archivo;
`session_origin_sample` normaliza palabras a tiempo de sesión por separado. Se usa
el solapamiento como contexto. Una frase pertenece al intervalo nuevo que contiene
su punto medio. Evidencia de igual texto/categoría con intervalos temporales
solapados no crea otra alerta; una ocurrencia posterior no solapada sí es distinta.
La deduplicación no depende solo del texto. No se infieren hablantes ni cambian
criterios clínicos. La segmentación/duración real de frases en cortes sigue sujeta
a validación con el proveedor y audio autorizado; las pruebas usan transcripciones
sintéticas, incluidas frases que cruzan el corte.

Recepción 201 y reintento idéntico 200 significan aceptación durable, no análisis
terminado. Antes de borrar, el agente comprueba identidad, secuencia, tamaño,
formato y checksum de la confirmación. Reintentos agotados, 401/403, conflicto,
archivo inválido o sesión cerrada conservan audio y requieren intervención; no se
renumeran ni trasladan a otra sesión. `last_sequence` es la última generada, incluso
pendiente; vale -1 sin audio. El orden de llegada de ACK y uploads puede variar.


## Smile nativo reutilizado

`format_version=smile.json.v1` transporta el array JSON del extractor entregado,
con su [schema](../contracts/smile-native-v1.schema.json). No se convierte a XLSX.
Se conserva `smile.excel.v1` para compatibilidad. La respuesta de asignación de
recolección informa formatos y alcance; control anuncia `agenda.smile-json.v1`.
La CLI incluida consulta solo los boxes de esa asignación y un día explícito.
El servidor verifica fecha, ID interno de box (3–7 → 8–12), IDs de cita únicos
por box y estados reconocidos por las reglas de ocupación actuales. No interpreta
`codigo_estado` como nueva autorización ni usa un ID de cita como ID de paciente.
