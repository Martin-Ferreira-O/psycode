# Análisis interno

Integra Speechmatics Batch y JEV mediante puertos propios, sin endpoints nuevos. La composición está en `backend.config.composition.analysis_worker`; el punto de entrada del trabajador es `AnalysisService.process(Fragment, roles=...)`.

- `domain.py`: entrada PCM y salida tipada 1.0.
- `ports.py`: transcriptor, analizador, bitácora y reserva de fragmentos.
- `clients.py`, `providers/`: adaptadores HTTP, preguntas versionadas y validación.
- `rules.py`, `matrix.json`, `privacy.py`: reglas seleccionadas del origen y redacción.
- `services.py`: contexto por sesión y registro interno de alertas.
- `ledger.py`: rechazo durable de duplicados y secuencias incorrectas.
- `audit.py`: fallos técnicos en la bitácora existente.

Ver [implementación y pruebas](../../../docs/INTEGRACION-SPEECHMATICS-JEV.md) y [contrato 1.0](../../../docs/analysis/OUTPUT-1.0.md). El módulo no arranca procesos, realiza llamadas ni consume créditos al importarse o construirse.

`Fragment.analysis_unit` conserva `utterance` por defecto para el flujo legacy.
Con `fragment`, el WAV se transcribe una vez y se envía una única petición JEV
con el bloque completo redactado, ordenado y anotado con tiempos de sesión,
hablantes, roles y atribución. No usa el historial ni el recorte legacy de
12000 caracteres. Las preguntas `bloque-signals-1` conservan las claves de salida
1.0 y clasifican el bloque de forma agregada. Se emite como máximo una señal y
una alerta: la mayor severidad con evidencia local verificada de una voz
confirmada como paciente. Las preguntas, negaciones, citas y voces profesionales,
desconocidas o superpuestas no se reasignan a otro hablante. Sin evidencia
verificable se conserva un resultado indeterminado. Solo en el diagnóstico
sintético autorizado (`audio_test=True`), las voces con atribución `assigned`
sin rol explícito reciben el rol ficticio `patient`; nunca en sesiones clínicas.

`Settings.jev_block_max_chars` / `JEV_BLOCK_MAX_CHARS` limita el texto anotado
a 262144 caracteres por defecto. Es una cota operacional de la aplicación,
sin equivalencia caracteres/tokens ni garantía de aceptación del proveedor.
[Typesafe](https://docs.typesafe.ai/models) documenta para JEV 1.13 límites
ordinarios de 64k tokens por petición y 32k por pregunta; su opción long context
no se activa. [OpenRouter](https://openrouter.ai/typesafe/jev-1.13) publica una
ventana de 262144 tokens. Un exceso local o rechazo por contexto (incluido 422
identificado como tal) produce `JEV_CONTEXT_LIMIT`; con checkpoint se eleva
`AnalysisRetry` para revisión. No se trunca, subdivide ni elimina audio.

El llamador debe pasar `analysis_unit` desde el snapshot de sesión y omitir el
requisito de contexto del bloque anterior para `fragment`. El checkpoint propio
del bloque conserva el request_id; los envíos inciertos nunca se repiten. La
respuesta y el resultado se persisten antes de registrar alertas. Tras persistir
el resultado se retira el texto preparado del checkpoint. `resume` devuelve
`analysis_unit=fragment` y `block_result` con estado, decisiones, errores y versión
de preguntas, sin duplicar la transcripción, para conservar el resultado al
confirmar el trabajo. La política de retención corresponde al consumidor.

## Unidad de análisis configurable

Las sesiones operativas nuevas usan `Fragment.analysis_unit="fragment"`:
Speechmatics transcribe el WAV y JEV evalúa su transcripción completa en una
solicitud. Los turnos y roles se conservan como anotaciones; no provocan llamadas
adicionales por cada intervención de 15 segundos. El resultado conjunto y sus
puntajes se guardan en `FragmentJob.checkpoint.block_result`, y se genera como
máximo una alerta con la evidencia verificada de mayor severidad del bloque.
No se atribuyen roles de paciente a voces clínicas desconocidas. Solo los clips
ficticios del diagnóstico mantienen su convención explícita de paciente simulado.

Los checkpoints ya iniciados por intervención conservan su unidad anterior.
Una respuesta JEV guardada se reutiliza al recuperar la entrega de la alerta;
un envío incierto requiere revisión y no se repite automáticamente.
`JEV_BLOCK_MAX_CHARS` limita la carga de aplicación (262144 caracteres inicialmente,
no tokens). Los límites del proveedor son independientes: un rechazo por contexto
produce `JEV_CONTEXT_LIMIT` y revisión, conservando el WAV; nunca se trunca el
texto ni se sustituye el análisis conjunto por múltiples análisis de segundos.
