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
En los clips de diagnóstico con varias voces, JEV identifica al paciente
simulado antes de aceptar el turno seleccionado como evidencia. Para los
bloques clínicos, `bloque-signals-4` incorporó turnos con hablante sin
confirmar. El texto debe expresar explícitamente la señal en primera persona en
un solo turno. Las peticiones de cita o simulación en el turno previo excluyen
esa respuesta como evidencia. Se requiere que JEV seleccione el turno con soporte de al menos
`.75`, confirme el contexto afirmativo y alcance el umbral operativo de la señal.
La alerta resultante queda pendiente de revisión y señala la incertidumbre del
hablante en su trazabilidad.

`bloque-signals-5` verifica individualmente hasta 12 pares de turno y nivel en
la misma solicitud. Los candidatos restantes se evalúan en grupos. La
aplicación conserva el contexto afirmativo y los dos umbrales para registrar
la alerta. Si falta evidencia verificada, `JEV_EVIDENCE_REJECTED` indica que
JEV la descartó con suficiente confianza y `JEV_EVIDENCE_UNCERTAIN` indica que
la elección no alcanzó el soporte requerido. Al cerrar la sesión se conservan
solo esos códigos en `FragmentJob.checkpoint.analysis_error_codes`.

En `bloque-signals-6`, cada candidato con hablante sin confirmar tiene una pregunta
individual, incluso cuando hay más de doce candidatos. Las hipótesis se leen de
la matriz extraída del Excel. Cada expresión distinta verificada conserva su
categoría más específica y su prioridad de revisión. El detalle incluye intervalo,
puntaje Noul del bloque, umbral y versión. Los resultados indeterminados conservan
el motivo técnico permitido, incluido `JEV_BELOW_THRESHOLD` cuando una expresión
explícita queda por debajo del corte.

La cola durable puede procesar un bloque mientras otro queda en revisión. Los
trabajos por intervención conservan su dependencia del contexto anterior. Se
reutilizan las respuestas JEV guardadas con las reglas de su versión y los
envíos inciertos requieren revisión. Los trabajos completados conservan su resultado.

`JEV_BLOCK_MAX_CHARS` limita el estado enviado a 262144 caracteres por defecto.
Ante un rechazo explícito por contexto, el cliente directo de Typesafe prueba
una vez el modo de contexto largo con el mismo bloque. Si el límite persiste,
el trabajo queda en revisión con `JEV_CONTEXT_LIMIT` y conserva el WAV según la
política de retención. Tras ajustar el límite aplicable, `process_fragment_jobs
--resume-job <uuid>` vuelve a poner el trabajo en cola con la transcripción
preparada. [Límites y contexto largo de Typesafe](https://docs.typesafe.ai/models#long-context).
