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
  fragmento con 16 000 de solapamiento, salvo el tramo final.
- `GET` devuelve el estado, cantidades de fragmentos y alertas de prueba. El
  objeto `data` contiene `test_id`, `box`, `scenario`, `samples`,
  `started_at`, `state`, `expected`, `accepted`, `analyzed`,
  `indeterminate` y `alerts`. Cada alerta incluye `id`, `category`,
  `severity`, `start` y `end`. Los offsets de alerta se expresan en
  segundos desde el comienzo del clip.

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
