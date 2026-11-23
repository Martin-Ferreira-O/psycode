# Contrato interno de salida 1.0

Tipos ejecutables: [`domain.py`](../../backend/apps/analysis/domain.py). No es una ruta HTTP pública. El trabajador devuelve `AnalysisResult`; `to_dict()` permite serializarlo con `json.dumps`. El esquema JSON está en [`output-1.0.schema.json`](output-1.0.schema.json). Las modificaciones incompatibles requieren otra versión.

| Campo | Tipo y significado |
| --- | --- |
| `contract_version` | Literal `1.0`. |
| `questions_version` | `habla-signals-1` por intervención, `bloque-signals-1` y `bloque-signals-2` en bloques históricos, `bloque-signals-3` con evidencia por turno, `bloque-signals-4` para revisión clínica con hablante sin confirmar y `bloque-signals-5` con verificación individual de candidatos. Todas usan una pregunta Choice de contexto y ocho Noul. |
| `session_id`, `sequence` | UUID canónico y secuencia entera desde 0. Solo uso interno. |
| `state` | `senal`, `sin_riesgo` o `indeterminado`. |
| `transcription` | `null` si falló Speechmatics; en otro caso `{text, words, cleanup}`. |
| `transcription.words[]` | `{text, start, end, speaker}`. Tiempos en segundos absolutos dentro de la sesión. `speaker` puede ser `null`. |
| `transcription.cleanup` | `deleted` o `delete_pending`. El segundo vuelve el resultado indeterminado. |
| `signals[]` | `{category_id, matrix_level, severity, excerpt, start, end, speaker}`. Solo `severity` 1–3 entra a alertas. `excerpt` es el texto redactado relacionado. `speaker` es `null` cuando el hablante clínico queda sin confirmar. |
| `decisions[]` | `{model, context, values, input_tokens, output_tokens, evidence_turns?, review_verdicts?}`. Ocho valores Noul validados. `evidence_turns` contiene IDs de turnos aceptados por nivel. `review_verdicts` guarda solo `confirmed`, `rejected` o `uncertain` por nivel e ID local. |
| `error_codes[]` | Códigos técnicos o de abstención; nunca excepciones libres ni cuerpos HTTP. |

`sin_riesgo` significa únicamente que un fragmento evaluable no produjo señales según estas reglas experimentales. `senal` requiere borrado remoto confirmado, audio sin solapamiento ambiguo y contexto propio afirmativo. Por intervención se requiere un rol `patient` confirmado. En bloques clínicos también se admite evidencia explícita en primera persona con hablante sin confirmar si JEV localiza el mismo turno y nivel con soporte de al menos `.75` y el puntaje Noul supera el umbral operativo.

Los fallos, resultados parciales, texto vacío, contexto desconocido o señales que no superan las puertas de evidencia son `indeterminado`. Pueden conservar candidatos en `signals`. El alta de alertas exige estado `senal`. Una negación, cita, pregunta o referencia histórica se conserva como contexto.

La conversión existente en Psycode ([MONGODB.md](../MONGODB.md)) agrupa niveles de matriz 1–2 → severidad 1, 3–4 → 2 y 5–7 → 3. El nivel 0 no produce alerta. No se añade una escala clínica nueva. El corte experimental `.55`, las preguntas y las puertas léxicas se adaptan del origen.

`register_signals(fragment, result)` llama a `AlertsService.register_alert`. Usa UUIDv5 determinista por sesión, secuencia, intervalo y categoría. El índice único de `alerts.alerta_id` evita duplicados incluso tras reiniciar el trabajador. `descripcion` recibe el fragmento redactado normalizado y limitado a 500 caracteres. La alerta con hablante sin confirmar usa el origen `analysis.speechmatics-jev/unattributed/1.0`. La notificación indica la incertidumbre sin incluir el texto de la conversación ni una identidad.

La salida puede contener transcripción sensible: consumirla en memoria, sin imprimirla, registrarla en logs ni guardarla como historial. La bitácora recibe exclusivamente códigos permitidos. El filtro de redacción no identifica todos los nombres o direcciones desconocidos: debe configurarse la lista local antes de un eventual uso autorizado con datos reales.
