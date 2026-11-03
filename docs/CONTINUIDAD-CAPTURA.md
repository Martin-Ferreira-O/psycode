# Continuidad de captura y recuperación de pendientes

La autorización sigue definiendo exclusivamente cuándo se puede capturar. Una
caída de HTTPS o WSS no amplía esa ventana y ya no convierte, por sí sola, una
sesión en fallida. El agente aplica el término local y conserva los archivos y
sus metadatos para enviarlos después. La recepción central y el procesamiento
pueden continuar una vez terminada la captura.

## Tres ciclos independientes

Los estados legados `iniciada`, `activa`, `finalizando`, `completada` y `fallida`,
los DTO de control y los recibos de ingesta existentes conservan sus nombres.
`completada` sigue indicando que se conoce el fin y se recibieron todas las
secuencias declaradas; no acredita que hayan terminado los análisis.

La proyección aditiva de `GET /api/v1/internal/sessions/<session_id>` autentica
al agente y restringe la consulta a su box. Expone:

| Campo | Valores y significado |
| --- | --- |
| `capture` | `start_unconfirmed`, `active`, `stop_unconfirmed` o `finished`: evidencia física de captura y detención. |
| `reception` | `pending`, `intervention_required` o `complete`: faltan datos o el manifiesto final, se necesita intervención o ya están todas las secuencias. |
| `processing` | `pending`, `failed` o `complete`: estado agregado de los trabajos centrales; permanece pendiente mientras falte recibir datos. |
| `job_counts` | Conteos por estado de `FragmentJob`: pendiente, procesando, completado y fallido. |
| `diagnostic_code` | Diagnóstico operativo separado de un fallo real de captura. |
| `error_code` | Fallo real de la sesión, si existe. No se reemplaza por un corte de red. |
| `backlog_alert` | `notice` desde 15 min, `warning` desde 24 h y `critical` desde 72 h de recepción incompleta después del corte; vacío antes. |

Los tiempos de inicio/detención de control, la secuencia esperada, la secuencia
final y el límite de recepción también se incluyen. Esta API no expone rutas
privadas de audio, nombres recibidos ni contenido clínico.

## Desconexión y término de captura

La configuración central predeterminada es:

| Variable | Valor | Efecto |
| --- | --- | --- |
| `CAPTURE_HEARTBEAT_SECONDS` | 30 s | Frecuencia anunciada de heartbeat. |
| `CAPTURE_INACTIVITY_TIMEOUT_SECONDS` | 90 s | Diagnóstico `CONTROL_DISCONNECTED`; no detiene ni invalida la captura autorizada. |
| `CAPTURE_START_TIMEOUT_SECONDS` | 120 s | Diagnóstico `START_CONFIRMATION_PENDING`; conserva la posibilidad de confirmar una ejecución histórica. |
| `CAPTURE_FINALIZATION_TIMEOUT_SECONDS` | 300 s | Diagnóstico `STOP_CONFIRMATION_PENDING`; no descarta pendientes. |
| `CAPTURE_RECEPTION_GRACE_SECONDS` | 604800 s / 7 días | Plazo automático de recepción desde el corte real o autorizado más temprano. |

Una confirmación de inicio atrasada registra su instante real y nunca vuelve a
activar una sesión que ya está finalizando o fallida. La detención autónoma al
término autorizado puede confirmarse aunque el coordinador central haya creado
la orden después de ese instante. Se conservan la deduplicación de órdenes y
las reglas de confirmaciones contradictorias.

El box se libera únicamente cuando existe evidencia de detención física. Una
recepción pendiente de la sesión A puede coexistir con una captura B autorizada
posteriormente. El vencimiento del horario, por sí solo, no prueba que OBS haya
quedado detenido.

## Evidencia física sin inventar un manifiesto

El servidor anuncia las capacidades aditivas `agent.events.v1` y
`sessions.capture-ended.v1` en `ready`. Los agentes nuevos pueden usar:

```text
POST /api/v1/internal/sessions/<session_id>/capture-ended
Authorization: Agent <identidad>.<secreto>
```

```json
{
  "occurred_at": "2026-11-02T16:00:00+00:00",
  "last_sequence": null,
  "reason_code": "RECOVERY_STOPPED"
}
```

Los motivos permitidos son `AUTHORIZATION_ENDED`, `AGENT_STOPPED`,
`AGENT_INTERRUPTED`, `RECOVERY_STOPPED`, `DISK_LOW` y `SHUTDOWN`.
`last_sequence` admite un entero desde `-1` o `null` si los registros no permiten
conocerlo. `-1` significa que se sabe que no hubo fragmentos; no sustituye un dato
desconocido.

La evidencia guarda `actual_end` y `capture_end_reason` sin fabricar un ACK
exitoso de una orden. Si se desconoce la secuencia final, marca
`FINAL_SEQUENCE_UNKNOWN`, requiere intervención para resolver el manifiesto y
permite la siguiente sesión una vez físicamente detenida. Todavía puede recibir
fragmentos válidos y consecutivos dentro del plazo; no declara la recepción
completa sin secuencia final conocida.

El mismo reporte es idempotente. Se puede enriquecer posteriormente una
secuencia final desconocida con su valor recuperado. Cambiar la fecha de fin,
el motivo o una secuencia final ya conocida produce conflicto. El agente debe
reutilizar su fecha durable de detención tanto en este reporte como en el ACK
de detención, si ambos se envían.

Un fallo real conserva `fallida` y su código. Cuando la detención física queda
confirmada, el servidor admite sus fragmentos previos al corte y conserva el
resultado fallido de captura. No vuelve a habilitar la captura por recibirlos.
Los reportes con motivo `AGENT_INTERRUPTED` o `DISK_LOW` registran ese fallo sin
depender de una comunicación WSS adicional; la causa específica permanece en
`capture_end_reason`, incluso si antes llegó el ACK de detención legado.

## Recepción después de siete días

Al agotarse el plazo se registra `RECEPTION_INTERVENTION_REQUIRED`. Los nuevos
fragmentos se rechazan con ese código hasta intervención del operador. No se
borra el audio local, no se cierra la sesión de forma irreversible y los
reintentos de fragmentos que ya fueron aceptados siguen obteniendo el recibo
original, incluso después del plazo.

Para habilitar recepción adicional, desde un entorno central autorizado:

```sh
uv run python manage.py resume_capture_reception \
  --box box-3 --session-id <UUID> --days 7
```

`--days` admite entre 1 y 30; se mide desde la intervención. El comando registra
el evento durable `capture.reception.resumed` y guarda
`reception_extended_until`. No modifica la ventana autorizada, no inicia OBS y
no elimina pendientes. También permite recuperar explícitamente sesiones de
versiones anteriores que terminaron por `AGENT_UNAVAILABLE`,
`SESSION_ABANDONED` o `FINAL_SEQUENCE_TIMEOUT`; no convierte automáticamente
otros fallos en sesiones activas. Si existiera una captura incompatible aún sin
confirmar, la operación se rechaza hasta reconciliarla.

Si el agente ya marcó los rechazos como intervención local, ejecutar
`psycode-agent retry-uploads` con el agente detenido después de habilitar la
recepción central. Este comando restablece los intentos y conserva bytes,
identificadores y fechas. No modificar manualmente journals ni manifiestos.

Los campos nuevos de `CaptureSession` son `diagnostic_code`,
`reception_intervention_at`, `reception_extended_until` y `capture_end_reason`.
El índice exclusivo por box comprende solo sesiones abiertas sin `actual_end`;
una sesión físicamente detenida puede seguir en `finalizando` mientras recibe
pendientes.

## Eventos y diagnóstico

`POST /api/v1/internal/agent-events` recibe lotes técnicos producidos localmente.
El servidor fija PC/box desde la identidad autenticada y deduplica por
`(agent_id, event_id)`. Reenviar el mismo evento conserva `received_at`; cambiar
el contenido de esa identidad produce conflicto y revierte el lote. Se guardan
ocurrencia, recepción, tipo, causa técnica, identificador de caída y duración
cuando se conoce. Los eventos sin una sesión son válidos; los que la indican
deben pertenecer al box autenticado.

```sh
uv run python manage.py capture_health
uv run python manage.py recover_capture_sessions
```

`capture_health` conserva los conteos existentes y agrega `session_lifecycles`,
`backlog_counts` y el último evento de HTTPS/WSS por box en
`last_connection_events`. Solo expone diagnósticos de una lista permitida y
metadatos técnicos. La inspección evalúa los plazos centrales; nunca inicia
captura. `recover_capture_sessions` solicita detención cuando vence la
autorización y actualiza diagnósticos, sin cerrar por mera ausencia de red.

## Despliegue y compatibilidad

1. Desplegar primero el servidor central y ejecutar sus migraciones `0007` y
   `0008`. Conservan las filas previas; no reabren automáticamente sesiones
   históricas fallidas.
2. Reiniciar los procesos centrales para cargar las capacidades y la nueva
   política. Comprobar `capture_health` y el acceso autenticado de un agente.
3. Actualizar los agentes conservando sus raíces privadas de estado y archivos
   pendientes. Usar las capacidades anunciadas para las extensiones nuevas.
4. Reconciliar pendientes históricos que requieran intervención, sin regenerar
   sus bytes, identidad de sesión, secuencias, fechas ni checksums.

Los uploads multipart y sus recibos v1/v2, las credenciales y los mensajes de
control existentes mantienen sus contratos. Los esquemas aditivos están en
`contracts/agent-events-v1.schema.json` y
`contracts/capture-ended-v1.schema.json`; el manifiesto de contratos identifica
sus hashes. Una caída no permite eliminar pendientes ni asignarlos a otra
sesión.

## Verificación y límites

Las pruebas centrales usan audio sintético, persistencia SQL real y reloj
simulado para desconexiones de varios días, ACK retrasados, recepción al límite
de siete días, intervención posterior, evidencia física con manifiesto
desconocido, sesiones consecutivas y separación de procesamiento. Los tests API
comprueban identidad, conflictos, límites de mensajes y diagnóstico sin rutas de
audio.

La autonomía inicial propuesta del agente es **24 horas acumuladas de audio
autorizado**; su capacidad debe incluir solapamiento, metadatos, copias completas
si se habilitan y reserva para cierre. El objetivo de pérdida máxima del audio
todavía en curso ante un apagón es **2 segundos**. Es un objetivo de diseño y de
prueba, no una certificación de hardware: matar un proceso o simular errores de
escritura no reproduce todas las cachés del sistema operativo, el disco, el
firmware o la pérdida de alimentación. La verificación en los PCs Windows/OBS y
su almacenamiento real debe medir y registrar ese límite antes de afirmar que
se cumple en producción.
