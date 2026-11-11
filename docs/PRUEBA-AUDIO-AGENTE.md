# Diagnóstico de audio de Psycode Agent

El asistente Windows 1.5.0 reproduce un clip ficticio en fragmentos de audio.
El servidor utiliza su cola, transcriptor y clasificador para mostrar el
resultado en el asistente. No se requiere una cita ni se emiten órdenes a OBS.

Desplegar juntos la API, la migración `capture.0019_audio_test` y el worker de
fragmentos. El diagnóstico usa la configuración existente de Speechmatics,
JEV y almacenamiento privado. El audio sintético sigue la retención del
worker. Los resultados se consultan con la credencial individual del PC.

## Contrato HTTP v1

Prefijo `/api/v1/internal/audio-tests/<uuid>`. Todas las solicitudes usan
`Authorization: Agent <credencial>` por HTTPS.

- `PUT` con JSON `scenario` (`neutral` o `alerta`) y `samples` (1 a 960 000).
  El UUID lo elige el cliente. Repetir el mismo inicio devuelve la prueba
  existente con su fecha original. La autorización dura cinco minutos para
  nuevas cargas.
- `POST /fragments` con el multipart y recibo de audio v2. El `session_id`
  es el UUID de la prueba, `captured_at` es `started_at` más el offset del
  fragmento y el PCM es mono de 16 bits a 16 kHz. Enviar 160 000 muestras por
  fragmento con 16 000 de solapamiento, salvo el tramo final.
- `GET` devuelve el estado, cantidades de fragmentos y alertas de prueba. El
  objeto `data` contiene `test_id`, `box`, `scenario`, `samples`,
  `started_at`, `state`, `expected`, `accepted`, `analyzed`,
  `indeterminate` y `alerts`. Cada alerta incluye `id`, `category`,
  `severity`, `start` y `end`. Los offsets de alerta se expresan en
  segundos desde el comienzo del clip.

Los estados son `receiving`, `analyzing`, `completed`, `failed` y
`expired`. El escenario expresa el resultado esperado y no determina la
clasificación. Para esta ruta se evalúan las voces identificadas del clip
como papeles de paciente simulado. Las señales del análisis se devuelven
como alertas de prueba sin textos, sin escrituras en alertas clínicas y sin
notificaciones.
