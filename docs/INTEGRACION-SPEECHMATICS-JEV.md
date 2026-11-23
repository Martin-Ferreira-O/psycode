# Speechmatics y JEV: integración y pruebas en Psycode

> Actualización de separación: [operación vigente](../docs/OPERACION-SEPARADA.md). Agente en el repositorio independiente `psycode-agent`; control WS autenticado, audio v2 y agenda durable. Las instrucciones históricas incompatibles quedan sustituidas por ese runbook.


## Estado verificado

Revisión del **16 de octubre de 2026**, sobre el commit de Psycode **`96299fb`**. Pasaron **28 pruebas de análisis** y **61 pruebas** al incluir la regresión relacionada de alertas. Se utilizaron respuestas HTTP simuladas, audio PCM sintético y persistencia simulada, sin claves reales, llamadas a los proveedores ni consumo de créditos.

Además se comparó la adaptación con `/Users/martin/Desktop/prueba`: se verificaron los seis hashes del manifiesto de origen y su etiqueta; las ocho funciones seleccionadas de reglas/alineación coinciden con el alterno actual. Se comprobó paridad de transcripción con puntuación, contexto solapado, tiempos y voces, así como preguntas y validación JEV para Typesafe y OpenRouter. También se ejercitaron los clientes que crean su propia conexión, sustituyendo su transporte HTTP: autenticación, selección de cuenta/endpoint, WAV, región, modelo, recuperación y borrado funcionaron con los dobles.

Esta verificación acredita la integración local y sus contratos simulados. No acredita conectividad, saldo, disponibilidad de cuentas, precisión clínica ni ejecución nativa en Windows. `runserver` **no inicia un consumidor de audio**: la entrega implementa el módulo y su punto de entrada interno; el productor/ejecutor de fragmentos debe conectarse mediante su tarea correspondiente.

## Procedencia y alcance

Origen: psycode-alterno, copia local `/Users/martin/Desktop/prueba`, rama `feat/speechmatics-jev`, commit **`c3c6278da7e6bbe547f809f50308756f1e4305d3`**. La etiqueta local **`psycode-integration-source-1.0`** apunta a ese commit. El [manifiesto](analysis/source-1.0.json) conserva los SHA-256 originales por archivo. La etiqueta está en el repositorio alterno y no se publica al hacer push de Psycode.

La copia alterna contiene cambios sin commit. La base adaptada se obtuvo del commit indicado; se documentan abajo las correcciones del backend, algunas equivalentes a las correcciones presentes en el árbol local del alterno. No existe en esa copia una referencia `propuesta-api` ni evidencia que permita acreditar su aprobación. **Confirmar con el equipo que este commit es la versión aprobada antes de cerrar administrativamente la tarea.**

| Componente original | Adaptación en `backend/apps/analysis/` |
| --- | --- |
| `whisper_compare/providers/speechmatics.py` | `providers/speechmatics.py` y envoltorio tipado en `clients.py`. |
| `whisper_compare/providers/jev.py` | `providers/jev_contract.py`, `privacy.py`, cliente JEV y contexto en `services.py`. |
| `whisper_compare/providers/http.py` | `providers/http.py` y errores internos en `errors.py`. |
| `whisper_compare/providers/settings.py` | `providers/settings.py`, con configuración desde variables de entorno. |
| `whisper_compare/clinical.py` | `rules.py`: hipótesis, contexto, puertas de evidencia, candidatos JEV y alineación de palabras. |
| `config/clinical_matrix.json` | `matrix.json`: categorías, hash y enmienda de la matriz. |

Código propio de Psycode: puertos en `ports.py`, [salida tipada 1.0](analysis/OUTPUT-1.0.md), reserva durable de fragmentos, coordinación con alertas, conexión a bitácora y pruebas. El [esquema JSON 1.0](analysis/output-1.0.schema.json) versiona la salida. HTTPX figura en `pyproject.toml`, `uv.lock` y `requirements.txt`.

No se trasladaron FastAPI, interfaz experimental, historial SQLite del alterno, herramientas de comparación, modelos locales, OBS, agenda, notificaciones ni procesamiento simultáneo de cinco boxes. No se copiaron archivos `.env`.

## Adaptaciones respecto al prototipo

- Speechmatics conserva el flujo Batch: WAV mono 16 kHz, español, diarización por hablante, modelo Standard/Enhanced, consulta del estado, descarga y borrado. La descarga REST usa `format=json-v2`, corrigiendo el `json` del commit original.
- Se conservan texto, tiempos absolutos y voces por trabajo Batch. `batch-0-S1` solo identifica una voz en el fragmento 0; no identifica al paciente ni equivale a `S1` de otro trabajo.
- Tras recuperar la transcripción se solicita `DELETE` con `force=true`. También se intenta borrar si falla una operación posterior a conocer el ID. Un borrado fallido conserva `delete_pending`, se registra en bitácora y el resultado queda indeterminado.
- Se reserva el fragmento antes de la red y se guardan metadatos técnicos del envío. Los envíos inciertos no se repiten automáticamente, tampoco después de reiniciar. Se rechazan duplicados y secuencias distintas de la esperada.
- JEV mantiene las preguntas `habla-signals-1`, Choice de contexto y ocho Noul, con validación de tipos, claves, rangos, distribución y uso de tokens. Typesafe exige el modelo exacto. OpenRouter admite la misma versión con una fecha válida cuando se solicita su alias versionado; las métricas Choice opcionales se validan si existen.
- Se conserva la selección Typesafe/OpenRouter sin cambio automático de cuenta. A diferencia del prototipo, los POST inciertos de JEV tampoco se repiten; es una adaptación deliberada al criterio de aceptación. Un rechazo explícito 429 permite reintento acotado. GET/DELETE tienen reintentos acotados; esperas `Retry-After` mayores de 30 segundos detienen el reintento.
- El contexto se mantiene por sesión, con ventana de un minuto y límite de 12.000 caracteres. La instancia procesa secuencialmente y limita los contextos activos. No demuestra capacidad simultánea de cinco boxes.
- Antes de JEV se redactan correos, RUT, teléfonos y términos configurados, además de la sesión, ruta de audio y claves conocidas si aparecen dentro del texto; se filtran también URLs, rutas comunes y asignaciones de credenciales. El cuerpo enviado contiene únicamente texto redactado, rol permitido, tiempos y preguntas, sin sesión, box, rutas, identificadores de voz ni claves. La clave del proveedor elegido se utiliza en su cabecera de autenticación.
- El filtro no garantiza anonimización completa: nombres y direcciones desconocidos pueden requerir términos configurados localmente.
- Se excluyeron `ProcessPoolExecutor`, el puente NDJSON y sus pipes. Esta adaptación no crea subprocesos auxiliares y evita trasladar sus bloqueos al backend bajo Windows. La prueba local comprueba ausencia de esos procesos; no sustituye una prueba en Windows nativo.

## Cómo instalar y probar sin credenciales

Desde la raíz del repositorio, con Python 3.12 o 3.13:

```sh
uv sync --locked
uv run python manage.py test backend.apps.analysis --settings=backend.config.test_settings --noinput
```

Alternativa con un entorno virtual activado:

```sh
python -m pip install --require-hashes -r requirements.txt
python manage.py test backend.apps.analysis --settings=backend.config.test_settings --noinput
```

Con el entorno ya instalado, en macOS/Linux puede usarse `.venv/bin/python`; en Windows PowerShell, `.\.venv\Scripts\python.exe`. No hace falta crear `.env`, configurar claves, habilitar procesamiento externo ni disponer de MongoDB para estas pruebas.

Regresión relacionada de 61 pruebas:

```sh
python manage.py test backend.apps.analysis backend.apps.alerts.tests.test_domain backend.apps.alerts.tests.test_api backend.apps.alerts.tests.test_persistence.RepositoryTests backend.apps.alerts.tests.test_persistence.DocumentMappingTests --settings=backend.config.test_settings --noinput
```

Las pruebas de integración usan `httpx.MockTransport`, PCM de ceros y persistencia simulada; bloquean `socket.connect`. La configuración de pruebas omite cargar `.env`. Comprueban transcripción con voces/tiempos, redacción, contexto y orden, validación JEV, fallos, borrado, parcialidad, alertas, idempotencia y bitácora.

## Cómo conectarlo al trabajador interno

1. Crear una única instancia de `backend.config.composition.analysis_worker()` dentro del trabajador del monolito. El constructor no realiza llamadas a proveedores. No instanciarlo por petición ni iniciar procesamiento desde `AppConfig` o una vista HTTP.
2. Entregar un `Fragment` por cada fragmento PCM mono 16 kHz, firmado de 16 bits little endian. Debe incluir sesión UUID canónica, secuencia entera desde 0, box, fecha con zona horaria y ruta del archivo. `start`, `end` y `context_start` son índices de muestras dentro del archivo/sesión, no segundos. La captura y conversión del audio no forman parte de esta entrega.
3. Invocar `worker.process(fragment, roles=roles_confirmados)` de forma secuencial. El rol debe confirmarlo el llamador; no se infiere de la diarización.
4. Consumir el `AnalysisResult` en memoria. No imprimir ni guardar la salida como historial porque puede incluir transcripción sensible. El trabajador registra las señales válidas mediante `AlertsService`.
5. Al finalizar, llamar `worker.close_session(session_id)` y aplicar la política del productor para eliminar sus temporales PCM. Cerrar el contexto no elimina las reservas contra duplicados.

Ejemplo de adaptación del llamador; la función no se ejecuta al definirla. Una llamada con clientes reales requiere configuración y autorización externas y puede consumir créditos:

```python
from pathlib import Path
from backend.apps.analysis.domain import Fragment


def procesar_fragmento(worker, *, sesion_id, secuencia, box, fecha,
                      ruta_pcm, inicio, fin, inicio_contexto, roles_confirmados):
    fragmento = Fragment(
        session_id=sesion_id,
        sequence=secuencia,
        box=box,
        captured_at=fecha,
        path=Path(ruta_pcm),
        start=inicio,
        end=fin,
        context_start=inicio_contexto,
    )
    return worker.process(fragmento, roles=roles_confirmados)
```

Por ejemplo, `{"batch-0-S1": "patient"}` solo es válido si se confirmó ese rol para el fragmento 0. Los roles permitidos son `patient`, `professional` y `unknown`. Sin atribución confirmada al paciente, el resultado permanece indeterminado y no genera alertas.

## Configuración de un eventual uso externo

Las variables y sus valores predeterminados también están en la [sección del README](../README.md#speechmatics-batch-y-jev-configuración-y-pruebas). Las claves del ejemplo están vacías. Mantener el `.env` existente; incorporar únicamente las variables necesarias o inyectarlas desde el entorno del trabajador, sin copiar claves desde el alterno ni publicarlas.

| Variable | Valor predeterminado / uso |
| --- | --- |
| `PSYCODE_EXTERNAL_PROCESSING_ENABLED` | `0`; solo `1` permite envíos externos, antes de leer el audio. |
| `SPEECHMATICS_API_KEY` | Sin valor; necesaria para Speechmatics real. |
| `SPEECHMATICS_REGION` | `eu1`; admite `eu1`, `us1`, `au1`. |
| `SPEECHMATICS_POLL_INTERVAL` | 2 segundos; rango 0,1–30. |
| `PSYCODE_PROVIDER_TIMEOUT` | 300 segundos por etapa; rango 1–540. Borrado: hasta 30 segundos adicionales. |
| `JEV_PROVIDER` | `auto`, `typesafe` u `openrouter`. Auto prefiere Typesafe si existen ambas claves. |
| `TYPESAFE_API_KEY` | Sin valor; necesaria si se elige Typesafe. |
| `OPENROUTER_API_KEY` | Sin valor; necesaria si se elige OpenRouter. |
| `PSYCODE_REDACT_TERMS` | `[]`, lista JSON de nombres/direcciones conocidos localmente. |

En **Configuración operativa** se eligen Jev (1.14 por defecto o 1.13) y
Speechmatics Batch (Enhanced por defecto, Standard, Melia 1 u Oak 1 Medical).
El trabajador consulta la selección al iniciar cada operación de proveedor.
Los trabajos de Speechmatics ya enviados conservan su modelo.

Solo se requiere la clave de la cuenta elegida para JEV. Los destinos están fijados en el adaptador: Typesafe System One o Decisions API de OpenRouter. No se cambia automáticamente de proveedor ante un fallo.

## Alertas, bitácora y recuperación

Solo un resultado `senal` completo, evaluable y sin errores registra alertas. La severidad usa 1–3, según la agrupación existente en [MONGODB.md](MONGODB.md). El fragmento redactado se almacena en `descripcion`, normalizado y limitado a sus 500 caracteres permitidos. `sin_riesgo` no genera alertas; fallos y resultados parciales/no evaluables permanecen como `indeterminado`.

Los UUID de alerta son deterministas por sesión, secuencia, intervalo y categoría. El índice único de MongoDB evita duplicados al repetir la entrega interna. No se invoca el servicio de notificaciones.

`AnalysisAudit` registra los fallos técnicos en `AuditWriter` y en `audit_events`, con acciones `analysis.speechmatics`/`analysis.jev` y códigos permitidos. El validador permite `alerta_id=null` solo para esos eventos anteriores a una alerta. No se guardan transcripciones, respuestas completas, rutas ni claves. Si falla la propia bitácora, se emite un evento sanitizado en el logger `psycode.audit`.

La conexión se probó mediante el punto de composición real y una base simulada. En el despliegue debe verificarse la aplicación del validador de MongoDB y su coordinación con la tarea 6; no se contactó una base real durante esta revisión.

Los archivos de ejecución están bajo `.local/analysis`, ignorado por Git: `fragments/` guarda reservas/secuencias y `jobs/` guarda estado, región e ID técnico de Speechmatics. No contienen audio, textos ni claves.

- `submitting` o `uncertain`: reconciliar manualmente con el proveedor; no volver a subir el audio automáticamente ni borrar reservas para forzar reintentos.
- `delete_pending`: repetir únicamente el borrado del ID conocido en su región original, sin subir audio de nuevo.
- `.lock` tras una interrupción: comprobar que no existe un consumidor activo antes de retirarlo manualmente.
- Reinicio: se pierde el contexto en memoria. No se continúa silenciosamente una sesión con secuencia mayor de 0; requiere revisión operativa y una nueva sesión autorizada.
- Fallo al persistir una alerta: si el llamador conserva el resultado, puede repetir exclusivamente `worker.register_signals(fragmento, resultado)`. No consume proveedores y evita alertas duplicadas. No repetir `process` para esa entrega.

No hay cola durable de resultados ni recuperación automática de conversaciones. Quedan pendientes confirmar la aprobación de `propuesta-api`, verificar la bitácora de la tarea 6 en el despliegue y conectar el productor de fragmentos. Las pruebas reales y la carga simultánea de cinco boxes siguen fuera de alcance.
