# Plan de separación: agente de salas y servidor central

Fecha: 27 de octubre de 2026. Proyecto de origen: `/Users/martin/Desktop/consultoria-bn`, rama observada `sprint/6`.

Este documento es un traspaso para que otro agente de IA implemente la separación. Su creación no ejecuta la migración ni modifica el funcionamiento del sistema.

## 1. Objetivo e instrucciones del usuario

Construir dos repositorios independientes que integren un mismo sistema:

1. **Servidor central:** el repositorio actual de sprint6 conserva exclusivamente el software que se ejecuta en el servidor/VPS.
2. **Agente de sala:** un nuevo repositorio contiene el programa instalado en cada una de las cinco computadoras de psicología. Es el mismo programa con configuración diferente por sala.

El usuario acordó estas funciones del agente:

- Comunicarse con el servidor mediante WebSocket.
- Grabar automáticamente cuando el servidor indique que hay una sesión autorizada.
- Enviar las grabaciones al servidor como fragmentos.
- Obtener información de Smile desde la red institucional: pacientes del día, psicólogos, supervisores y los demás datos que ya entrega la integración existente.
- Iniciarse automáticamente, recuperar la conexión, conservar pendientes de envío, detener la captura al vencer su autorización, informar estado y fallos, y configurarse por sala.

**Smile ya está resuelto según el usuario.** Reutilizar esa integración, sus datos y su comportamiento. No solicitar nuevamente el Excel de ejemplo, no convertir la ausencia del ejemplo en un bloqueo de la separación y no desarrollar un scraper alternativo por suposición.

SCRUM-72 y SCRUM-74 son entregas realizadas. Preservar su lógica y sus pruebas. Las adaptaciones del transporte y de sus límites de integración son parte de este trabajo.

## 2. Decisiones de arquitectura para implementar

| Tema | Decisión |
|---|---|
| Repositorio central | Conservar `/Users/martin/Desktop/consultoria-bn` y su historial. No renombrar la rama `sprint/6` ni cambiar su remoto. |
| Repositorio nuevo | Nombre propuesto `psycode-agent`, en `/Users/martin/Desktop/psycode-agent`, como directorio hermano. No anidarlo en el repositorio central. Si ya existe, inspeccionarlo y conservar sus cambios. |
| Publicación | Preparar el repositorio Git local. Crear un remoto, publicar, desplegar o instalar en equipos institucionales queda fuera de esta ejecución salvo instrucción posterior. |
| Canal de control | WebSocket seguro iniciado por el agente hacia el servidor. El equipo de la sala no necesita un servidor de órdenes accesible desde Internet. |
| Canal de archivos | Mantener HTTPS para subir WAV y los reportes de agenda cuando corresponda. WebSocket transporta control, confirmaciones y estado. |
| Autorización | El servidor decide la ventana autorizada. El agente solo ejecuta y aplica sus límites locales de seguridad. |
| Agenda | Smile se consulta desde el agente. La consolidación de datos, interpretación de agenda y autorización permanecen en el servidor, respetando el contrato existente. |
| Distribución | Un paquete instalable del agente, cinco configuraciones. No crear cinco repositorios ni cinco variantes del código. |
| Cola | Reutilizar `FragmentJob` y la cola SQL existente. No introducir otro broker como requisito inicial. |
| Código compartido | Contratos de red versionados. Ningún import de código del servidor desde el agente ni viceversa en producción. No crear un tercer repositorio de utilidades. |
| Procesos | Agente local; servidor HTTP/WebSocket; coordinador de autorizaciones; trabajador de análisis; tareas de mantenimiento y demás trabajadores centrales existentes. |

Las rutas y nombres nuevos indicados más adelante son propuestas para concretar la implementación. Documentar los nombres definitivos y mantenerlos consistentes entre código, contratos y pruebas.

## 3. Estado del código que debe conocer el agente ejecutor

Inventario de la revisión inicial; verificarlo nuevamente al comenzar porque puede haber cambios posteriores.

| Archivo o módulo actual | Qué contiene / acción |
|---|---|
| `backend/apps/capture/agent/` | Implementación del agente y pruebas locales. Es la fuente principal de la extracción. |
| `backend/apps/capture/agent/main.py` | CLI actual limitada a `status`, `start`, `stop` de OBS. No asumir que ya inicia el agente autónomo completo. |
| `backend/apps/capture/agent/agent_loop.py` | Ciclo actual basado en consulta periódica a un puerto de control. Adaptar su interfaz al transporte WebSocket sin bloquear la captura. |
| `backend/apps/capture/agent/session_coordinator.py` | Inicio, detención, confirmaciones y recuperación. Importa `Command` desde el backend. |
| `backend/apps/capture/agent/command_journal.py` | Registro durable de órdenes `prepared`, `executed`, `acknowledged`. Conservar sus garantías. |
| `backend/apps/capture/agent/audio_chunker.py`, `fragment_store.py` | Fragmentación y persistencia. Importan utilidades del filesystem central. |
| `backend/apps/capture/filesystem.py` | Utilidades que también necesita el servidor. Incluye import de `django.core.files.locks`. No moverlo completo dejando roto el servidor ni arrastrar Django al agente. |
| `backend/apps/capture/domain.py` | DTO `Command`, DTO `Session` y errores centrales. El módulo importa `backend.common.errors`. No copiarlo entero como dependencia local. |
| `backend/apps/capture/ports.py` | Puerto interno `BoxAgentControl`, que el nuevo adaptador remoto debe envolver. |
| `backend/apps/capture/services.py` | Sesiones, órdenes persistentes, `reconcile_box`, ACK, heartbeat, interrupción y recuperación. Permanece central. |
| `backend/apps/capture/authentication.py` | Identidad de máquina `Agent`, vinculada al box. Reutilizar su validación para HTTP y WebSocket. |
| `backend/apps/capture/ingestion.py`, `storage.py`, `uploads.py` | Ingesta durable e idempotente. Permanecen centrales. |
| `backend/apps/capture/processing.py` | Consumidor de la cola, estados, reintentos y limpieza. Permanece central. |
| `backend/apps/capture/management/commands/process_fragment_jobs.py` | Procesamiento por lote; termina al vaciar la cola o alcanzar el máximo. Hay que definir su operación continua. |
| `backend/apps/agenda/services.py` | Lector Excel y agenda de ocupación en memoria. La instancia y sus actualizaciones deben conectarse al coordinador. |
| `backend/apps/operational/capture_authorization.py` | Autorización por agenda/horario clínico. Actualmente contempla respaldo por horario clínico si la agenda no está disponible. Conservar esa política; no cambiarla silenciosamente. |
| `backend/config/composition.py` | Construcción de servicios. Una instancia nueva de agenda puede estar vacía. |
| `backend/config/asgi.py` | Ya existe la aplicación ASGI HTTP; extenderla para WebSocket. |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | Dependencias mezcladas; incluyen `obsws-python`. Separarlas y regenerar los locks por sus herramientas. |
| `docs/SCRUM-72-INTEGRACION.md`, `API_CONTRACTS.md` | Contratos y acuerdos históricos; actualizar los que queden superados. |

La revisión local encontró el lector de Excel, pero no localizó el punto de descarga de Smile. Esto no contradice la confirmación del usuario: el ejecutor debe localizar el componente existente en las fuentes de entrega, ramas o artefactos disponibles y registrar su procedencia. Si no está accesible, avanzar con la extracción y un adaptador de contrato probado con fixtures; reportar la conexión real como pendiente, sin inventar que ya fue validada.

## 4. Contenido final de cada repositorio

### 4.1. Agente: estructura orientativa

```text
psycode-agent/
  pyproject.toml
  uv.lock
  .env.example
  .gitignore
  README.md
  AGENTS.md
  src/psycode_agent/
    __main__.py
    config.py
    domain.py
    runtime.py
    control/             # WebSocket, serialización y reconexión
    capture/             # OBS, FFmpeg, fragmentación y coordinador local
    uploads/             # Cliente HTTPS y cola persistente
    smile/               # Adaptador de la integración existente
    persistence/         # Journal, manifiestos, locks y archivos privados
    diagnostics/
  tests/
    unit/
    contract/
    integration/         # Servidor y OBS simulados
    hardware/            # Optativas; no se ejecutan por defecto
  contracts/             # Schemas/fixtures de la versión soportada
  scripts/               # Instalación, inicio, detención y recuperación
  docs/
```

Solo incluir dependencias necesarias para el agente. No requerir Django, modelos ORM, MongoDB, Speechmatics, JEV, credenciales de proveedores ni el checkout central para instalar o probar el paquete.

Extraer al agente los DTO de transporte que necesita; conservar representaciones equivalentes en el servidor mediante serialización explícita. Implementar las utilidades locales de archivos sin Django, manteniendo permisos privados, atomicidad y compatibilidad Windows/POSIX. No conservar imports `backend.*` mediante modificaciones a `PYTHONPATH`, enlaces simbólicos o paquetes ficticios.

### 4.2. Servidor central

Conservar cuentas, autenticación de profesionales, web, dashboard, configuración operacional, agenda, sesiones, ingesta, almacenamiento privado, análisis, alertas, notificaciones, auditoría y migraciones.

Agregar o completar:

- Adaptador WebSocket autenticado para `BoxAgentControl`.
- Recepción de la información que obtiene Smile, reutilizando la integración de datos existente.
- Persistencia de la última agenda válida y mecanismo de actualización del coordinador.
- Ejecución periódica del coordinador y recuperación de sesiones.
- Ejecución continua y cierre controlado del trabajador de fragmentos.
- Documentación y pruebas de operación de ambos repositorios.

Eliminar al finalizar la extracción el directorio de ejecución local `backend/apps/capture/agent/`, sus dependencias exclusivas, sus instrucciones de instalación mezcladas con las centrales y referencias inválidas a la ruta anterior. Mantener sus antecedentes en Git y un documento que indique el nuevo repositorio. No eliminar migraciones, almacenamiento o utilidades que siga usando el servidor.

## 5. Contrato de control WebSocket

### 5.1. Conexión y autenticación

Ruta propuesta: `/ws/v1/agents`. Conexión `wss://` iniciada por el agente. Desarrollo y pruebas pueden usar `ws://` en loopback.

- Autenticar el handshake con la identidad de máquina ya existente: `Authorization: Agent <agent_id>.<secret>`.
- Extraer una función de validación reutilizable; no duplicar reglas HTTP/WS con comportamientos diferentes.
- Fijar el box desde la identidad autenticada. Un campo `box` enviado por el agente no concede acceso a otro box.
- No usar JWT del psicólogo ni credenciales en query strings.
- Negociar versión del protocolo, versión del agente y capacidades. Rechazar versiones incompatibles con un código estable, sin efectos sobre OBS.
- Impedir dos procesos locales sobre el mismo estado mediante un lock. En el servidor definir una única conexión de control propietaria por identidad/box, con una concesión persistente y vencimiento si hay varios procesos ASGI. Probar la sustitución de una conexión antigua por una reconexión válida.
- La reconexión sincroniza el estado persistente de la sesión; no equivale a autorizar una captura nueva.

### 5.2. Mensajes y semántica

Sobre común JSON: `protocol_version`, `message_id`, `type`, `sent_at`, `payload` y `correlation_id` en las respuestas. Fechas ISO 8601 con zona; UUID canónicos. Publicar schemas, límites de tamaño y ejemplos válidos/inválidos.

| Mensaje / operación | Datos y efecto |
|---|---|
| `hello` / `ready` | Negociación e identidad; el servidor informa hora y parámetros operativos. |
| `sync` / `state` | Reconciliar sesión vigente, órdenes pendientes y estado local. |
| `command` | `command_id`, `session_id`, `box`, `kind`, `scheduled_start`, `scheduled_end`; `kind` conserva `inicio` o `detencion`. |
| `command_ack` / `command_receipt` | Confirmación real de ejecución; `success`, `occurred_at`, código permitido y `last_sequence` en detención. La respuesta se envía después de persistir. |
| `heartbeat` / `heartbeat_receipt` | Actividad de sesión, separada del ping/pong de conexión. |
| `interrupted` / `interruption_receipt` | Interrupción de sesión con código técnico permitido. |
| `status` | Estado operativo: OBS, captura, pendientes, espacio disponible y última sincronización con Smile. No es una autorización. |
| `error` | Código estable, correlación y si es recuperable. Sin excepciones libres ni datos clínicos. |
| `agenda_collect` / confirmación | Si la integración Smile requiere órdenes de descarga: flujo propio, sin inventar un tercer `kind` en las órdenes de captura. |

Reglas obligatorias:

1. Entrega de órdenes al menos una vez, con `command_id` estable y journal local durable.
2. Distinguir recepción de un mensaje, ejecución de OBS y confirmación durable del servidor. Solo la última permite cerrar el ACK pendiente local.
3. Reintentar un ACK perdido con el mismo contenido aunque el servidor ya no reentregue la orden.
4. Detenciones con prioridad, limitadas al `session_id` correspondiente. Las sesiones fallidas no se reactivan con mensajes retrasados.
5. Envolver los métodos existentes del dominio; no reproducir la máquina de estados dentro del handler WS.
6. El servidor conserva órdenes en SQL. Para esta primera implementación, el handler puede revisar órdenes pendientes a intervalo acotado y publicarlas por WS; no depende de memoria compartida con el coordinador ni requiere Redis. Documentar el intervalo y probar el flujo entre procesos separados.
7. La captura, la subida, la consulta de Smile y los ACK deben poder progresar sin bloquear el manejo de detenciones o heartbeats. Definir timeouts y colas internas acotadas.
8. Reutilizar los códigos técnicos de sesiones existentes. Los nuevos errores operativos de transporte/diagnóstico deben documentarse sin enviarlos a campos que solo admiten el catálogo anterior.

Valores iniciales propuestos: revisión del coordinador cada 5 s, revisión de órdenes por la conexión cada 1 s, heartbeat de sesión cada 30 s. Conservar inicialmente los plazos centrales de 120 s para inicio/inactividad y 300 s para finalización. Todos configurables; no utilizar esos plazos para extender una autorización vencida.

## 6. Captura, desconexión y recuperación

- Iniciar OBS solo por una orden vigente destinada al box y la sesión correctos.
- Conservar la espera de disponibilidad del audio antes de confirmar inicio; una respuesta de OBS por sí sola no prueba que FFmpeg ya dispone del audio.
- Registrar intención y ejecución durablemente. Un reinicio no debe reiniciar OBS a ciegas ni duplicar la captura.
- Usar un plazo local calculado con reloj monotónico para aplicar el fin autorizado; las fechas interoperables siguen en UTC. Detectar desajustes de reloj y definir cuándo impiden iniciar.
- Si se pierde el control, reconectar con backoff y jitter sin extender `scheduled_end`. Conservar la política actual de cierre tras agotar fallos; hacerla explícita y probarla.
- Al vencer o revocarse la autorización, cortar la captura dentro del plazo permitido. No prolongarla hasta completar un fragmento de duración nominal. Finalizar un WAV parcial válido y subir solo audio permitido por la ventana.
- En una detención normal, finalizar el audio actual, fijar durablemente `last_sequence`, drenar pendientes hasta un plazo acotado y confirmar la detención. No esperar indefinidamente a la red.
- `last_sequence` es la última secuencia generada localmente, no la última aceptada por el servidor; `-1` cuando no hubo audio.
- Después de declarar `last_sequence` no generar secuencias mayores. El servidor puede recibir uploads y ACK en distinto orden, respetando los estados y límites actuales.
- Ante un journal inconcluso, reconciliar con el servidor e inspeccionar OBS. Si no se puede demostrar que es seguro continuar, mantener un estado de recuperación explícito, no borrar evidencia ni autorizarse de forma local.
- Conservar ubicación y formato de journals/manifiestos existentes o incluir una migración local verificable. Una actualización del agente no debe perder audio pendiente.

El agente debe tener una entrada ejecutable para funcionamiento autónomo y comandos de estado/diagnóstico/recuperación. Evitar acciones manuales que eludan autorización central durante la operación normal.

## 7. Envío de fragmentos y contrato temporal

### 7.1. Compatibilidad de la API actual

Conservar `POST /api/v1/internal/fragments`, sin barra final, y sus siete campos: `archivo`, `box`, `session_id`, `secuencia`, `formato`, `checksum`, `captured_at`.

- WAV RIFF PCM lineal mono, 16 kHz, 16 bits little endian. El límite inicial existente es 25 MiB por archivo.
- Secuencias consecutivas desde cero. Resolver la aceptación de N antes de avanzar a N+1.
- SHA-256 sobre todos los bytes del WAV definitivo. No regenerar ni modificar bytes, fecha o identidad al reintentar.
- Nueva aceptación: HTTP 201. Reintento idéntico: HTTP 200, mismo trabajo. Verificar todos los datos de la confirmación antes de borrar.
- La aceptación del archivo no significa que el análisis terminó. El agente no espera resultados clínicos para liberar un archivo aceptado.
- No llamar adicionalmente a `accept_sequence()` por archivos enviados mediante la API.
- Reintentar errores transitorios con límite. No repetir ciegamente 401/403, conflictos, archivos inválidos o sesiones cerradas.
- Agotar intentos no autoriza eliminar el archivo. Definir estado de intervención, retención y limpieza explícita. Al llegar al límite de disco, informar y detener de forma controlada antes de corromper archivos.
- Cuando el servidor ya no admita pendientes por el cierre definitivo de la sesión, mantenerlos en un estado operativo explícito. No renumerarlos, cambiarles la sesión ni reabrir autorizaciones para forzar su aceptación.
- Inventariar también las grabaciones completas que deje OBS, además de los WAV fragmentados. Asignarles ubicación privada y retención para evitar una segunda copia que crezca sin límite. La limpieza no debe borrar fragmentos pendientes de confirmación.

### 7.2. Solapamiento y tiempos

Conservar inicialmente el perfil existente configurable de 10 s por fragmento y 1 s de solapamiento. Registrar el perfil efectivo por sesión; no permitir que cambie a mitad de sesión sin un contrato explícito. El último WAV se conserva solo si incluye audio nuevo, evitando otro archivo compuesto únicamente por solapamiento.

La extracción debe preservar la API v1. Para transmitir intervalos adicionales, publicar una ampliación versionada; propuesta: `/api/v2/internal/fragments`. No añadir campos silenciosamente al multipart v1 que hoy los rechaza. Mantener pruebas de compatibilidad v1 y declarar sus límites para análisis con solapamiento si no incluye metadatos suficientes.

Durante la transición, el servidor admite el contrato anterior y el nuevo. El agente selecciona capacidades negociadas; no activa el envío v2 contra un servidor que no lo soporte. Publicar una matriz de compatibilidad de versiones y probar la actualización del servidor antes que la de los agentes. No eliminar v1 como parte de esta extracción.

Contrato temporal propuesto para la versión nueva:

- `captured_at`: instante UTC de la primera muestra del WAV; conservarlo durante reintentos. El instante base de adquisición es el primer audio válido, no la hora de upload ni una promesa de precisión del PTS del streaming.
- `session_start_sample`: índice, relativo a la sesión, de la primera muestra del WAV.
- `session_end_sample`: extremo exclusivo de la última muestra del WAV.
- `new_audio_start_sample`: inicio del audio nuevo de ese WAV, excluyendo el contexto repetido.
- `sample_rate`: 16000; validar que `session_end_sample - session_start_sample` coincida con las muestras reales.
- Invariantes: `0 <= session_start_sample <= new_audio_start_sample < session_end_sample`. Validar continuidad y solapamiento contra la secuencia anterior y el perfil registrado.
- El servidor valida también el extremo final del audio contra la ventana autorizada, con tolerancia técnica explícita y acotada; validar solo `captured_at` no demuestra que todo el archivo esté dentro de ella.

Ejemplo de 10 s / 1 s, en muestras de sesión:

| Secuencia | Inicio del WAV | Inicio del audio nuevo | Fin exclusivo |
|---|---:|---:|---:|
| 0 | 0 | 0 | 160000 |
| 1 | 144000 | 160000 | 304000 |
| 2 | 288000 | 304000 | 448000 |

**Cuidado con el adaptador de Speechmatics:** actualmente `Fragment.context_start`, `start` y `end` se usan también para posicionarse dentro del archivo. No sustituirlos directamente por índices absolutos de sesión: un WAV independiente no contiene las muestras anteriores. Mantener offsets locales al archivo para lectura y un origen separado para normalizar transcripciones al tiempo de sesión.

Usar el audio repetido como contexto y asignar la evidencia nueva a un único intervalo. Definir la regla de pertenencia para frases que cruzan el corte y probarla. Evitar alertas repetidas por solapamiento además de deduplicar trabajos/reintentos; no fusionar dos afirmaciones distintas solo por tener el mismo texto o categoría. No reducir el solapamiento a cero como atajo para evitar este problema.

## 8. Smile y actualización de la agenda

### 8.1. Qué extraer y qué conservar

Localizar y reutilizar el mecanismo existente de acceso/descarga de Smile. Las credenciales de Smile y la comunicación con la red institucional pertenecen al agente. La interpretación y consolidación central de datos mantiene el contrato ya entregado. Si la integración existente tiene otra separación interna, envolverla con adaptadores antes de reescribir su lógica.

No deducir que todos los agentes ven las cinco salas. Respetar el alcance existente. Si varias instalaciones obtienen el mismo reporte global, asignar un colector principal por fuente y un reemplazo controlado por el servidor para evitar descargas concurrentes. No agregar una elección distribuida entre PCs como requisito.

La sincronización de Smile funciona independientemente de la grabación. Puede ser necesaria antes de autorizar la primera sesión. Una falla de Smile no bloquea el hilo de control ni modifica la ventana ya recibida por el agente.

### 8.2. Transporte y persistencia central

Reutilizar el contrato existente para transmitir el resultado. Si falta únicamente el transporte remoto, agregar un endpoint autenticado propuesto `/api/v1/internal/agenda-reports`, sin cambiar el significado de los campos existentes.

- Enviar el reporte descargado o su representación existente, identificado por una operación de recolección estable y checksum. No crear dos parsers incompatibles.
- Metadatos mínimos de sincronización: identificador de recolección, fuente, fecha de agenda, instante de obtención, alcance de boxes y versión de formato. Reutilizar nombres existentes si ya están definidos.
- Validar qué identidades pueden actualizar una fuente de agenda. La capacidad de subir audio de un box no concede automáticamente permiso para actualizar todos los boxes.
- Aceptación durable e idempotente. Guardar última versión válida y revisión por fuente/box para sobrevivir reinicios.
- Impedir que un reporte atrasado reemplace uno más reciente. Preferir generaciones de recolección asignadas por el servidor; los reintentos conservan la generación. No confiar únicamente en el reloj de la PC o en el orden de llegada.
- Distinguir reporte válido vacío, reporte parcial y descarga fallida. Solo una actualización explícita y válida puede vaciar los boxes cubiertos; conservar los no incluidos.
- Preservar las relaciones con pacientes, psicólogos y supervisores que ya entregue Smile. No inventar identificadores ni asumir que el lector de ocupación actual representa toda esa integración.
- Registrar frescura y fallo de sincronización, manteniendo explícito el respaldo por horario clínico existente. Modificar esa política requeriría una decisión funcional separada.

### 8.3. Instancia de agenda y procesos

El coordinador crea una sola instancia de `AgendaService`, la carga desde la última revisión válida y la inyecta en autorización y sesiones. Actualiza esa misma instancia al cambiar la revisión. Ninguna fábrica del flujo debe sustituirla accidentalmente por una agenda vacía.

Dos procesos no comparten un objeto Python. Los receptores HTTP persisten actualizaciones y el coordinador observa revisiones; cualquier otro consumidor central reconstruye su vista desde la misma fuente durable. Verificar específicamente reinicio del coordinador y recepción de agenda en otro proceso.

## 9. Procesamiento central y alcance clínico

- Mantener el análisis y las claves de Speechmatics/JEV exclusivamente en el servidor.
- Conservar los estados de trabajo `pendiente`, `procesando`, `completado`, `fallido`, separados de `riesgo_detectado`, `sin_riesgo_detectado`, `indeterminado`.
- Mantener la diferencia entre imposibilidad de atribuir/evaluar y fallo técnico del proveedor.
- Conservar las severidades 1–3, el extracto en `descripcion`, la deduplicación y la ausencia de alertas para resultados sin riesgo o indeterminados.
- **Sin identificación confiable del hablante, no asignar el rol de paciente.** Mantener `unknown`; cuando la regla necesita atribución y no la tiene, producir `indeterminado` sin alerta. No introducir un mapeo automático `S1 = paciente` ni atribuir por defecto todo el audio al paciente.
- Conectar la recepción a `FragmentJobProcessor` mediante la cola existente, sin ejecutar proveedores dentro del request HTTP.
- Dar al trabajador un modo continuo con espera cuando no hay trabajos y parada controlada. Conservar el modo por lote para pruebas y operación acotada.
- La implementación actual mantiene contexto de sesión en memoria y rechaza secuencias posteriores si se perdió. Resolver y documentar el reinicio: restaurar un checkpoint mínimo solo si el contrato de almacenamiento existente lo permite; de lo contrario marcar explícitamente el fallo técnico y la recuperación requerida. No procesar secuencias posteriores fingiendo contexto vacío ni prometer recuperación automática inexistente.
- Empezar con un trabajador secuencial y afinidad de sesión mientras el contexto sea local. No habilitar varios consumidores independientes de una misma sesión sin resolver primero su contexto compartido y orden.
- Cerrar contextos terminados cuando ya no queden trabajos de esa sesión. Finalizar captura y terminar análisis son hitos diferentes.
- No convertir cualquier fallo externo en un reintento automático: respetar los casos de envío incierto y las garantías existentes para no duplicar llamadas, cargos o alertas.

## 10. Configuración, instalación y operación

### 10.1. Agente

Mantener compatibilidad o migración documentada de las variables actuales: `BOX_ID`, `OBSW_HOST`, `OBSW_PORT`, `OBSW_PASSWORD`, `STREAM_URL`, `CHUNK_DURATION`, `CHUNK_OVERLAP`, `PSYCODE_INTERNAL_BASE_URL`, `PSYCODE_AGENT_TOKEN`, `HTTP_TIMEOUT`, `MAX_RETRIES`, `RETRY_BACKOFF`, `HEARTBEAT_INTERVAL`, `CONTROL_MAX_FAILURES`, `AGENT_STATE_ROOT`.

Agregar configuración de URL WebSocket, reconexión, límites locales y capacidades de Smile según la integración existente. Revisar `COMMAND_POLL_INTERVAL`: retirarlo o renombrarlo si deja de tener ese significado; no conservar una variable engañosa.

La configuración debe cargarse al construir el programa, no como efecto lateral de importar un módulo. Unificar las rutas de estado y fragmentos en directorios persistentes ajenos al directorio de instalación. Dar un ejemplo por sala sin secretos reales.

Documentar OBS, FFmpeg y MediaMTX según la topología ya validada. Identificar dónde se ejecuta MediaMTX; si depende de una red inaccesible, preparar la alternativa local y validarla. No asumir que cambiar de repositorio convierte esa dependencia en local automáticamente.

El agente no requiere interfaz propia. El inicio automático debe respetar cómo se ejecuta OBS y sus permisos en la sesión del equipo. Para Windows, proporcionar instalación como servicio o inicio automático bajo la cuenta adecuada, verificando acceso a OBS, audio y estado privado; no prometer que OBS funcionará sin sesión interactiva si no está demostrado.

### 10.2. Servidor

Conservar configuración central de Django, SQL, MongoDB, notificaciones, proveedores, almacenamiento y `CAPTURE_AGENTS`. Separar variables nuevas de coordinación/WebSocket/agenda de las exclusivas de OBS.

Preparar configuración de ASGI y del proxy para HTTPS/WSS, incluyendo Upgrade, timeouts, tamaño máximo de carga y apagado controlado. No desplegarla durante la implementación.

Documentar comandos exactos que realmente existan al terminar para:

1. Instalar dependencias y aplicar migraciones.
2. Iniciar servidor HTTP/WebSocket.
3. Iniciar coordinador periódico de autorizaciones y recuperación.
4. Iniciar trabajador continuo de fragmentos.
5. Ejecutar limpieza y trabajadores de correo/notificaciones existentes.
6. Consultar salud, detener procesos y recuperar pendientes.

No iniciar trabajadores en imports, `AppConfig`, WSGI/ASGI startup por cada worker web ni vistas HTTP. Un solo coordinador activo o exclusión mediante lease persistente.

Orden de parada: impedir nuevos inicios, solicitar cortes autorizados, recibir confirmaciones y pendientes dentro de plazos acotados, conservar estado durable y detener consumidores. Evitar cerrar primero el receptor si todavía se esperan uploads. Una parada forzada debe tener recuperación documentada y probada.

## 11. Secuencia de implementación y entregables

### Fase 0. Inventario y línea base

- Leer las instrucciones vigentes de ambos directorios y revisar cambios locales. No sobrescribir trabajo ajeno.
- Confirmar rama y revisión de origen; crear una rama de trabajo `codex/separacion-agente-servidor` si no existe una rama de tarea indicada. No renombrar ni borrar `sprint/6`.
- Registrar qué pruebas pasan, fallan o requieren servicios externos. No presentar como resultado propio el número histórico de pruebas de los README.
- Identificar componentes de Smile y topología de captura desde sus fuentes existentes, sin pedir el Excel otra vez.
- Elaborar un manifiesto de extracción: origen, destino, dependencias, pruebas y tratamiento de datos locales.

**Salida:** línea base y manifiesto verificables; ninguna funcionalidad se elimina todavía.

### Fase 1. Contratos

- Especificar WebSocket, errores, autenticación, reconexión y compatibilidad.
- Documentar audio v1, nueva representación temporal versionada y contrato de Smile existente.
- Publicar schemas y fixtures sin datos reales. Fuente canónica: documentación/contratos del servidor; el agente conserva la versión soportada con comprobación automática de compatibilidad.

**Salida:** ambos lados pueden implementar y probar mensajes sin importar código del otro.

### Fase 2. Extracción del paquete local

- Crear el repositorio hermano y un paquete Python instalable con dependencias y lock propios.
- Extraer captura, OBS, fragmentación, uploads, journal, recuperación y configuración.
- Sustituir imports centrales por DTO y utilidades locales independientes.
- Mover pruebas unitarias y simulaciones. Preservar pruebas de privacidad y recuperación de archivos.
- Incorporar el adaptador Smile existente y su configuración local.

**Salida:** el agente se instala y sus pruebas propias pasan sin Django ni acceso al repositorio central.

### Fase 3. Canal WebSocket en ambos lados

- Extender ASGI y agregar autenticación, serialización y adaptador al dominio existente.
- Implementar cliente WS, reconexión, confirmaciones durables y reconciliación.
- Conservar la lógica local de captura y recuperación, adaptando su invocación al canal nuevo.
- Probar comandos y ACK repetidos, respuesta perdida después de commit, corte de red y cierre por ventana.

**Salida:** un servidor y un agente simulado intercambian órdenes reales por WebSocket, en procesos separados.

### Fase 4. Smile y agenda compartida

- Conectar el adaptador existente al transporte y autenticación central.
- Persistir revisiones válidas e impedir actualizaciones duplicadas o atrasadas.
- Conectar el coordinador a una agenda cargada y actualizable. Probar el respaldo existente.
- Verificar que una actualización de agenda pueda detener una sesión o crear otra según las reglas actuales, sin sesiones superpuestas.

**Salida:** agenda obtenida desde el lado local alimenta la autorización central sin carga manual adicional.

### Fase 5. Tiempo, solapamiento y análisis

- Implementar el contrato temporal versionado, validaciones y migraciones compatibles.
- Separar posiciones locales del WAV de tiempos de sesión; conservar API v1.
- Aplicar propiedad del audio nuevo y deduplicación de evidencia repetida.
- Probar la política sin hablante identificado, diferenciando indeterminación y fallo técnico.
- Completar ejecución continua, límites de contexto y política de reinicio del consumidor.

**Salida:** fragmentos aceptados llegan al análisis con tiempos coherentes y resultados acordes con la atribución disponible.

### Fase 6. Operación automática

- Implementar entrada autónoma, inicio automático, diagnóstico y detención del agente.
- Documentar/probar comandos y supervisión de los procesos centrales.
- Mantener configuración de secretos fuera de Git y conservar estado durante actualizaciones.

**Salida:** runbooks reproducibles para instalar, arrancar, detener y recuperar ambos componentes.

### Fase 7. Limpieza del repositorio central

- Solo después de validar el paquete extraído, eliminar su implementación de la ruta central.
- Retirar dependencias exclusivas del agente y regenerar lock y export de dependencias centrales.
- Reubicar las pruebas que mezclaban ambos sistemas; no perder cobertura para que desaparezcan errores de imports.
- Actualizar README principal, documentación de captura, composición, contratos y notas de SCRUM-72/74 afectadas.
- Comprobar que el servidor se instala y se prueba sin OBS, FFmpeg ni el repositorio hermano. Las integraciones cruzadas serán una suite explícita aparte.

**Salida:** sprint6 contiene solo ejecución central y referencias al contrato del agente.

### Fase 8. Verificación final y entrega

- Ejecutar pruebas apropiadas, incluyendo conexión real WS/HTTP entre dos procesos locales con servicios externos simulados.
- Registrar revisiones de ambos repositorios, cambios, resultados y límites de validación.
- Entregar enlaces locales, comandos y estado de pendientes concretos. No declarar pruebas institucionales ni de hardware que no se realizaron.

Separar commits por extracción, contratos, transporte, integración y limpieza cuando se hagan commits. No mezclar la migración con cambios clínicos o refactors ajenos.

## 12. Pruebas y criterios de aceptación verificables

### 12.1. Distribución de pruebas

- Agente: unitarias, contratos y backend/OBS/Smile simulados sin Django.
- Servidor: dominio, API, cola, autorización, WS y agente simulado sin importar `psycode_agent` en la suite central ordinaria.
- Integración cruzada: suite separada que instala una versión identificada del agente como dependencia solo de pruebas y levanta los dos procesos. Puede vivir en el servidor. No depender del nombre ni de la proximidad de carpetas del desarrollador.
- Pruebas actuales `test_http_integration.py` y `test_control_ack_integration.py`: revisar y trasladar su cobertura a esa suite o a pruebas equivalentes de contrato. No llevar fixtures ORM al repositorio del agente.
- Hardware y red institucional: optativas y documentadas. Pruebas automáticas de proveedores no consumen créditos.
- Configurar verificación automatizada propia en cada repositorio: instalación desde su lock, pruebas pertinentes y detección de imports prohibidos. Cubrir Windows para persistencia/servicio del agente y Linux para el servidor; no presentar un resultado de un sistema operativo como validación del otro.

### Responsables de validación

| Entrega | Validación técnica | Evidencia de cierre |
|---|---|---|
| Extracción y ejecución local | Agente ejecutor; revisión del responsable de SCRUM-72 | Instalación aislada, pruebas de captura/recuperación y runbook local. |
| WebSocket, sesiones e ingesta | Agente ejecutor; revisión de responsables de SCRUM-71/73 | Contratos y pruebas WS/HTTP entre procesos, estados y reintentos. |
| Smile y agenda | Responsable de la integración existente y del flujo de autorización; pruebas del ejecutor | Datos del contrato preservados, actualización durable y mismas reglas operativas. |
| Trabajador y resultados | Agente ejecutor; revisión del responsable de SCRUM-74 | Orden, deduplicación, fallos técnicos, atribución desconocida y proveedores simulados. |
| Alcance funcional y entrega | Responsable del proyecto | Criterios de este documento y pendientes documentados. |

Estos son roles, no nombres inventados ni autorizaciones para contactar a otras personas. El agente ejecutor completa las comprobaciones automáticas disponibles y deja las evidencias preparadas para revisión sin convertir cada fase en una solicitud de permiso. La falta de revisión humana no impide preparar una implementación verificable; tampoco permite afirmar que esa revisión ocurrió.

### 12.2. Matriz mínima

| Caso | Resultado requerido |
|---|---|
| Instalación aislada del agente | Importa y ejecuta pruebas sin backend, Django o bases de datos. |
| Instalación aislada del servidor | Pruebas centrales sin OBS ni checkout del agente. |
| Identidad inválida o box ajeno | Rechazo sin ejecutar captura ni aceptar datos fuera del alcance. |
| Protocolo incompatible | Error explícito, sin efectos de captura. |
| Orden de inicio duplicada | Una sola ejecución de OBS; ACK idempotente. |
| ACK perdido tras commit | Reenvío idéntico; misma sesión y resultado. |
| WS desconectado y reconectado | Reconcilia estado y órdenes sin reiniciar captura a ciegas. |
| Autorización vencida sin conexión | Detención local dentro del límite acordado. |
| Revocación a mitad del fragmento | Corte y último WAV parcial; no incluye audio fuera de ventana. |
| OBS aún sin audio / falla FFmpeg | No confirma captura sana; comunica fallo permitido. |
| Upload duplicado o respuesta perdida | Un trabajo; misma identidad y bytes; borrado solo tras confirmación válida. |
| Conflicto de checksum o secuencia | Rechazo consistente y conservación local de evidencia. |
| Reintentos agotados / disco casi lleno | Estado visible y parada controlada; sin borrado silencioso de pendientes. |
| Detención sin fragmentos | `last_sequence = -1`; cierre consistente. |
| Último fragmento parcial | Se envía si tiene audio nuevo; no genera archivo de solo solapamiento. |
| Estado local tras reinicio/actualización | Conserva journal y pendientes; no duplica ni borra audio. |
| Mismo reporte Smile repetido | Una actualización lógica, confirmación idempotente. |
| Reporte antiguo que llega tarde | No reemplaza una revisión nueva. |
| Reporte vacío / descarga fallida | Comportamientos distintos; una falla no vacía la agenda. |
| Recepción de agenda y coordinador separados | El coordinador observa la revisión válida y mantiene su instancia cargada. |
| Reinicio del coordinador | Recupera agenda y sesiones; no inicia con agenda vacía por accidente. |
| Cambio de agenda / horario | Órdenes y sesiones correctas, sin solapamiento de ventanas por box. |
| Solapamiento y frase en el corte | Tiempos de sesión coherentes, evidencia contextual conservada y alerta no duplicada. |
| Hablante desconocido | No se atribuye al paciente; indeterminado sin alerta cuando falta atribución requerida. |
| Fallo técnico del proveedor | Trabajo fallido/recuperado según contrato, separado de resultado indeterminado. |
| Trabajo bloqueado o consumidor reiniciado | Recuperación segura o fallo explícito; sin pérdida silenciosa de contexto. |
| Captura completada con análisis pendiente | No se eliminan trabajos ni se confunde fin de captura con fin de análisis. |
| Parada de procesos | Estado durable, tiempos acotados y recuperación documentada. |

## 13. Definición de terminado

- Existen dos repositorios independientes, con manifiestos, dependencias, pruebas y documentación propios.
- Sprint6 ya no contiene el programa de la PC ni requiere sus dependencias de captura.
- El agente usa WS para control y HTTPS para archivos, con identidad por sala.
- Smile existente se ejecuta desde el lado local y sus datos llegan a la agenda central según su contrato. Si su fuente no fue accesible, reportarlo como pendiente de conexión real y no marcar esta condición cumplida.
- Inicio, detención, recepción, cola y análisis están conectados y probados con simulaciones.
- Se conservan autorizaciones, estados, idempotencia y recuperación existentes; las ampliaciones tienen migraciones y contratos explícitos.
- Existe un contrato temporal documentado y probado para duración, solapamiento y último fragmento.
- No se atribuye automáticamente al paciente una voz desconocida.
- Los procesos necesarios tienen comandos reales de inicio, detención y diagnóstico.
- Se registran resultados de pruebas, versiones compatibles y límites. No hay secretos, audios ni datos reales de pacientes en Git.

Fuera de alcance: prueba integral formal con dos boxes, prueba de carga con cinco boxes, despliegue institucional, publicación de repositorios remotos, nuevos criterios clínicos, rediseño de Smile y actualizador automático de toda la flota. La automatización de inicio local sí está incluida.

## 14. Instrucción inicial para el nuevo agente de IA

> Implementa el plan de este documento en el proyecto `/Users/martin/Desktop/consultoria-bn` y un repositorio hermano propuesto `/Users/martin/Desktop/psycode-agent`. El usuario ya acordó separar el software local de las salas y el servidor central. Usa WebSocket para control y conserva HTTPS para archivos. Reutiliza SCRUM-72, SCRUM-74 y la integración Smile existente, sin pedir otra vez el Excel ni rehacer funcionalidades entregadas. Empieza revisando instrucciones, cambios locales y la línea base. Extrae el agente como paquete independiente, elimina imports del backend y conserva pruebas y estado durable. Implementa los adaptadores y la operación automática descritos. Limpia el repositorio central después de comprobar que la extracción funciona. Consulta Context7 antes de implementar sintaxis o configuración de librerías/frameworks, conforme a las instrucciones del proyecto. No publiques ni despliegues. No consumas créditos de proveedores. Informa avances y entrega los dos repositorios con pruebas, contratos, comandos y pendientes verificables. No presentes este plan como implementación ya completada.
