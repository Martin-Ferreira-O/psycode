# Evaluación de JEV 1.14 en entrevistas de Psycode

12 de noviembre de 2026 · Base `103c1d4`, contrato `bloque-signals-3`.

Las preguntas nuevas recuperaron señales sintéticas, pero convirtieron el deseo pasivo del tramo de 07:23 en ideación activa. La variante que incorpora solo una pregunta anterior preservó 07:23, aunque repitió el mismo error en una entrevista sintética independiente. El prototipo y las pruebas viven en `scripts/jev_eval`. La evidencia disponible permite seguir evaluando el contexto entre cortes en un entorno de diagnóstico. Los dos errores de categoría y la atribución incorrecta con una etiqueta de voz errónea impiden promover las variantes al trabajador clínico.

## Contrato verificado

Context7 resolvió `/typesafe-docs/typesafeai` y devolvió la guía de `state`, Choice y Noul. El índice de modelos de esa copia aún documentaba 1.13. Contrasté los límites con la referencia vigente y confirmé con un POST sintético que el modelo devuelto es `jev-1.14.0`. El endpoint directo es `POST https://api.typesafe.ai/v1/systemone`. [Referencia de la API](https://api.typesafe.ai/redoc), [modelos](https://docs.typesafe.ai/models).

- `state` acepta JSON estructurado. Cada pregunta recibe el mismo estado y se evalúa de forma independiente. Referenciar `current.turns[1]` dentro de las instrucciones o la descripción de una opción identifica el objeto que se debe evaluar. El nombre de la pregunta sirve para recuperar la respuesta en el cliente. La instrucción debe contener el juicio completo. [State](https://docs.typesafe.ai/concepts/state), [guía de TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one).
- Noul evalúa una proposición binaria con criterios `true` y `false`. Choice devuelve una opción del conjunto definido, con un máximo de 255 y una distribución por opción. Psycode añade `ninguno` y aplica el corte a la probabilidad de la opción elegida. Una Choice de evidencia puede devolver un turno aunque la Noul correspondiente quede baja. Los puntajes cuantifican respuestas a preguntas textuales. [Noul](https://docs.typesafe.ai/primitives/noul), [Choice](https://docs.typesafe.ai/primitives/choice).
- Los límites de 1.14 son 64k tokens para el estado más todas las preguntas y 32k para el estado más una pregunta. `TypeSafe-Danger-Zone-Long-Context: true` eleva ambos límites a 262k tokens. TypeSafe documenta menor precisión y mayor latencia en ese modo. El código limita el JSON de `state` a 262.144 caracteres por defecto y reenvía el bloque una vez con la cabecera si TypeSafe rechaza su tamaño. El límite local mide caracteres. Los experimentos cupieron en el contexto normal. [Límites de contexto](https://docs.typesafe.ai/models#context-length).

Las etiquetas de la batería siguen las categorías de texto de Psycode. Se anotó malestar sin señal suicida, deseo de estar muerta o no despertar, e ideación de causarse la propia muerte. Una respuesta puede contener las últimas dos categorías en afirmaciones diferenciables. Los niveles 3–7 se enviaron para reproducir el contrato y se conservaron en la traza. La batería fue diseñada para evaluar los niveles 0–2. [Protocolo Columbia en español](https://cssrs.columbia.edu/languages/spanish/).

## De la captura a la alerta

| Etapa | Comportamiento del código y punto de pérdida |
|---|---|
| Corte | La captura configurada en bloques actuales de 30 s envía audio consecutivo sin solapamiento. El modo por fragmento invoca a JEV con `history=[]`. El modo por intervención tiene un mecanismo independiente de historial. Véanse `docs/FRAGMENTOS-CONFIGURABLES.md`, `capture/processing.py:197` y `analysis/services.py:207`. |
| Speechmatics | Batch recibe mono PCM 16 kHz, español, diarización por voz y vocabulario psicológico. El parser conserva palabras por intervalo y convierte las etiquetas en identificadores propios del trabajo. `_prepare_block` agrupa por voz, puntuación y pausa, marca solapamientos y redacta texto antes de enviarlo a JEV. Una fusión de voces o una pregunta sin puntuación puede cambiar el turno y su elegibilidad. Véanse `providers/speechmatics.py:37`, `providers/speechmatics.py:185` y `services.py:112`. |
| Rol y opciones | `_block_current` crea alias locales por fragmento. En clínica, la opción de evidencia exige voz asignada y rol `patient` confirmado por la aplicación. El procesador por defecto recibe un mapa vacío si carece de proveedor de roles. El diagnóstico autoriza una convención local para la paciente simulada. Con varias voces de diagnóstico, JEV evalúa el rol por Choice en paralelo. Un alias no identifica a la misma persona en otro bloque. Véanse `capture/processing.py:84` y `services.py:143`. |
| Interpretación y selección | JEV recibe todos los turnos actuales, incluso los que solo sirven de contexto. La lista de evidencia excluye preguntas, citas, referencias a terceros, antecedentes, turnos previos al audio nuevo y voces sin atribución. Las exclusiones se calculan a nivel de turno. Una mención secundaria a una hermana o una cita propia reafirmada hoy puede excluir una afirmación elegible desde el punto de vista semántico. Véanse `services.py:159`, `rules.py:21` y `providers/jev_contract.py:45`. |
| Verificación | Para niveles 1–2, se exige contexto de afirmación propia, Noul ≥ 0,55 y evidencia localizada o una regla literal en una voz confirmada según la versión. Una Choice necesita masa ≥ 0,55 para el turno y coincidencia con la voz de paciente. La inferencia diagnóstica de voz también requiere masa ≥ 0,55. Las dimensiones superiores pasan por reglas locales. El servicio toma la señal de mayor nivel verificado. El malestar se mide como Noul y carece de alerta y localizador. Véanse `providers/jev_contract.py:115`, `services.py:171` y `rules.py:57`. |
| Entrega | `register_signals` registra solo un resultado con señal y sin errores, mediante un identificador determinista. La prueba sustituyó el servicio de alertas por un `Mock` en todos los casos. El registro y la entrega quedaron confinados al simulador. Véase `services.py:435`. |

### Los tramos de regresión

Recuperé de la VPS los cinco WAV del diagnóstico de 07:49 y verifiqué sus SHA-256 contra los registros de ingestión. Los cuatro primeros tienen 30 s y el último 11 s. Para 07:23 reconstruí 30 s desde el Ogg autorizado del instalador mediante el método de remuestreo del diagnóstico anterior. La preparación repitió Speechmatics Batch y congeló los turnos para todas las variantes. El audio de 06:53 y de 07:19 aporta contexto experimental. Una transcripción auxiliar de 90 s desde 06:53 se usó para auditar continuidad, fuera de la comparación de JEV. Los tiempos corresponden al reloj del clip del instalador.

| Fragmento | Qué ocurrió |
|---|---|
| 07:23–07:53 | La paciente expresa un deseo indirecto en `t10`, 07:46,62–07:48,58, voz 2. La transcripción coloca un «sí» anterior junto a la explicación normalizadora del entrevistador en una sola voz y deja una negación breve en esa voz. Esas palabras requieren revisión de diarización. El turno de deseo pasivo sí queda separado. La base repitió categoría 1 con 0,87–0,89 y Choice de `t10` con 0,97. El resultado previo aportado por el usuario fue categoría 1 y 0,90. |
| 07:49–08:19 | El corte deja `t10` completo en el tramo anterior. `t0` (voz 1) comienza a mitad de la reformulación del entrevistador. `t1` (voz 2) expresa cansancio y un deseo ambiguo de dejar de estar allí. La base identificó la voz de la paciente con 0,84–0,85. Sus Noul de deseo quedaron en 0,35–0,39 y la Choice eligió `ninguno` las dos veces. Una repetición seleccionó `t0` para ideación con 0,55, pero la validación descartó esa voz y la Noul de ideación fue 0,30. Con historial, la Noul de deseo llegó a 0,56–0,57 y ambas Choice de deseo siguieron en `ninguno`. El resultado pasó a indeterminado. |
| 08:19–08:49 | Continúa el relato sobre actividades y amistades. En el diagnóstico la voz del relato se reconoce por la conversación del bloque. Las cuatro variantes dieron 0,01 en ambas señales y `ninguno`. |
| 08:49–09:19 | El texto alterna preguntas y respuestas sobre aislamiento y temor a molestar. Batch las fusionó bajo una sola etiqueta. El Noul de malestar en la base fue 0,80–0,81, con ambas señales en 0,01. |
| 09:19–09:49 | Vuelven a alternarse preguntas y respuestas bajo una sola etiqueta. La frase sobre no querer estar allí llega en una reformulación ligada a pedir ayuda. Malestar 0,65–0,67 en la base, con deseo e ideación ≤ 0,02. |
| 09:49–10:00 | Solo se transcribió el inicio de una pregunta hacia el final. Todas las variantes devolvieron pregunta, `ninguno` para ambas evidencias e indeterminado. Falta una respuesta de paciente. |

En 07:49, forzar el mapa de roles voz 1 entrevistador / voz 2 paciente como contrafactual dejó el primer bloque sin señal en todas las variantes. La Noul de deseo llegó como máximo a 0,38. La ausencia del turno anterior y la ambigüedad de la frase actual explican el resultado mejor que un fallo en la Choice de rol. La reformulación del entrevistador tampoco basta para acreditar una afirmación de la paciente. En 07:23, las preguntas nuevas dieron 0,62–0,66 para ideación y seleccionaron `t10` con masa 0,82–0,88. Emitieron categoría 2 en ambas repeticiones, incluso con roles inyectados en el contrafactual. La evidencia apuntaba a la voz correcta y a una afirmación de otra categoría.

## Entrada y preguntas probadas

El código exacto está en `scripts/jev_eval/variants.py`. Las variantes comparten modelo, turnos del bloque actual, verificador y cortes de 0,55. Cada variante necesita una solicitud por bloque.

| Variante | Cambios |
|---|---|
| `actual` | Petición vigente, con ocho Noul, Choice de contexto y Choice de evidencia de niveles 1–2 cuando hay opciones. Choice de voz cuando procede. |
| `preguntas` | Criterios propios de cada categoría, reglas explícitas para las respuestas breves y las reformulaciones, y opciones de Choice que apuntan al índice y al alias exactos. |
| `anterior` | Preguntas vigentes con instrucciones de uso del historial. Hasta dos turnos asignados del fragmento anterior, en los últimos 12 s y con 480 caracteres de texto en total. Alias de voz en un ámbito distinto. |
| `preguntas_anterior` | Combina las dos intervenciones anteriores. |
| `respuesta_previa` | Añade una pregunta previa de entrevistador confirmado solo si el bloque comienza con una respuesta breve de paciente confirmada dentro de los primeros 4 s de audio nuevo. Busca una sola pregunta con marca de cierre, excluye alternativas unidas por «o» y tolera una invitación neutra entre pregunta y respuesta. Fuera de esa condición, el contenido de la solicitud es idéntico a la base. |

Ejemplo sintético del estado de `respuesta_previa`.

```json
{
  "current": {
    "analysis_unit": "fragment",
    "speaker_roles": {"voz1": "patient"},
    "turns": [{"id": "t0", "speaker": "voz1", "text": "Sí, varias veces."}]
  },
  "history": [
    {"speaker": "prev_voz1", "role": "professional", "text": "¿Has pensado en matarte?"}
  ]
}
```

El texto añadido a las preguntas pertinentes de `respuesta_previa` es el siguiente.

> El primer turno actual es una respuesta breve. Usa la pregunta directa de `history` para interpretar qué confirma o niega. Usa como evidencia la respuesta actual solo si expresa o confirma inequívocamente la experiencia.

La Choice solo ofrece `t0` y `ninguno` en este ejemplo. Para el diseño de preguntas por categoría, `preguntas` consultó si la paciente expresa sufrimiento emocional sin deseo o ideación, si desea estar muerta o que su vida termine por sí sola y si ha pensado en causarse la propia muerte. Las dos últimas Choice repitieron la definición de su categoría y apuntaron a un ID elegible del diálogo. La distinción todavía falló en 07:23. Para una iteración posterior, hace falta verificar que el contenido exacto confirmado incluye causar la propia muerte antes de interpretar un «sí» como ideación activa. La categoría y el turno se deben comprobar juntos, en especial cuando el candidato es una respuesta elíptica o una aclaración a mitad de turno.

Si se integra historial en el futuro, el candidato es una pregunta redactada, contigua, de la misma sesión y con rol confirmado. Se debe invalidar al cambiar de sesión o perder continuidad. Un turno previo sirve para resolver el referente de la respuesta. Su evidencia queda asociada al fragmento donde ocurrió. El caso `pasivo_anterior_no_reemitir` y la segunda batería comprueban que una afirmación anterior por sí sola no vuelva a producir una alerta. Los bloques de diagnóstico de 07:23 y 07:49 no cumplieron las condiciones de `respuesta_previa`.

## Comparación

Batería principal de 46 entrevistas sintéticas independientes del clip, con dos repeticiones por variante. Segunda batería dirigida de 14 entrevistas, escrita antes de ejecutar `respuesta_previa`. Los fixtures registran categoría, voz observada, voz real cuando difiere y turnos aceptables. Hay afirmaciones directas e indirectas, respuestas breves, preguntas compuestas, negaciones, autocorrección, citas propias y ajenas, terceros, casos con varias voces, voces sin asignar y atribución errónea. Cada repetición cuenta como una observación de ejecución. El tamaño de cada batería se refiere a entrevistas únicas.

La tabla mide Noul ≥ 0,55 por categoría. Las columnas de resultado final miden el candidato por categoría y turno. Una señal en un turno incorrecto puede contar simultáneamente como FP y FN. Los casos ambiguos deliberados se etiquetaron como negativos. Los fallos HTTP se excluirían por par completo. Las 696 evaluaciones de la comparación devolvieron el modelo solicitado.

### Batería principal

Precisión / exhaustividad en porcentajes. Los conteos Noul se presentan como verdaderos positivos / falsos positivos / falsos negativos.

| Variante | Malestar Noul P/E (VP/FP/FN) | Deseo Noul P/E (VP/FP/FN) | Ideación Noul P/E (VP/FP/FN) | Deseo final P/E | Ideación final P/E |
|---|---:|---:|---:|---:|---:|
| Actual | 73,7 / 100 (14/5/0) | 54,5 / 75,0 (18/15/6) | 70,0 / 70,0 (14/6/6) | 90,0 / 37,5 | 61,5 / 40,0 |
| Preguntas | 100 / 100 (14/0/0) | 56,7 / 70,8 (17/13/7) | 72,0 / 90,0 (18/7/2) | 100 / 41,7 | 53,3 / 40,0 |
| Anterior | 35,9 / 100 (14/25/0) | 53,7 / 91,7 (22/19/2) | 69,6 / 80,0 (16/7/4) | 92,3 / 50,0 | 66,7 / 50,0 |
| Preguntas y anterior | 100 / 100 (14/0/0) | 64,5 / 83,3 (20/11/4) | 76,9 / 100 (20/6/0) | 100 / 50,0 | 71,4 / 50,0 |
| Actual, segunda ejecución | 70,0 / 100 (14/6/0) | 52,9 / 75,0 (18/16/6) | 58,3 / 70,0 (14/10/6) | 100 / 37,5 | 53,3 / 40,0 |
| Respuesta previa, segunda ejecución | 82,4 / 100 (14/3/0) | 57,9 / 91,7 (22/16/2) | 69,6 / 80,0 (16/7/4) | 92,3 / 50,0 | 62,5 / 50,0 |

Las diferencias entre las dos corridas de la base ilustran la variación de los puntajes al repetir solicitudes. Para `respuesta_previa`, el hash de contenido coincide con el de la base en cada par donde no se incorporó una pregunta previa. En esos pares las diferencias de resultado corresponden a repetición del modelo con el mismo contenido.

Abstención de evidencia = Choice ofrecida que devuelve `ninguno`. «Sin Choice» = el código no construyó preguntas de evidencia. «Voz errónea» = el turno elegido pertenece al entrevistador u otra persona según el fixture. Una selección en la voz correcta con categoría o turno equivocados cuenta como error de localización. Los conteos se presentan en orden deseo / ideación.

| Variante | Sin Choice (por nivel) | Choice ninguno | Turno correcto / selecciones en deseo | Turno correcto / selecciones en ideación | Voz errónea Choice | Voz errónea final | Bloque indeterminado |
|---|---:|---:|---:|---:|---:|---:|---:|
| Actual | 20 | 42 / 46 | 14 / 30 | 11 / 26 | 2 / 2 | 0 / 2 | 46 |
| Preguntas | 20 | 42 / 44 | 14 / 30 | 10 / 28 | 2 / 2 | 0 / 2 | 45 |
| Anterior | 20 | 36 / 39 | 18 / 36 | 13 / 33 | 2 / 2 | 0 / 2 | 46 |
| Preguntas y anterior | 20 | 36 / 36 | 18 / 36 | 12 / 36 | 2 / 2 | 0 / 2 | 46 |
| Actual, segunda ejecución | 20 | 42 / 46 | 14 / 30 | 11 / 26 | 2 / 2 | 0 / 2 | 45 |
| Respuesta previa, segunda ejecución | 20 | 36 / 41 | 18 / 36 | 13 / 31 | 2 / 2 | 0 / 1 | 45 |

En malestar, la atribución y la abstención de evidencia son indisponibles en todas las variantes porque la salida de nivel 0 solo contiene Noul. Los turnos de referencia están etiquetados para poder medir una Choice de malestar en otra iteración. La Noul por sí sola tiene salida continua en las tres categorías. El repositorio considera el corte 0,55 como decisión de candidato y conserva la abstención en Choice y verificación. El resumen JSON también identifica los Noul positivos que quedaron sin evidencia localizada.

### Segunda batería de respuesta previa

| Variante | Malestar Noul P/E | Deseo Noul P/E | Ideación Noul P/E | Deseo final P/E | Ideación final P/E | Choice ninguno deseo / ideación | Bloque indeterminado |
|---|---:|---:|---:|---:|---:|---:|---:|
| Actual | — / 0 | 100 / 33,3 | — / 0 | 100 / 33,3 | — / 0 | 24 / 24 | 12 |
| Respuesta previa | 100 / 100 | 60,0 / 100 | 66,7 / 50,0 | 100 / 66,7 | 66,7 / 50,0 | 16 / 16 | 10 |

Cada variante tuvo 28 evaluaciones, con dos por caso. Hubo dos bloques sin Choice por categoría y cero errores de voz en ambas. La variante acertó 6/10 selecciones de deseo y 4/10 de ideación. La base acertó 2/2 y 0/2 respectivamente. Los dos falsos positivos finales de ideación de `respuesta_previa` corresponden al mismo caso repetido. En la base, «—» indica ausencia de predicciones positivas.

### Casos que cambiaron

- `pasivo_si_cruce` dice «Sí, eso me pasa». La base dio deseo 0,01. Con `respuesta_previa` y la pregunta de la entrevistadora, la Noul subió a 0,90–0,93 y se seleccionó la respuesta `t0` como deseo pasivo. La misma variante recuperó dos respuestas activas de la segunda batería, una tras una invitación neutra.
- En `previa_pasivo_afirmacion` la paciente dice «Sí, algunas noches» a una pregunta sobre que la vida termine por sí sola. `respuesta_previa` asignó 0,92 a deseo y 0,62–0,70 a ideación, con `t0` para ambos. El desempate local emitió nivel 2. `preguntas` y `preguntas_anterior` tuvieron el mismo tipo de regresión en 07:23.
- `activo_si_compuesta` combina dos posibilidades en una pregunta. El «sí» provoca un falso positivo en la base. En la primera repetición `preguntas_anterior` devolvió contexto incierto y el verificador bloqueó la señal aunque ambas Choice eligieron ese turno. `activo_si_compuesta_cruce` quedó sin historial en `respuesta_previa`.
- En `activo_profesional_mal_etiquetado` la transcripción asigna a la paciente un ejemplo pronunciado por el entrevistador. Las cuatro primeras variantes seleccionaron la voz etiquetada como paciente y emitieron nivel 2 en las dos repeticiones. En `activo_paciente_mal_etiquetada` la afirmación genuina quedó sin opción de evidencia. En `activo_rol_clinico_no_confirmado` el verificador bloqueó todas las señales.
- En `activo_roles_diagnostico` la primera repetición de la base dio Noul de ideación 0,73 y eligió la respuesta correcta. La Choice de voz dio masa 0,53 a la paciente y la validación bloqueó la señal. En `pasivo_cita_propia_actual` y `pasivo_antecedente_ajeno_a_frase` el problema es distinto. El turno quedó fuera de Choice por las banderas de verificación local, pese a Noul de deseo alto.

### Tokens, latencia y solicitudes

Promedios de tokens del proveedor. Latencia HTTP medida desde esta máquina, con un cliente reutilizado y orden aleatorio fijo. P95 por rango más próximo. Cada columna de latencia describe solo JEV. Los WAV se transcribieron antes y se reutilizaron los turnos. La primera preparación observó aproximadamente 4–7 s por WAV de 11–30 s para transcripción, consulta y limpieza de Speechmatics.

| Batería | Variante | HTTP | Entrada | Salida | Mediana / P95 ms |
|---|---|---:|---:|---:|---:|
| Principal | Actual | 92 | 4.194 | 287 | 189 / 212 |
| Principal | Preguntas | 92 | 3.829 | 287 | 192 / 220 |
| Principal | Anterior | 92 | 5.199 | 287 | 196 / 223 |
| Principal | Preguntas y anterior | 92 | 4.834 | 287 | 197 / 217 |
| Principal, segunda ejecución | Actual | 92 | 4.194 | 287 | 193 / 227 |
| Principal, segunda ejecución | Respuesta previa | 92 | 4.224 | 287 | 192 / 221 |
| Segunda | Actual | 28 | 4.287 | 292 | 195 / 213 |
| Segunda | Respuesta previa | 28 | 4.505 | 293 | 198 / 218 |
| Diagnóstico | Actual | 12 | 4.856 | 403 | 192 / 259 |
| Diagnóstico | Preguntas | 12 | 4.550 | 403 | 195 / 229 |
| Diagnóstico | Anterior | 12 | 6.017 | 403 | 201 / 238 |
| Diagnóstico | Preguntas y anterior | 12 | 5.711 | 403 | 199 / 231 |
| Diagnóstico, segunda ejecución | Actual | 12 | 4.856 | 403 | 205 / 234 |
| Diagnóstico, segunda ejecución | Respuesta previa | 12 | 4.856 | 403 | 195 / 210 |

El contrafactual de roles añadió 16 solicitudes. Hubo una petición por variante, caso y repetición, sin reintentos ni contexto largo. La comparación conservó los cortes de 0,55. En la segunda batería, el falso positivo activo llegó a 0,70 y otras señales dependen además de la evidencia y del rol. Ajustar un solo corte con estos ejemplos no resolvería las causas observadas.

## Reproducción

Desde la raíz del repositorio, con las credenciales privadas de TypeSafe y, para preparar audio, Speechmatics. Los scripts leen variables del entorno o el archivo local `.env`. El artefacto de resultados conserva respuestas, métricas y huellas de los payloads. Los turnos con texto del diagnóstico se guardan localmente bajo `.local/`.

```bash
mkdir -p .local/jev-eval
.venv/bin/python -m unittest scripts.jev_eval.test_run
.venv/bin/python manage.py test backend.apps.analysis backend.apps.capture --settings=backend.config.test_settings --noinput

.venv/bin/python -m scripts.jev_eval.run --live --repeat 2 \
  --output .local/jev-eval/synthetic-new.json

.venv/bin/python -m scripts.jev_eval.prepare --live \
  --manifest scripts/jev_eval/diagnostic_manifest.json --audio-dir .local/jev-eval \
  --output .local/jev-eval/diagnostic-cases-new.json
.venv/bin/python -m scripts.jev_eval.run --live --repeat 2 --diagnostic-only \
  --diagnostic-cases .local/jev-eval/diagnostic-cases-new.json \
  --output .local/jev-eval/diagnostic-new.json

.venv/bin/python -m scripts.jev_eval.run --live --repeat 2 --extension \
  --variant actual --variant respuesta_previa \
  --diagnostic-cases .local/jev-eval/diagnostic-cases-new.json \
  --output .local/jev-eval/followup-new.json
```

El manifiesto identifica los cinco WAV exactos de la VPS y la reconstrucción de 07:23. Esta usa `alerta.ogg` del agente (`7f6a2ca`), 30 s desde el segundo 443, decodificación mono a 48 kHz, `resample_poly(samples, 1, 3)`, redondeo tras multiplicar por 32768, saturación y WAV PCM16 a 16 kHz. Para `previous-0749.wav` y `previous-0723.wav`, recortar 30 s en el segundo 439 o 413 respectivamente con FFmpeg y salida `-ac 1 -ar 16000 -c:a pcm_s16le`. El manifiesto comprueba la huella de los WAV de regresión. Una vez congelada la transcripción, repetir JEV sobre el mismo JSON permite comparar sin variación de ASR. Para reproducir el contrafactual, duplicar las dos entradas `0723-bloque` y `0749-bloque-1`, rellenar `roles` y `previous_roles` con las etiquetas observadas de cada trabajo (S1 profesional, S2 paciente) y ejecutar la misma orden de diagnóstico sobre ese archivo. Son roles inyectados para aislar una variable.

La suite existente de análisis y captura pasó 317 pruebas y el evaluador pasó 5 pruebas con transporte simulado. La comparación en vivo usa TypeSafe real y la preparación del diagnóstico usa Speechmatics real. La segunda batería y los dos tramos de un solo video aportan evidencia de regresión, con cobertura limitada para evaluar desempeño clínico o asignación de roles en otros audios.

## Seguimiento en los cortes de 07:44 y 07:49

El 12 de noviembre se compararon WAV del mismo diagnóstico autorizado. Speechmatics Batch y JEV 1.14 fueron reales y el registro de alertas se simuló. Se compararon los fragmentos aislados de 07:14, 07:44 y 07:49 con diarización normal, sin diarización y con sensibilidad 0,7. También se añadieron los turnos del bloque anterior a `history` o se transcribieron los WAV contiguos como un único trabajo. En este último caso, `new_audio_start_sample` dejó como elegibles los turnos del audio nuevo.

| Variante | Qué ocurrió |
|---|---|
| Sin diarización | Los tres WAV quedaron sin voz asignada. JEV dio ideación 0,60 en el bloque de 07:14, pero el verificador devolvió indeterminado en los tres casos. |
| Diarización a 0,7 | Los tres resultados finales coincidieron con la base. El «sí» de 07:14 siguió en la misma voz que el entrevistador. |
| Texto del bloque anterior más el actual | En 07:49, deseo 0,33 → 0,59, sin evidencia localizada. Resultado indeterminado. En 07:44 se conservó la señal de deseo ya encontrada por la base. En 07:49 el consumo de entrada pasó de 4.839 a 6.476 tokens en una solicitud. |
| WAV anterior y actual en un trabajo | En 07:49, deseo 0,91, con el turno actual de la paciente a 07:54,94. El sentido de su frase admite más de una lectura. Se usaron 5.315 tokens JEV y 60 s de audio Batch. En 07:44 se conservó la evidencia de 07:46,58. |
| 8 s previos más el WAV de 07:49 | Dos voces. Deseo 0,58 y 0,64 en dos llamadas. Ambas eligieron el turno actual de 07:54,94. |
| 12 s previos más el WAV de 07:49 | Speechmatics fusionó las voces. Una llamada quedó indeterminada y la otra atribuyó una señal a la reformulación del entrevistador bajo la convención de paciente de voz única del diagnóstico. |

La propuesta es una ventana móvil con una pregunta o unos pocos turnos previos de la misma sesión. Cada petición se inicia con el bloque actual disponible, el historial tiene un límite fijo y la evidencia seleccionable pertenece al audio nuevo. Si falta el predecesor, el bloque actual sigue siendo analizable. Para cortes que parecen romper un turno, el siguiente ensayo puede comparar una ventana de audio solapada como un solo Batch. Esa prueba debe medir cambios de diarización, falsas atribuciones y duplicación de alertas con los mismos WAV y diálogos independientes. Los alias de lotes distintos requieren confirmación independiente antes de vincularse a una persona. Los datos de seguimiento provienen de un solo clip.
