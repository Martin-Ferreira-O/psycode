# Contrato interno de salida 1.0

Tipos ejecutables: [`domain.py`](../../backend/apps/analysis/domain.py). No es una ruta HTTP pública. El trabajador devuelve `AnalysisResult`; `to_dict()` permite serializarlo con `json.dumps`. El esquema JSON está en [`output-1.0.schema.json`](output-1.0.schema.json). Las modificaciones incompatibles requieren otra versión.

| Campo | Tipo y significado |
| --- | --- |
| `contract_version` | Literal `1.0`. |
| `questions_version` | `habla-signals-1`: Choice de contexto y ocho preguntas Noul del origen. |
| `session_id`, `sequence` | UUID canónico y secuencia entera desde 0. Solo uso interno. |
| `state` | `senal`, `sin_riesgo` o `indeterminado`. |
| `transcription` | `null` si falló Speechmatics; en otro caso `{text, words, cleanup}`. |
| `transcription.words[]` | `{text, start, end, speaker}`. Tiempos en segundos absolutos dentro de la sesión. `speaker` puede ser `null`. |
| `transcription.cleanup` | `deleted` o `delete_pending`. El segundo vuelve el resultado indeterminado. |
| `signals[]` | `{category_id, matrix_level, severity, excerpt, start, end, speaker}`. Solo `severity` 1–3 entra a alertas. `excerpt` es el texto redactado relacionado. |
| `decisions[]` | `{model, context, values, input_tokens, output_tokens}`. Ocho valores Noul validados; no son probabilidades clínicas. |
| `error_codes[]` | Códigos técnicos o de abstención; nunca excepciones libres ni cuerpos HTTP. |

`sin_riesgo` significa únicamente que un fragmento evaluable no produjo señales según estas reglas experimentales. No demuestra ausencia de riesgo clínico. `senal` requiere todas las intervenciones evaluadas, borrado remoto confirmado, atribución de voz no superpuesta, rol `patient` confirmado por el llamador interno y contexto propio afirmativo. La diarización no identifica al paciente.

Los fallos, resultados parciales, texto vacío, atribución/contexto desconocidos o señales que no superan las puertas de evidencia son `indeterminado`. Pueden conservar candidatos en `signals`, pero no registran alertas. Una negación, cita, pregunta o referencia histórica se conserva para revisión; no se convierte automáticamente en señal propia afirmativa.

La conversión existente en Psycode ([MONGODB.md](../MONGODB.md)) agrupa niveles de matriz 1–2 → severidad 1, 3–4 → 2 y 5–7 → 3. El nivel 0 no produce alerta. No se añade una escala clínica nueva. El corte experimental `.55`, las preguntas y las puertas léxicas se adaptan del origen.

`register_signals(fragment, result)` llama exclusivamente a `AlertsService.register_alert`. Usa UUIDv5 determinista por sesión, secuencia, intervalo y categoría; el índice único de `alerts.alerta_id` evita duplicados incluso tras reiniciar el trabajador. `descripcion` recibe el fragmento redactado normalizado, limitado a los 500 caracteres que admite el servicio existente. No se almacena el resto de la conversación en MongoDB ni se notifica.

La salida puede contener transcripción sensible: consumirla en memoria, sin imprimirla, registrarla en logs ni guardarla como historial. La bitácora recibe exclusivamente códigos permitidos. El filtro de redacción no identifica todos los nombres o direcciones desconocidos: debe configurarse la lista local antes de un eventual uso autorizado con datos reales.
