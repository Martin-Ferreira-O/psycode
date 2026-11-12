# Diagnóstico de audio de Psycode Agent

El asistente Windows 1.5.0 reproduce un clip ficticio en fragmentos de audio.
El servidor utiliza su cola, transcriptor y clasificador para mostrar el
resultado en el asistente. No se requiere una cita ni se emiten órdenes a OBS.

Desplegar juntos la API, la migración `capture.0019_audio_test` y el worker de
fragmentos. El diagnóstico usa la configuración existente de Speechmatics,
JEV y almacenamiento privado. El audio sintético sigue la retención del
worker. Los resultados se consultan con la credencial individual del PC.
La limpieza del contexto conserva el resumen de cada alerta de prueba
para que el asistente pueda mostrar el mismo resultado después del análisis.

## Contrato HTTP v1

Prefijo `/api/v1/internal/audio-tests/<uuid>`. Todas las solicitudes usan
`Authorization: Agent <credencial>` por HTTPS.

- `PUT` con JSON `scenario` (`neutral` o `alerta`) y `samples` (1 a 9 600 000).
  El UUID lo elige el cliente. Repetir el mismo inicio devuelve la prueba
  existente con su fecha original. La autorización vence como mínimo cinco
  minutos después del inicio y dos minutos después del final previsto.
- `DELETE` cierra la recepción para ese PC y devuelve el estado. Es
  idempotente. Los fragmentos ya aceptados siguen en análisis y los
  recibos previos se pueden volver a consultar mediante reintentos. El
  reproductor abre otra prueba cuando salta a un punto distinto.
- `POST /fragments` con el multipart y recibo de audio v2. El `session_id`
  es el UUID de la prueba, `captured_at` es `started_at` más el offset del
  fragmento y el PCM es mono de 16 bits a 16 kHz. Enviar 160 000 muestras por
  fragmento con 16 000 de solapamiento, salvo el tramo final, en modo legacy.
- `GET` devuelve el estado, cantidades de fragmentos y alertas de prueba. El
  objeto `data` contiene `test_id`, `box`, `scenario`, `samples`,
  `started_at`, `state`, `expected`, `accepted`, `analyzed`,
  `indeterminate` y `alerts`. Cada alerta incluye `id`, `category`,
  `severity`, `start` y `end`. Los offsets de alerta se expresan en
  segundos desde el comienzo del clip.
- `fragment_details=1` añade `data.fragments` a PUT, GET y DELETE. Devuelve
  cada fragmento aceptado con su secuencia, intervalo en muestras, estado y,
  cuando está disponible, un motivo técnico. El detalle sigue disponible
  tras la limpieza. El esquema es `audio-test-fragment-details-v1.schema.json`.

Los estados son `receiving`, `analyzing`, `completed`, `failed`,
`expired` y `stopped`. El escenario expresa el resultado esperado y no determina la
clasificación. Para esta ruta se evalúan las voces identificadas del clip
como papeles de paciente simulado. Las señales del análisis se devuelven
al asistente como alertas de prueba sin textos.

## Mostrar la detección en la demo

1. En el agente, abre **Probar conexión con audio** y elige **Con alerta esperada**.
2. En la web, abre **Registro de evaluaciones** y pulsa **Actualizar** tras la
   detección. La fila aparece como **Alerta de prueba** y **Pendiente**. Puedes
   guardar una evaluación desde su detalle.
3. Si el servidor tiene `NOTIFICATIONS_ENABLED=true` y el correo configurado,
   usa los destinatarios de **Configuración operativa** y envía un mensaje con
   el asunto **[PRUEBA] Alerta simulada**. El cuerpo indica que la detección es
   simulada y que no requiere intervención clínica.

El historial y los indicadores clínicos del Dashboard excluyen las alertas de
prueba. El clip **Sin alerta esperada** solo genera un registro o correo si el análisis
detecta una señal. Para mostrar el flujo completo, inicia una nueva prueba
después de actualizar la web y el worker de fragmentos.

## Perfil operativo negociado v1

El cliente solicita `PUT <prefijo>?fragment_profile_version=1`, conservando
exactamente el JSON `scenario`, `samples`. Sin query se mantiene el perfil legacy
de 10 s/1 s. Valores distintos de `1`, vacíos o repetidos devuelven 400.
Cambiar entre legacy y v1 para el mismo UUID devuelve 409; cambiar escenario o
cantidad de muestras también. Requiere servidor y agente que implementen esta negociación.

Al crear v1 se congela la configuración operativa en `capture_chunk_config` y el
perfil efectivo en `audio_profile`. La duración es, en modo fijo,
`min(configuración, max(10, ceil(samples / 16000)))`; en modo sesión es
`max(10, ceil(samples / 16000))`. No se activa `capture_chunk_negotiated`:
el diagnóstico tiene su propia negociación, separada de las órdenes de captura.
Los reintentos conservan perfil, fecha, secuencias y bytes aunque cambie el ajuste.

Todas las respuestas de estado de una prueba v1 (PUT, GET y DELETE) incluyen
`fragment_profile_version: 1` y `audio_chunk_duration` entero en segundos.
El solapamiento sigue siendo 1 s. `expected` deriva del perfil: un clip de 600 s
produce 1 fragmento con duración 600, 11 con duración 60 (cola de 10 s), y 67
sin negociación. El último tramo contiene audio nuevo. Al saltar en el clip se
crea otro UUID con las muestras restantes; sus offsets empiezan desde cero.

El contrato central está en
[`audio-test-profile-v1.schema.json`](../contracts/audio-test-profile-v1.schema.json),
con hash SHA-256 de sus bytes en `contracts/manifest.json`. La definición `query`
representa la query decodificada y `response` el objeto `data`, sin el envelope.
El agente debe incorporar este contrato y solicitar v1 para aplicar el ajuste web.

Verificación local sin proveedores, OBS ni base institucional:

```sh
PSYCODE_TEST_SQLITE_PATH=/tmp/psycode-audiotest-profile-test.sqlite3 uv run --no-sync python manage.py test backend.apps.capture --settings=backend.config.test_settings --noinput
```
