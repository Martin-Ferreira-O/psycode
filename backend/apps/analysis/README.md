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

## Unidad de análisis configurable

Speechmatics transcribe en español con diarización por voz y vocabulario de
psicología. El modelo `enhanced` usa además el dominio `medical`. En audio mono,
las etiquetas de diarización identifican voces dentro del trabajo Batch.
[Configuración de Speechmatics Batch](https://docs.speechmatics.com/speech-to-text/batch/input).

Las sesiones operativas nuevas usan `Fragment.analysis_unit="fragment"`. JEV
recibe el diálogo completo redactado, con turnos cronológicos y alias locales
de voz. Los tiempos se conservan en el trabajador para verificar evidencia.
`bloque-signals-3` pide a JEV identificar el turno que contiene la evidencia para
los niveles 1 y 2 en la misma solicitud. Esto permite verificar afirmaciones
indirectas que se entienden por el diálogo. El trabajador comprueba la atribución
del turno y conserva los puntajes en `FragmentJob.checkpoint.block_result`.
Las alertas clínicas requieren un rol de paciente confirmado. En los clips de
diagnóstico con varias voces, JEV identifica al paciente simulado antes de
aceptar el turno seleccionado como evidencia.

La cola durable puede procesar un bloque mientras otro queda en revisión. Los
trabajos por intervención conservan su dependencia del contexto anterior. Se
reutilizan las respuestas JEV guardadas y los envíos inciertos requieren revisión.

`JEV_BLOCK_MAX_CHARS` limita el estado enviado a 262144 caracteres por defecto.
Ante un rechazo explícito por contexto, el cliente directo de Typesafe prueba
una vez el modo de contexto largo con el mismo bloque. Si el límite persiste,
el trabajo queda en revisión con `JEV_CONTEXT_LIMIT` y conserva el WAV según la
política de retención. Tras ajustar el límite aplicable, `process_fragment_jobs
--resume-job <uuid>` vuelve a poner el trabajo en cola con la transcripción
preparada. [Límites y contexto largo de Typesafe](https://docs.typesafe.ai/models#long-context).
