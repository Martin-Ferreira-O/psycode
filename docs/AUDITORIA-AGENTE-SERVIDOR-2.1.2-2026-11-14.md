# Auditoría de PSYCODE Agent y servidor desde 2.1.2

Fecha: **14 de noviembre de 2026**, zona `America/Santiago` (UTC−03:00).
Destinatario: agente o desarrollador que implementará las correcciones.
Alcance: diagnóstico, inspección de producción de solo lectura y pruebas sintéticas. **No se aplicaron correcciones ni se modificaron servicios, credenciales o datos operativos.**

## 1. Conclusión ejecutiva

Hay tres problemas que deben tratarse por separado:

1. **Actualización integrada:** el mensaje de indisponibilidad agrupa fallos de configuración local y respuestas HTTP 401/403/404. No significa «no existe una versión nueva». La VPS tiene **2.1.3**, con manifiesto correcto, y hay descargas completas exitosas. Los registros también contienen rechazos 401, pero proceden de otros orígenes de red que el asociado por correlación al Box 7. **No se ha demostrado qué respuesta produjo el mensaje que vio el usuario.**
2. **Desconexión del Box 7:** está comprobada. Su última comunicación fue el **14/11 a las 01:48:57**, y la desconexión se detectó a las **01:49:23**. Su registro sigue activo y sin revocar. La caída final no coincide con un reinicio del servidor. Falta inspeccionar el equipo Windows para determinar si falló el proceso, su arranque después de actualizar, la red o alguna condición local. La versión 2.1.2 que muestra el panel es la última informada, no una lectura actual del ejecutable instalado.
3. **Defecto reproducible desde 2.1.2:** el intercambio de configuración puede entrar en un ciclo de conflictos. El servidor rechaza una retransmisión legítima después de perder un recibo; el cliente reintenta antes de enviar estado o procesar el ciclo normal de órdenes. Se reprodujeron ambos extremos. **Debe corregirse, pero no hay evidencia suficiente para atribuirle la caída histórica de este PC:** en producción Box 7 sólo tiene la configuración inicial v0, mientras el disparador reproducido usa una revisión local posterior.

Los avisos «Detención sin confirmar» y «captura pendiente de recuperación» tampoco equivalen a un fallo de actualización o de conexión: aparecen incluso en el Box 3 conectado con 2.1.1.

## 2. Material y revisiones examinadas

| Componente | Evidencia |
|---|---|
| Servidor local | Rama `sprint/8`, commit `3b53205`; árbol limpio al iniciar. |
| Servidor desplegado | `734eaf7b070672331dbd8f74049d65324f42d634`, merge que contiene `3b53205`. La comparación de árboles en VPS no mostró diferencias. |
| Agente 2.1.1 | Tag `v2.1.1`, commit `71b537e`, 13/11 01:04:32 −03. |
| Agente 2.1.2 | Tag `v2.1.2`, commit `443b0c5`, 13/11 23:36:43 −03. |
| Agente local actual | `c3cedfd`, versión declarada 2.1.3, 14/11 00:59:46 −03; árbol limpio. |
| Publicación en VPS | `agent-installers/current -> 2.1.3`. Versiones 2.1.2 y 2.1.3 presentes; hashes coincidentes con sus manifiestos. |
| Imagen del usuario | Box 3 conectado, versión reportada 2.1.1; Box 7 sin comunicación, versión reportada 2.1.2. Ambos con recuperación y detención sin confirmar. |

Se revisaron los repositorios `consultoria-bn` y `psycode-agent`, historial, contratos, pruebas, archivos de publicación, servicios, TLS, logs de Nginx/systemd y campos técnicos de la base de producción. Las referencias de líneas corresponden a estas revisiones; el agente implementador debe comprobarlas si el código cambia.

No se inspeccionó el Windows afectado, sus diarios privados, la versión del EXE instalado ni sus tareas programadas. No se ejecutó el instalador Windows ni una captura real. No se recogieron tokens, claves, audio ni contenido clínico para este documento. Las letras A/B usadas abajo son alias de orígenes de red: **una IP no identifica por sí sola un PC**.

## 3. Evidencia operacional y cronología

Todas las horas siguientes están convertidas a **Chile UTC−03:00**; los access logs originales usan UTC.

| Momento | Observación | Interpretación |
|---|---|---|
| 13/11 23:51 aprox. | Publicación 2.1.2 presente en VPS. | El paquete llegó al servidor. |
| 14/11 00:44–00:54 | Varias conexiones WSS aceptadas/cerradas en la secuencia asociada al Box 7. | Hubo intermitencia antes de la caída final. |
| 00:54:31, 01:07:36, 01:17:32, 01:19:30 y 01:32:36 | Reinicios ordenados de ASGI en la ventana inspeccionada. Dos respuestas WSS 502 coinciden con los dos primeros. | Explican interrupciones transitorias; no el cierre final de 01:49. |
| 01:06 aprox. | `current` pasa a 2.1.3. | Desde ese momento existe una actualización para 2.1.2. |
| 01:21–01:44 | Eventos del dispositivo reportan fallos HTTPS y WSS. | Hubo problemas de transporte reportados por el agente; falta detalle local de causa. |
| 01:32:38 | Servicios actuales arrancan; después permanecen estables en la inspección. | No se observó un bucle de reinicios del servidor. |
| 01:44:26 | Reconexión y configuración inicial de Box 7, versión de configuración 0. | El agente pudo autenticarse y negociar con el servidor. |
| 01:44:45, 01:45:16 y 01:45:42 | Consultas de metadatos HTTP 200 del origen A. | El endpoint de actualización funcionaba. |
| 01:45:01 y 01:45:30 | Descargas 2.1.3 HTTP 200, **59.833.955 bytes** cada una, origen A. | El servidor entregó el paquete completo; esto no prueba instalación exitosa. |
| 01:48:57.950849 | Última comunicación registrada de Box 7, versión reportada 2.1.2. | Es el dato que concuerda con la captura. |
| 01:49:23.814622 | Se registra desconexión de Box 7 con causa `UNKNOWN`. | No hay causa técnica local específica acreditada por esa fila. |
| 03:07:28–05:25:39 | 19 consultas de metadatos HTTP 401 desde otro origen, B. | Hubo rechazos de autenticación, pero no deben atribuirse al Box 7 por proximidad temporal. |
| 13:58:13 | Otra descarga completa 2.1.3 HTTP 200, origen A. | HTTPS/descarga pueden funcionar sin que el runtime WSS vuelva a comunicar. |

La correlación de A con Box 7 se basa en el cierre WSS exactamente coincidente con el evento de desconexión y tráfico de eventos del agente. En el conjunto inspeccionado, A tiene **cinco consultas de metadatos y tres descargas, todas 200; ningún 401**. Los otros orígenes suman 31 respuestas 401 de `python-httpx` y una de navegador. Esto orienta la investigación, pero no permite identificar cada solicitud HTTP con un usuario o instalación sin telemetría adicional.

Otros controles de VPS:

- HTTPS público responde 200 con verificación de certificado habilitada. Certificado Let's Encrypt YE2 válido del **13/11 02:25:35 UTC al 19/11 18:25:34 UTC**. No se acreditó un fallo TLS global actual.
- Servicios web, coordinador, fragmentos y almacenamiento activos. En la ventana de journal examinada alrededor de la caída no hubo tracebacks, errores de base bloqueada ni entradas `ERROR` detectadas.
- Registro Box 7 único, administrado, activo, sin revocar y con credencial configurada. No se halló contador de fallos de autenticación correspondiente a su UUID. Esto no prueba que todos los procesos locales usaran la credencial correcta.
- La publicación 2.1.3 es de 59.833.955 bytes. Se verificaron hashes de ambas versiones, no sólo el nombre de la carpeta. Los manifiestos con CRLF se leen correctamente en modo texto; no se encontró un fallo de finales de línea.

## 4. Actualizaciones: diagnóstico y corrección

### 4.1 Qué significa realmente el mensaje

En el agente, `src/psycode_agent/windows_updates.py:27,51,69` emite `UpdateUnavailable` cuando:

- No puede leer/validar el perfil: origen admitido o credencial con formato válido.
- El servidor devuelve **401**, **403** o **404**.

La comparación de versiones ocurre después y distingue correctamente las ternas numéricas. Si no hay una versión superior, devuelve `None`. Un fallo HTTPX de TLS/red muestra otro mensaje («No se pudo consultar Psycode…»). El texto recordado por el usuario, si corresponde a esta rama, prioriza la configuración local y el código HTTP sobre una supuesta falta de release.

El updater no cambió entre 2.1.1, 2.1.2 y el HEAD 2.1.3 inspeccionado; tampoco hubo un cambio de dependencias TLS entre esas versiones que explique por sí solo el incidente.

### 4.2 Descargar desde la web no valida la identidad del agente

Ambos mecanismos usan `backend/apps/operational/windows_installer.py:_published_release`, pero tienen autenticaciones diferentes:

| Acceso | Requisitos |
|---|---|
| Instalador en web | Usuario autenticado con permiso de administrador. |
| Actualización dentro del agente | `GET /api/v1/internal/agent-updates/windows-x64`, HTTPS y `Authorization: Agent <credencial individual>`. |
| Binario para el agente | Mismo endpoint seguido de `/2.1.3`, misma autenticación. |

Metadatos esperados: objeto directo `{version, size, sha256}`, sin envoltorio `data`. Referencias: `windows_installer.py:87–117`, `operational/urls.py:27`, `capture/authentication.py:114`.

### 4.3 Acción de implementación

1. Añadir razones técnicas separadas en el updater: perfil ilegible/inválido, 401, 403, 404, error TLS/red, metadatos inválidos, hash incorrecto. Guardar fecha, operación, versión y código seguro; nunca token, cabecera Authorization o cuerpo privado.
2. Mantener mensajes comprensibles. Para 401 indicar que no se pudo validar el acceso del equipo; para 404 indicar publicación no disponible. Reservar «ya actualizado» para una respuesta válida sin versión superior.
3. Añadir correlación segura entre petición y diagnóstico. El servidor puede registrar UUID si la autenticación fue exitosa; ante fallo, usar un identificador de correlación seguro. No registrar credenciales ni usar IDs no autenticados como prueba de identidad.
4. En el PC afectado, comprobar **con el perfil y usuario Windows reales** el origen HTTP, URL WSS y resultado técnico de una consulta. El perfil instalado normalmente es `%LOCALAPPDATA%\Psycode\config\agent.dpapi`; DPAPI depende del usuario. Comprobar ruta efectiva, permisos y cuenta, sin exportar secretos.
5. Si se reproduce 401, verificar pérdida/renovación de credencial, otro perfil, otro usuario Windows o ejecutable antiguo. No regenerar códigos como primer paso: una nueva vinculación puede invalidar una instalación operativa y destruir evidencia del problema.

No corresponde desactivar TLS, hacer público el endpoint o cambiar el comparador de versiones sin un fallo reproducido. La publicación ausente globalmente no es consistente con los 200 observados.

## 5. Defecto confirmado de configuración y continuidad

### 5.1 Servidor: retransmisión no idempotente

Referencia: `backend/apps/capture/websocket.py:258–296`, especialmente `271–276`.

Secuencia reproducida con `RemoteControl.dispatch`, SQLite y registro sintético reales:

```text
config_local(base_version=0, local_revision=0, heartbeat=30)
  -> config_receipt(version=0, local_revision=0)

config_local(base_version=0, local_revision=1, heartbeat=20)
  -> servidor guarda version=1
  -> config_receipt(version=1, local_revision=1) [se simula recibo perdido]

retransmitir exactamente base_version=0, local_revision=1, heartbeat=20
  -> CONFIG_VERSION_CONFLICT
```

El servidor exige que `base_version` ya alcance `applied.version`, incluso cuando está recibiendo la misma revisión y contenido que acaba de guardar. Si la respuesta se pierde, o el cliente cae antes de persistirla, el cliente no puede conocer esa versión nueva. No requiere corrupción del journal ni un cambio web concurrente.

**Solución:** reconocer la repetición de una operación local ya aplicada y devolver su recibo durable cuando identidad, revisión y contenido coinciden y no ha sido superada por un cambio efectivo posterior incompatible. Conservar conflictos para contenido diferente, revisiones inválidas o autoridad posterior. No eliminar indiscriminadamente la comparación de versiones. Para conflictos reales, definir una respuesta de reconciliación con versión, revisión y estado efectivos.

### 5.2 Agente: el conflicto impide avanzar al ciclo normal

Referencias: `src/psycode_agent/control.py:406–464`; `runtime.py:237–296`.

`configure()` envía `config_local` antes de consumir la configuración remota pendiente. `runtime.run()` llama a `configure()` antes de `loop.tick()`, `status()` y el replay periódico. Un rechazo correlacionado conserva la conexión, espera y vuelve a empezar por la misma operación fallida.

Sonda con runtime y `configure()` reales, transporte simulado y cinco respuestas `CONFIG_VERSION_CONFLICT`:

```json
{"config_local":5,"opens":1,"pending_configuration_consumed":false,"status":0,"ticks":0}
```

Mismo resultado en el código exacto del tag **2.1.2** y en HEAD **2.1.3**. La suite habitual pasa, pero no cubre este caso. El lector WSS y mecanismos locales de seguridad siguen teniendo responsabilidades independientes: no afirmar que desaparece toda protección de detención. Sí queda demostrado que no avanza el ciclo normal ni la publicación de estado.

**Solución:** separar reconciliación de configuración de las tareas críticas. Mantener heartbeat/status, ACK, detenciones autorizadas, recuperación y subidas; acotar los reintentos de configuración con estado técnico visible. **Bloquear nuevos inicios cuando la configuración necesaria no está reconciliada**, sin bloquear las tareas de cierre. No resolverlo llamando indiscriminadamente a `loop.tick()` ni borrando el journal o inventando revisiones.

### 5.3 Relación con el incidente real

Es una regresión funcional verificable en el camino añadido en 2.1.2 y aún presente en 2.1.3. **No está demostrado que causara la caída del Box 7.** La base inspeccionada sólo conserva su baseline de configuración v0, sin la revisión local1 que requiere la reproducción anterior. Las descargas, el último hello y los logs del Windows son necesarios para resolver esa atribución.

## 6. Desconexión y recuperación de captura

### 6.1 Cómo leer la imagen

| Indicador | Fuente y significado |
|---|---|
| Sin comunicación | No hay registro activo con `control_owner` y lease vigente: `operational/views.py:119`. No identifica por sí solo la causa. |
| Versión 2.1.2 | Último `hello` reportado: `capture/websocket.py:112–133`. Puede no ser la versión instalada ahora. |
| Captura pendiente de recuperación | `RECOVERY_REQUIRED` informado por el agente; puede mantenerse visible offline. En el agente depende de intervenciones de control/ACK, no de autenticación: `session_coordinator.py:76`, `runtime.py:262`. |
| Detención sin confirmar | Estado de la última sesión del **box**, con detención/fallo sin cierre acreditado: `capture/services.py:534`, `operational/views.py:125–138`. |
| Pendientes del PC: 0 | Último conteo reportado de pendientes. No acredita cierre de la sesión, ausencia de intervenciones o ausencia de otros archivos locales. |
| Disco y autonomía | Telemetría anterior si el PC está desconectado; no una lectura en vivo. |

La recuperación ya afecta al Box 3 conectado con 2.1.1. No tratarla automáticamente como consecuencia de actualizar a 2.1.2 ni darla por resuelta al restablecer WSS.

### 6.2 Revisión local necesaria para cerrar la causa de Box 7

Recoger primero evidencia técnica bajo el usuario Windows que ejecuta el agente:

1. Ruta y versión real del EXE, versión en `HKCU\Software\Psycode\Agent`, cuenta de ejecución, procesos/supervisor activos y ruta del perfil. Buscar instalaciones o procesos duplicados sin finalizarlos a ciegas.
2. Tarea programada: estado, `Enabled`, último resultado, acción/ruta ejecutable y usuario. El funcionamiento del asistente gráfico no demuestra que el runtime esté arrancado.
3. Archivos `run-failure.json` y `supervise-failure.json` junto al perfil, si existen; `resume-after-update` en el directorio de configuración; `<state>/supervisor-status.json` y `<state>/control-status.json`.
4. `<state>/<box>/configuration/`, `ack-outbox/intervention/`, journals, estado de sesión y manifiestos de fragmentos. Extraer sólo códigos, fechas, revisiones y campos técnicos necesarios; conservar los originales privados.
5. Contrastar la hora de descarga 01:45, el último estado 01:48:57, el resultado del instalador y el primer intento de arranque posterior. Un HTTP 200 del binario no prueba instalación, verificación local ni reinicio.
6. Correlacionar código WSS: `CONTROL_CREDENTIAL_INVALID`, errores TLS, `CONTROL_ROUTE_NOT_FOUND`, `CONTROL_RATE_LIMITED`, `CONNECTION_REPLACED`, `CONFIG_VERSION_CONFLICT` o fallo local. Si no hay intento WSS posterior, priorizar proceso/tarea/arranque; si lo hay, seguir el error concreto.

El instalador usa mantenimiento para detener/reanudar. `installer.iss:91–95` aplaza actualización automática si el gate está ocupado, sin detener al proceso viejo por esa rama. `windows_install.py:174` reanuda usando `resume-after-update`; fallos de registro/arranque pueden requerir recuperación. **No se encontró una regla que prohíba reiniciar simplemente por `RECOVERY_REQUIRED`**. La actualización fallida o un arranque 2.1.3 que no llega a `hello` son hipótesis concretas, no causas confirmadas.

### 6.3 Recuperación segura de sesiones

Para cada sesión pendiente, contrastar orden de inicio/detención, confirmaciones, cierre local, hora y última secuencia, archivos y aceptación durable del servidor. Reenviar la confirmación o evento de cierre previsto por el protocolo de forma idempotente cuando exista evidencia suficiente. Si no la hay, mantener intervención explícita y escalar.

No forzar `actual_end`/`final_sequence`, fabricar `-1`, borrar journals/colas o desvincular el equipo para quitar los avisos. Conservar la credencial y los pendientes durante una actualización. Para el panel, identificar visiblemente la fecha del último diagnóstico y diferenciar una advertencia histórica de una comprobación actual.

## 7. Plan de trabajo para el agente implementador

| Prioridad | Entrega | Criterio de aceptación |
|---|---|---|
| P1 | Idempotencia de `config_local` en servidor | Recibo perdido después del commit y retransmisión idéntica devuelven el recibo correcto, sin nueva fila ni conflicto espurio. Cambios posteriores incompatibles siguen protegidos. |
| P1 | Continuidad del control ante conflicto en agente | Sigue habiendo status/heartbeat, cierre y ACK; no se ejecutan nuevos inicios inseguros; reconciliación observable y reintentos limitados. |
| P1 operativo | Diagnóstico local Box 7 | Identificar versión/proceso real y primer error después de 01:48:57. Registrar causa con evidencia antes de cambiar identidad o estado persistido. |
| P1 operativo | Recuperación Box 3/7 | Cierre y recepción conciliados con evidencia local/servidor; conservar datos cuando falte confirmación. |
| P2 | Errores diferenciados del updater | Se distingue perfil/401/403/404/TLS/red/sin nueva versión; diagnóstico sin secretos y correlacionable con servidor. |
| P2 | Verificación del instalador y arranque | Actualización 2.1.2→versión corregida preserva identidad/estado y vuelve a enviar hello/status bajo la cuenta real. Fallos de mantenimiento son visibles y recuperables. |
| P2 | Claridad de estado del panel | Telemetría vieja fechada; recuperación independiente de conectividad y del pipeline del box. |

Orden recomendado: guardar evidencia local, corregir los dos defectos reproducidos con pruebas, mejorar diagnóstico, validar actualización en Windows de ensayo y después intervenir el PC real. No asumir que instalar 2.1.3 corrige el defecto de configuración: la reproducción también falla con su código local.

## 8. Verificación realizada y pruebas de aceptación

Pruebas ejecutadas en esta auditoría:

| Prueba | Resultado y alcance |
|---|---|
| Servidor: updater + configuración + WebSocket | **29 aprobadas**, configuración de test, SQLite temporal aislado. |
| Servidor: updater + WebSocket + regresiones de PCs | **28 aprobadas**; tiene solapamiento con la suite anterior, no sumar como 57 casos distintos. |
| Agente: updater + control + TLS + seguridad runtime + configuración | **120 aprobadas** con código actual. Diez pruebas necesitaron permitir sockets localhost; el primer bloqueo del sandbox no fue un fallo del producto. |
| Reproducción servidor: pérdida de recibo | **Defecto confirmado**: retransmisión idéntica produce `CONFIG_VERSION_CONFLICT`. La aserción de reproducción verifica el fallo, no una corrección. |
| Reproducción agente: conflicto repetido | **Defecto confirmado en 2.1.2 y HEAD**: cinco intentos, cero tick/status. Transporte simulado. |
| VPS | Publicación, hashes, TLS, servicios, revisión desplegada, logs y datos técnicos consultados en lectura. |

Comando de la suite principal del servidor:

```sh
PSYCODE_TEST_SQLITE_PATH=/tmp/psycode-audit-20261114.sqlite3 \
  .venv/bin/python manage.py test \
  backend.apps.operational.test_windows_installer \
  backend.apps.capture.test_agent_configuration \
  backend.apps.capture.test_websocket_audit \
  --settings=backend.config.test_settings --noinput --verbosity=1
```

Comando ejecutado en el repositorio del agente:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q \
  -p no:cacheprovider tests/unit/test_windows_updates.py \
  tests/integration/test_control.py tests/integration/test_control_tls.py \
  tests/unit/test_runtime_safety.py tests/unit/test_chunk_config.py
```

Antes de entregar una corrección, añadir y aprobar:

- Pérdida del `config_receipt` después de commit; caída del proceso antes de persistirlo; reconexión y reenvío idéntico.
- Misma revisión con contenido distinto y con una actualización web posterior: no sobrescribir configuración silenciosamente.
- Conflicto real repetido manteniendo status/heartbeat, ACK/detenciones y bloqueo de nuevos inicios cuando corresponda.
- Updater con perfil ilegible, 401, 403, 404, TLS inválido, timeout, versión igual/inferior/superior, tamaño/hash incorrecto y cambio de release entre consulta y descarga.
- Windows empaquetado: actualizar desde 2.1.1 y 2.1.2, durante recuperación pendiente y durante captura, conservando credencial y estado; verificar tanto aplazamiento como reanudación.
- Cortar/restaurar red y reiniciar ASGI: identidad estable, reconexión y status recuperados. Validar los casos de proceso duplicado y tarea deshabilitada.
- Confirmar recepción/cierre sintéticos completos; una descarga o conexión exitosa no basta para acreditar el flujo de captura.

Las suites aprobadas no sustituyen una prueba del EXE Windows ni una integración completa entre releases empaquetadas. Esta auditoría no acredita el estado físico del micrófono, OBS, la red del PC o su almacenamiento actual.

## 9. Reproducciones para convertir en regresiones

### Servidor: dentro de un Django TestCase aislado

El siguiente fragmento reproduce el comportamiento actual. La prueba de corrección debe cambiar la última aserción para exigir el mismo recibo sin error y verificar que no aumente el número de filas.

```python
from uuid import uuid4
from unittest.mock import patch
from backend.apps.capture.pc_registry import create_agent
from backend.apps.capture.authentication import authenticate_agent_header
from backend.apps.capture.websocket import RemoteControl
from backend.apps.capture.protocol import envelope

agent, token = create_agent(name='PC sintético auditoría', box='box-3')
control = RemoteControl(authenticate_agent_header(('Agent ' + token).encode()), uuid4())
control.open()
control.config_supported = True
with patch('backend.common.audit.AuditWriter.emit'):
    control.dispatch(envelope('config_local', {
        'base_version': 0, 'local_revision': 0,
        'effective_config': {'heartbeat_interval': 30},
    }))
    message = envelope('config_local', {
        'base_version': 0, 'local_revision': 1,
        'effective_config': {'heartbeat_interval': 20},
    })
    first = control.dispatch(message)
    assert first == ('config_receipt', {'version': 1, 'local_revision': 1})
    with self.assertRaisesRegex(ValueError, 'CONFIG_VERSION_CONFLICT'):
        control.dispatch(message)
```

### Agente: diseño exacto de la sonda ejecutada

Se usó `runtime.run()` real y una subclase de `WebSocketControl` que conserva `configure()` real. `open()` prepara un contexto usable con `agent.config.v1` y una configuración entrante pendiente; `_request()` cuenta cinco envíos `config_local`, devuelve un `ControlRejected('CONFIG_VERSION_CONFLICT', correlated=True)` en cada uno y señala parada en el quinto. Se cuenta `AgentLoop.tick()` y `status()`, se simulan backend/uploader y se elimina la espera aleatoria. Todo usa un directorio de estado temporal.

Resultado esperado del defecto: `opens=1`, `config_local=5`, `ticks=0`, `status=0`, configuración entrante sin consumir. Para la regresión, exigir progreso de tareas críticas y reconciliación explícita; no exigir simplemente cinco ticks capaces de iniciar captura sin validar la configuración.

## 10. Límites que deben permanecer explícitos

- Confirmado: publicación 2.1.3 sana en el momento de inspección; consultas/descargas 200; rechazos 401 de otros orígenes; Box 7 dejó de comunicar; defecto de configuración reproducido en ambos repositorios.
- No confirmado: respuesta exacta que vio el usuario, identidad de cada petición fallida, resultado de instalación en Windows y causa final de la desconexión.
- No se detectó evidencia para culpar al comparador de versiones, a un certificado global vencido, a una credencial revocada de Box 7 o a una caída permanente de la VPS.
- Ausencia de errores en los logs consultados no demuestra ausencia de todo fallo histórico. El siguiente paso decisivo es la evidencia local del PC, no regenerar credenciales ni borrar estado.
