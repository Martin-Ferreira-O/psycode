# SCRUM-72 — Especificación de integración del agente del box

> Actualización de separación: [operación vigente](../docs/OPERACION-SEPARADA.md). Agente en el repositorio independiente `psycode-agent`; control WS autenticado, audio v1/v2 y agenda durable. Las instrucciones históricas incompatibles quedan sustituidas por ese runbook.


Fecha: 2026-10-24. Destinatario: responsable de **Capturar y enviar fragmentos
desde el box**. Este documento entrega el contrato disponible de SCRUM-71 y
SCRUM-73; **no implementa SCRUM-72**.

Fuente de verdad HTTP: [API_CONTRACTS.md, sección 5](../API_CONTRACTS.md#5-ingesta-interna-de-fragmentos).
Control de sesiones: [README de captura](../backend/apps/capture/README.md) y
[BoxAgentControl](../backend/apps/capture/ports.py).

## 1. Qué está disponible y qué falta acordar

| Integración | Estado al hacer pull |
|---|---|
| Recepción de fragmentos SCRUM-73 | Implementada: `POST /api/v1/internal/fragments`. Incluye autenticación, validación, idempotencia y cola SQL. |
| Ciclo de sesiones y órdenes SCRUM-71 | Implementado en el backend mediante `BoxAgentControl`, con órdenes persistentes y confirmaciones idempotentes. |
| Transporte remoto de órdenes, confirmaciones, heartbeat y fallos | Implementado mediante WSS `/ws/v1/agents`, identidad Agent, lease SQL y ACK durable. Véase [control vigente](CONTROL-Y-AUDIO.md). |
| Duración y solapamiento de fragmentos | Perfil inicial configurable 10/1 s; metadatos temporales y validación de ventana en audio v2. |
| Formato de archivo aceptado | Definido: WAV RIFF, PCM lineal, mono, 16 kHz, 16 bits little endian. |
| URL del ambiente y credencial real por box | Se entregan por configuración y canal privado; el código no confirma que exista un despliegue operativo. |

La ingesta está disponible en código desde `d3f88db` y `b0b127b`; el contrato y
la operación están documentados en `e9d9225`. Hacer pull de la rama que contenga
esos cambios y los posteriores. En el backend se debe aplicar `manage.py migrate`
y configurar los agentes antes de probar contra un ambiente real.

## 2. Enviar un fragmento a SCRUM-73

**Método:** `POST`. **Ruta:** `/api/v1/internal/fragments`, sin barra final.
**Transporte:** HTTPS en el ambiente real. **Cuerpo:** `multipart/form-data`.
Dejar que el cliente HTTP genere el boundary y cierre el multipart completo.

Cabecera:

```http
Authorization: Agent <agent_id>.<secret>
```

Es una credencial de máquina vinculada a un único box. No usar JWT de
profesionales, cookies, query string ni campos adicionales para autenticar.
El agente conserva el token completo de forma privada. El backend recibe por
`CAPTURE_AGENTS` el identificador, box y SHA-256 hexadecimal del token completo
`<agent_id>.<secret>`, sin `Agent `. No enviar ese hash como token.
Provisionar un secreto aleatorio de al menos 32 bytes codificado en base64url
sin padding; las restricciones completas están en el contrato principal.

Enviar exactamente estos siete campos, una sola vez cada uno:

| Campo multipart | Valor que debe generar/conservar el agente |
|---|---|
| `archivo` | Un archivo WAV finalizado y no vacío, con cabecera RIFF y longitudes consistentes. No enviar PCM crudo, vídeo ni un archivo todavía en escritura. |
| `box` | `box-3`, `box-4`, `box-5`, `box-6` o `box-7`; debe coincidir con la identidad autorizada. Configurable sin cambiar código. |
| `session_id` | UUID recibido en la orden de SCRUM-71. No generarlo ni reemplazarlo durante un reintento. |
| `secuencia` | Decimal consecutivo desde `0` por sesión, hasta `9223372036854775806`; sin decimales, espacios ni ceros iniciales. |
| `formato` | Texto exacto `wav`. |
| `checksum` | SHA-256 de **todos los bytes del WAV definitivo**, incluida la cabecera: 64 caracteres hexadecimales en minúsculas, sin prefijo. |
| `captured_at` | Fecha/hora original de captura con zona horaria, máximo 40 caracteres, por ejemplo `2026-10-24T15:00:10Z`. Conservarla en los reintentos; no sustituir por la hora de envío. |

`captured_at` es obligatorio aunque no aparezca entre los metadatos enumerados
en la descripción de SCRUM-72. El backend lo necesita para validar fragmentos
que llegan después de solicitar la detención. Debe estar dentro de la ventana
real permitida y no retroceder respecto del fragmento anterior. No usar la hora
de subida ni la de cierre del archivo si ya quedaron fuera de esa ventana.
La interpretación exacta de este instante para fragmentos con solapamiento se
debe acordar según la sección 6.

Límites y orden:

- Archivo: máximo **25 MiB (26.214.400 bytes)** por defecto, incluida su cabecera.
  El ambiente puede configurar otro límite; confirmarlo antes del despliegue.
- Multipart completo: límite del archivo más 64 KiB. No agregar campos propios.
- La sesión debe pertenecer al box, tener inicio real confirmado y estar
  `activa` o `finalizando` para aceptar fragmentos nuevos.
- Enviar en orden y resolver la aceptación de N antes de avanzar a N+1 es la
  estrategia más simple compatible con el backend. Los saltos se rechazan.
- No llamar además a `accept_sequence()` para un archivo enviado por HTTP:
  SCRUM-73 registra la secuencia y crea el trabajo en una sola transacción.

Ejemplo; las variables se cargan desde configuración privada y el manifiesto
local del fragmento:

```sh
curl --request POST "$PSYCODE_INTERNAL_BASE_URL/api/v1/internal/fragments" \
  --header "Authorization: Agent $PSYCODE_AGENT_TOKEN" \
  --form 'archivo=@fragment.wav;type=audio/wav' \
  --form "box=$PSYCODE_BOX" \
  --form "session_id=$CAPTURE_SESSION_ID" \
  --form "secuencia=$FRAGMENT_SEQUENCE" \
  --form 'formato=wav' \
  --form "checksum=$FRAGMENT_SHA256" \
  --form "captured_at=$FRAGMENT_CAPTURED_AT"
```

## 3. Qué confirma la recepción y cuándo borrar el archivo local

Una aceptación nueva devuelve **201**. Un reintento idéntico devuelve **200**
con la misma confirmación. En ambos casos, archivo y trabajo ya fueron
aceptados de forma durable por el backend. No significa que el análisis terminó.

Ejemplo de respuesta; UUID, checksum y fechas son ilustrativos:

```json
{
  "success": true,
  "data": {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "session_id": "11111111-1111-4111-8111-111111111111",
    "box": "box-3",
    "secuencia": 0,
    "formato": "wav",
    "checksum": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 364,
    "accepted_at": "2026-10-24T15:00:20Z",
    "estado": "aceptado"
  },
  "message": "Fragmento recibido",
  "timestamp": "2026-10-24T15:00:20Z"
}
```

Antes de eliminar el archivo, el agente debe comprobar HTTP 200/201,
`success=true`, `data.estado=aceptado` y que sesión, box, secuencia, formato,
checksum y tamaño correspondan al fragmento enviado. Guardar durablemente la
confirmación/estado local antes de eliminarlo permite recuperarse tras reinicios.
No basta con abrir la conexión, terminar el upload o recibir un cuerpo ilegible.

Si hay timeout, desconexión, respuesta incompleta o error 5xx, la aceptación
puede ser incierta: **conservar el archivo y reintentar exactamente el mismo
fragmento**. No regenerar el WAV, reescribir su cabecera, cambiar la secuencia,
UUID o fecha. La clave de idempotencia es `(session_id, secuencia)`; no se
requiere una cabecera `Idempotency-Key`.

Para sobrevivir reinicios, SCRUM-72 deberá mantener una cola/manifiesto local
privado con archivo, sesión, box, secuencia, formato, checksum, `captured_at`,
intentos y confirmación. Este documento no implementa esa cola.

## 4. Errores y política de reintento que debe implementar el agente

Los errores tienen `success=false` y `error={code, message, details}`. Decidir
por `error.code`, sin depender del texto de `message`. El catálogo completo
está en [API_CONTRACTS.md](../API_CONTRACTS.md#errores).

| Resultado | Conducta esperada de SCRUM-72 |
|---|---|
| 200/201 con confirmación válida | Registrar aceptación y eliminar el archivo local. |
| Timeout, desconexión o 5xx | Conservar y reintentar sin modificar identificación ni bytes, con backoff y un máximo configurado. Al agotarlo, registrar/comunicar un fallo técnico por el transporte que se acuerde. |
| 401 `AUTH_REQUIRED` / `AUTH_INVALID_TOKEN` | Revisar provisión o rotación de la credencial. No repetir indefinidamente con el mismo token inválido. |
| 403 `AUTH_FORBIDDEN` | Revisar box configurado e identidad asignada. No cambiar de box para eludir el rechazo. |
| 404 `SESSION_NOT_FOUND` | Revisar sesión y pertenencia al box con el coordinador; no inventar otro UUID. |
| 409 `SEQUENCE_OUT_OF_ORDER` | Si falta una secuencia anterior, resolverla primero. Si supera la última declarada, no es un rechazo recuperable reenviando ese número. |
| 409 `SEQUENCE_CONFLICT` | Fallo de consistencia: conservar evidencia técnica y archivo privado. No sobrescribir ni renumerar automáticamente. |
| 409 `SEQUENCE_ALREADY_REGISTERED` | Se registró la secuencia por el puerto antiguo sin trabajo. Coordinar integración; no llamar ambos caminos para el mismo fragmento. |
| 409 de estado/ventana/fecha | No reintentar ciegamente: revisar sesión, tiempo original y cierre. Una sesión fallida no se reactiva enviando audio. |
| 400, 413, 415 o 422 | Corregir configuración/serialización/producción del archivo según el código. Conservarlo sin marcarlo aceptado. No modificar un fragmento de aceptación incierta para reutilizar su clave. |

Los valores de máximo de intentos, backoff, timeout HTTP y política de disco
local no están definidos por esta API: acordarlos/configurarlos en SCRUM-72.
No borrar pendientes por agotar reintentos; definir explícitamente su retención
y recuperación. No registrar tokens, audio, transcripciones, nombres originales
ni respuestas libres de OBS/proveedores en logs o mensajes de error.

## 5. Órdenes de SCRUM-71 y cierre de sesión

**Esto es un contrato interno de Python, no una API HTTP ya publicada.**
El adaptador remoto deberá invocar `BoxAgentControl` en el backend y fijar el
box desde una identidad autenticada. El agente no comparte ni accede al SQL
del backend. No hay todavía rutas `/commands`, `/ack`, `/heartbeat` o similares.

Una orden `Command` contiene:

| Campo | Semántica |
|---|---|
| `command_id` | UUID estable para deduplicar la ejecución y su confirmación. |
| `session_id` | UUID de captura que deben llevar todos los fragmentos. |
| `box` | Box destinatario; rechazar órdenes ajenas. |
| `kind` | `inicio` o `detencion`. |
| `scheduled_start`, `scheduled_end` | Ventana autorizada, con zona horaria. |

Las órdenes se entregan **al menos una vez** y pueden repetirse tras una caída.
SCRUM-72 debe deduplicar por `command_id`, también después de reiniciar, y no
volver a iniciar OBS por una orden ya ejecutada. Rechazar inicios fuera de su
ventana y aplicar detenciones solo a la sesión indicada.

| Operación interna | Datos que necesita el adaptador |
|---|---|
| `commands(box)` | Obtiene órdenes pendientes y registra su entrega. |
| `acknowledge(box, command_id, success=True, occurred_at=...)` | Confirma inicio realmente ejecutado; la sesión pasa de `iniciada` a `activa`. Conservar el instante real para reintentos. |
| `acknowledge(..., success=True, occurred_at=..., last_sequence=N)` | Confirma detención ejecutada y declara la última secuencia final. `N=-1` si no se generó ningún fragmento. |
| `acknowledge(..., success=False, error_code=...)` | Informa fallo de ejecución con código técnico permitido, sin error libre. |
| `heartbeat(box, session_id)` | Informa actividad; no revive sesiones vencidas. |
| `interrupted(box, session_id, error_code=...)` | Informa interrupción; el backend marca fallida la sesión y genera detención de limpieza. |

Códigos técnicos admitidos actualmente: `AGENT_START_FAILED`,
`AGENT_STOP_FAILED`, `AGENT_INTERRUPTED`, `AGENT_UNAVAILABLE`,
`SESSION_ABANDONED`, `FINAL_SEQUENCE_TIMEOUT`. No inventar códigos OBS o HTTP
para esos campos; acordar su mapeo con el backend. Un fallo de detención se
reentrega con la misma orden; una limpieza posterior exitosa no reactiva una
sesión fallida.

Secuencia de integración:

1. Recibir orden de inicio válida, ejecutar la captura y confirmar su inicio
   real. No subir secuencias nuevas mientras el backend siga en `iniciada`.
2. Finalizar cada WAV y guardar sus bytes/metadatos estables. Enviarlo por
   SCRUM-73 en orden y eliminarlo solo después de confirmar aceptación.
3. Al recibir detención, finalizar el fragmento de cierre según la política
   de corte acordada; dejar de generar secuencias y fijar N de forma durable.
4. Enviar pendientes y confirmar la detención con `last_sequence=N` y su
   instante real. El backend admite confirmación y uploads en cualquiera de
   los dos órdenes; SCRUM-72 puede intentar vaciar pendientes antes, sin
   retrasar la confirmación indefinidamente si falla el envío.
5. Desde que se declara N no puede generarse ni enviarse ninguna secuencia
   mayor. El backend completa cuando recibió la detención y todas las
   secuencias `0..N`, independientemente del procesamiento posterior.

Plazos predeterminados actuales del backend:

| Plazo | Valor |
|---|---|
| Confirmación de inicio | 120 s desde autorización. |
| Ausencia de actividad | 120 s desde última actividad aceptada. |
| Finalización | 300 s desde solicitud de detención; los heartbeats no extienden este plazo. |

El polling de órdenes no sustituye un heartbeat de sesión. Acordar su frecuencia
y los plazos efectivos del ambiente: un fragmento largo o una cola grande no
debe provocar abandono por silencio. Si vence la finalización, el backend puede
rechazar pendientes nuevos; conservarlos no garantiza que puedan subirse luego.

## 6. Acuerdos necesarios antes de cerrar la integración real

| Pendiente | Qué debe quedar especificado entre responsables |
|---|---|
| Transporte de control SCRUM-71 ↔ agente | Implementado: [WS 1.0](CONTROL-Y-AUDIO.md), separado del transporte HTTPS de archivos. Validación institucional pendiente. |
| Duración | Segundos por fragmento y tratamiento del primero y del último incompleto. El límite de 25 MiB es de tamaño, no una duración acordada. |
| Solapamiento | Segundos/muestras, qué audio se repite y cómo se representa en el futuro consumidor. La API actual no admite campos `overlap`, `start`, `end` o `context_start`. Si son necesarios, versionar/ampliar el contrato antes de enviarlos. |
| Tiempo de captura y corte | Instante representado por `captured_at` con solapamiento, precisión, reloj sincronizado y corte al detener/revocar. Debe respetar inicio real y límites del backend; no usar el instante tardío de upload. |
| Configuración del agente | Box, URL backend, credencial, conexión/credencial OBS, directorio local privado, duración, solapamiento, timeout, intentos, backoff y heartbeat. Los nombres vigentes están en el `.env.example` y README del paquete `psycode-agent`. |
| Operación ante fallos | Límites de disco, retención/recuperación de pendientes agotados, reinicio, mapeo de fallos OBS/backend y mecanismo para comunicarlos sin notificaciones clínicas. |
| Ambiente compartido | URL, certificados, provisión de cada box, coordinador en ejecución y plazos efectivos. `runserver` no inicia el coordinador. |

Hasta resolver transporte y parámetros de segmentación, SCRUM-72 puede avanzar
con adaptadores simulados y pruebas del envío, pero no debe dar por completada
la recepción real de órdenes ni inventar endpoints o valores definitivos.

## 7. Pruebas de integración esperadas en SCRUM-72

- Configurar dos boxes sin modificar código; impedir órdenes o envíos ajenos.
- Simular OBS por WebSocket: inicio, detención, desconexión y fallos, sin
  credenciales reales ni dependencia de una interfaz gráfica del agente.
- Generar WAV con el perfil y segmentación acordados; verificar primera/última
  secuencia, solapamiento, checksum y timestamps estables.
- Backend simulado: 201, reintento 200, aceptación cuya respuesta se pierde,
  timeout, 5xx, credencial inválida, salto y conflicto de secuencia.
- Confirmar que no se borra un archivo sin respuesta válida; recuperar cola
  local e identificadores después de reiniciar el agente.
- Repetir una orden de inicio/detención y comprobar que no se ejecuta dos veces;
  conservar su confirmación original y el `last_sequence` declarado.
- Detener con pendientes y con cero fragmentos (`last_sequence=-1`); no crear
  una secuencia posterior y respetar los plazos de finalización.
- Agotar reintentos y comunicar solo códigos técnicos, sin audio, contenido
  clínico ni secretos en logs o errores.

Las pruebas ya disponibles del backend se pueden ejecutar con:

```sh
uv run python manage.py test backend.apps.capture --settings=backend.config.test_settings --noinput
```

No necesitan OBS, MongoDB ni credenciales reales; no reemplazan las pruebas
propias del agente ni la validación de hardware/red institucional pendiente.
