# Contrato interno de salida 1.0

Tipos ejecutables: [`domain.py`](../../backend/apps/analysis/domain.py). No es una ruta HTTP pública. El trabajador devuelve `AnalysisResult`; `to_dict()` permite serializarlo con `json.dumps`. El esquema JSON está en [`output-1.0.schema.json`](output-1.0.schema.json). Las modificaciones incompatibles requieren otra versión.

| Campo | Tipo y significado |
| --- | --- |
| `contract_version` | Literal `1.0`. |
| `questions_version` | `bloque-texto-1` en trabajos nuevos. Envía una pregunta Choice por pasaje y usa las definiciones de la matriz. Las versiones anteriores conservan su esquema de preguntas para recuperación. |
| `session_id`, `sequence` | UUID canónico y secuencia entera desde 0. Solo uso interno. |
| `state` | `senal`, `sin_riesgo` o `indeterminado`. |
| `transcription` | `{text, words, cleanup}` cuando la respuesta de Speechmatics está disponible en memoria. En fallos o recuperación puede ser `null`. |
| `transcription.words[]` | `{text, start, end, speaker}`. Los tiempos de palabra se refieren al fragmento. `speaker` es `null` en texto plano. |
| `transcription.cleanup` | `deleted` o `delete_pending`. El segundo vuelve el resultado indeterminado. |
| `signals[]` | Categoría, intervalo en segundos de sesión, cita redactada, puntaje y umbral efectivo. El texto plano puede incluir `context_before` y `context_after` con las frases vecinas redactadas. |
| `decisions[]` | Incluye el modelo y el uso. En texto plano, `text_evidence` conserva la categoría elegida y su soporte por pasaje. `values` resume los máximos por categoría. |
| `error_codes[]` | Códigos técnicos o de abstención del resultado global. |
| `review_issues[]` | Intervalos y motivos de los pasajes inciertos o bajo el umbral. Pueden coexistir con señales verificadas. |

`sin_riesgo` indica que un fragmento evaluable no produjo señales según estas reglas experimentales. `senal` requiere borrado remoto confirmado y al menos un pasaje verificado que alcance el umbral operativo. La evaluación usa el significado del texto del pasaje y su contexto cronológico.

Los fallos, el texto vacío o la evidencia insuficiente sin pasajes verificados producen `indeterminado`. El alta de alertas exige estado `senal`. Las negaciones, citas, preguntas y referencias históricas sirven como contexto.

Las alertas tienen prioridad de revisión operativa. El nivel 1 corresponde a prioridad baja, 2–3 a media y 4–7 a alta. El nivel 0 no genera alerta. Esta agrupación es una decisión de implementación pendiente de validación clínica. Cada pasaje verificado conserva su categoría más específica, intervalo, puntaje y umbral.

`register_signals(fragment, result)` genera una alerta por fragmento de texto plano con UUIDv5 determinista por sesión y secuencia. El índice único de `alerts.alerta_id` evita duplicados tras reiniciar el trabajador. `analisis.evidencias` conserva todas las citas verificadas. `descripcion` mantiene la vista resumida de hasta 500 caracteres para consumidores históricos. La notificación usa la prioridad más alta e incluye únicamente datos operativos.

La salida puede contener transcripción sensible: consumirla en memoria, sin imprimirla, registrarla en logs ni guardarla como historial. La bitácora recibe exclusivamente códigos permitidos. El filtro de redacción no identifica todos los nombres o direcciones desconocidos: debe configurarse la lista local antes de un eventual uso autorizado con datos reales.
