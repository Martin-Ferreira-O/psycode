# Sesiones de captura (SCRUM-71)

Persistencia SQL de la autorización de SCRUM-70 hasta el cierre. No lee Excel,
controla OBS, recibe archivos ni ejecuta análisis. Solo almacena identificadores,
box, origen, estados, fechas, números de secuencia y códigos técnicos permitidos.
Los UUID de captura son distintos de las sesiones JWT.

## Integración con SCRUM-70

`OperationalService.authorize_box_capture()` y `authorize_box_transition()`
conservan su contrato de autorización y ahora sincronizan la sesión persistente.
`CaptureAuthorizationService.evaluate_box()` sigue siendo una consulta sin
crear sesiones. Para un coordinador nuevo, usar la composición siguiente:

```python
from backend.config.composition import capture_session_service

# Compartir la MISMA instancia de AgendaService que ya usa SCRUM-70.
coordinator = capture_session_service(agenda_service=agenda)

# En cada tick del coordinador, para los boxes 3 a 7:
session = coordinator.reconcile_box("box-3")
```

El coordinador debe ejecutarse periódicamente y ante cambios de autorización.
La agenda sigue siendo responsabilidad de SCRUM-70; construir otra instancia
vacía de agenda activa su política de respaldo por horario clínico.
No se inicia ningún trabajador en WSGI, AppConfig ni al importar módulos.

La sesión y su orden de inicio se guardan en una transacción, insertando primero
la sesión. La orden solo es visible para otra conexión después del commit.
Un índice único parcial impide dos sesiones abiertas por box, incluyendo
`iniciada`, `activa` y `finalizando`. Otra restricción identifica la ventana
por `(box, origen, inicio programado, término programado)` mientras su
`authorization_ended_at` sea nulo: repetir un tick o reiniciar el proceso no
reabre una sesión completada o fallida dentro de la misma autorización.
Una revocación o cambio de ventana/origen registra el fin de la autorización,
incluso si la sesión ya falló. Una autorización posterior puede crear otra sesión
con un UUID y una orden de inicio nuevos dentro de la misma ventana, una vez
cerrada la anterior y confirmadas las detenciones pendientes. Volver de agenda
al horario de respaldo también permite una nueva sesión en ese horario.

Una revocación, vencimiento o cambio de ventana/origen deja la sesión en
`finalizando`, cancela el inicio pendiente y crea una única detención. El contexto
original se conserva. Una ventana nueva puede iniciar en el próximo tick después
del cierre; no se solapan ventanas durante la finalización.

## Contrato del agente

`ports.BoxAgentControl` define la interfaz interna, implementada por
`CaptureSessionService`. Todos los métodos validan el box y la pertenencia del
identificador recibido. El adaptador futuro HTTP, IPC o mensajería debe autenticar
al agente y fijar el box desde esa identidad. No hay rutas públicas de ingesta ni
se concede acceso mediante el JWT de un profesional. La elección de transporte,
provisión de identidad y ejecución en el box requieren su contrato de integración.

```python
# El adaptador invoca esta interfaz en el backend; no comparte SQL con el box.
from backend.apps.capture.ports import BoxAgentControl

control: BoxAgentControl = coordinator
for order in control.commands("box-3"):
    # Transmitir order al agente; ejecutar por command_id de forma idempotente.
    # Tras recibir la confirmación del inicio:
    if order.kind == "inicio":
        control.acknowledge("box-3", order.command_id, occurred_at=started_at)

control.heartbeat("box-3", session.session_id)
accepted = control.accept_sequence(
    "box-3", session.session_id, number=0, captured_at=captured_at,
)

# Después de recibir una orden de detención y la respuesta del agente:
control.acknowledge(
    "box-3", stop_order.command_id, occurred_at=stopped_at, last_sequence=0,
)
```

| Operación | Contrato |
|---|---|
| `commands(box)` | Tupla de DTO `Command`, sin ORM ni contenido clínico. Registra cada entrega. |
| `acknowledge(box, command_id, ...)` | Confirma la ejecución de una orden previamente entregada; devuelve un DTO `Session`. |
| `accept_sequence(box, session_id, number, captured_at)` | `True` al aceptar; `False` para un reintento idéntico ya aceptado. |
| `heartbeat(box, session_id)` | Actualiza actividad; una sesión vencida se cierra sin revivirla. |
| `interrupted(box, session_id, error_code=...)` | Registra interrupción, marca fallida y genera detención de limpieza. |

Las órdenes llevan `command_id`, `session_id`, `box`, `kind` (`inicio` o
`detencion`) y ventana programada. Se reentregan con los mismos UUID hasta
confirmación; la entrega es **al menos una vez**. El agente debe deduplicar por
`command_id`, aplicar las órdenes exclusivamente a su `session_id` y rechazar
inicios fuera de su ventana. Una consulta no prueba que el agente ejecutó la
orden. Si el backend cae después de publicarla, el siguiente poll la repite.

Las confirmaciones idénticas son idempotentes; las contradictorias se rechazan.
`occurred_at` es el instante real de ejecución con zona horaria, distinto del
instante de recepción. Si se omite, se usa el instante de recepción del backend;
se recomienda enviarlo para respuestas retrasadas. El inicio confirmado permite
`iniciada → activa`. Una respuesta tardía no reactiva sesiones finalizando o
fallidas. Una detención exitosa exige `last_sequence`, desde `0`, o `-1` si no
hubo secuencias. Los fallos usan `success=False` y un código técnico permitido;
nunca se aceptan mensajes de error libres.

Un fallo de detención deja la sesión fallida, conserva el intento en bitácora y
reentrega la misma orden. Una confirmación exitosa posterior puede reconocer la
limpieza; la sesión permanece fallida. Hasta confirmar esa limpieza se bloquean
nuevos inicios en el box. Las detenciones tienen prioridad en las entregas.

## Secuencias y cierre

Las secuencias aceptadas son consecutivas desde `0`. Un salto debe reintentarse
después de aceptar las anteriores. `captured_at` representa un instante de captura,
no la llegada al backend. Debe ser consciente de zona, no futuro, no anterior al
inicio real ni a la secuencia previa, y no posterior al fin programado, revocación
o detención confirmada. Se admiten secuencias retrasadas durante `finalizando`.

Una restricción SQL única `(session_id, number)` y el bloqueo transaccional de
sesión impiden duplicados y actualizaciones perdidas entre procesos. Repetir un
número con distinta fecha es conflicto. Un reintento idéntico no vuelve a generar
eventos ni efectos; devuelve `False`, incluso tras completar la sesión.

Solo se completa cuando existe confirmación exitosa de detención y se han
aceptado **todas** las secuencias hasta `last_sequence`. Ambas llegadas pueden
ocurrir en cualquier orden o concurrentemente. Se rechazan nuevas secuencias en
sesiones completadas o fallidas. No se invoca ningún analizador al aceptarlas.

## Recuperación y bitácora

Ejecutar una pasada al arrancar el coordinador y periódicamente (por ejemplo,
cada 15 segundos) mediante `coordinator.recover()` o el comando:

```sh
uv run python manage.py recover_capture_sessions
```

No inicia sesiones nuevas ni necesita cargar agenda. Valores por defecto:

| Límite | Valor | Resultado |
|---|---|---|
| Confirmación de inicio | 120 s desde autorización | Fallida: `AGENT_UNAVAILABLE` |
| Ausencia de actividad | 120 s desde heartbeat, confirmación o secuencia | Fallida: `SESSION_ABANDONED` |
| Finalización | 300 s desde solicitud de detención, aunque sigan heartbeats | Fallida: `SESSION_ABANDONED` o `FINAL_SEQUENCE_TIMEOUT` |

Se configuran con `start_timeout`, `heartbeat_timeout` y `finalization_timeout`
(objetos `timedelta`) en la composición; el comando acepta los mismos nombres
como `--start-timeout`, `--heartbeat-timeout`, `--finalization-timeout` en segundos.
La entrega de órdenes y las respuestas también verifican vencimientos para
evitar revivir sesiones si un tick se retrasa. Una caída del proceso se detecta
por estos plazos; no se presupone que reiniciar el backend detuvo al agente.

`CaptureEvent` conserva en SQL la bitácora del fin de autorización, creación, órdenes, entregas,
confirmaciones, secuencias aceptadas, finalización y fallos. Cada evento se guarda
en la misma transacción que el cambio y se emite a `psycode.audit` solo después
del commit. Un rollback elimina también el evento; un fallo del logger no pierde
la copia SQL. Esta bitácora técnica se consulta internamente por
`CaptureSession.events`; no modifica el endpoint MongoDB `/api/v1/audit-events`,
que sigue siendo la bitácora de alertas. Los errores son códigos de lista cerrada,
sin excepciones, audio, transcripciones, nombres, pacientes o payloads arbitrarios.

## Instalación y pruebas

```sh
uv run python manage.py migrate
uv run python manage.py test backend.apps.capture backend.apps.operational --settings=backend.config.test_settings --noinput
```

Las pruebas de concurrencia usan `TransactionTestCase`, barreras y conexiones SQL
independientes contra un archivo SQLite de pruebas; no simulan la persistencia.
La configuración existente usa `transaction_mode=IMMEDIATE` y timeout para
serializar escritores SQLite. También se bloquean filas con `select_for_update`
en motores que lo soporten. No se necesitan MongoDB, agentes ni credenciales.
