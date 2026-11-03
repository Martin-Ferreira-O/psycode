# Revisión funcional del servidor tras la separación

27 de octubre de 2026. Revisión local en macOS de
`codex/separacion-agente-servidor`, sobre HEAD
`59b250812459c0bafd775f1edd76e522215f85fa` y los cambios sin commit del checkout.
Se preservaron los cambios de migración existentes y la rama actual. Los cambios
siguen sin commit; no hubo publicaciones ni despliegues.

## Resultado

La separación servidor/agente pasa las comprobaciones automáticas locales
descritas abajo. Se encontraron y corrigieron errores de entrada, limpieza,
despliegue y pruebas que no detectaba la suite ordinaria inicial. Este resultado
no certifica el funcionamiento en el VPS ni en los PCs Windows institucionales.

El servidor se instaló y probó sin `psycode_agent` ni `obsws_python`. La integración
cruzada instaló un wheel explícito del agente en otro entorno y usó HTTP/WebSocket
reales, sin importar su checkout desde el código central. No se modificó el
repositorio hermano durante esta revisión.

## Correcciones

| Problema reproducido o comprobado | Corrección |
|---|---|
| ASGI en producción no tenía un destino de `collectstatic` ni una ruta de estáticos en Nginx. La interfaz depende de JavaScript/CSS. | `STATIC_ROOT=staticfiles`, URL `/static/`, alias de Nginx y paso `collectstatic` documentado. El directorio público queda separado de `.local/`. Prueba de recolección de los assets reales del acceso. |
| Excel aceptado aunque sus citas pertenecieran a otra fecha que `agenda_date`. | Comprobación de la fecha de todas las citas antes de persistir. Prueba de rechazo sin publicar una revisión. |
| Un campo de texto en lugar del archivo de agenda producía HTTP 500. | Validación de `UploadedFile`, respuesta 400 y conservación de la revisión anterior. |
| Las secuencias posteriores a un fragmento fallido terminaban en SQL sin pasar por la eliminación del audio. La limpieza de huérfanos conserva archivos que tienen trabajo asociado. | Finalización mediante el mismo camino que los demás fallos, con limpieza y cierre de contexto, sin llamar proveedores. Prueba de la cadena de fallos. |
| La suite cruzada fallaba con el agente actual: la cola no enviaba sin un inicio confirmado en su journal. | El fixture recorre preparación, ejecución, ACK central y confirmación local del inicio; conserva el requisito de autorización. |
| El acceso no publicaba el estado de carga que verificaba la prueba del navegador. | Estado accesible de carga para acceso y recuperación, conservando el bloqueo de doble envío. |
| La prueba del navegador usaba tokens sintéticos pero dejaba consultas actuales de usuario, lista, detalle y evaluación llegar al backend. | Respuestas sintéticas completas para esos contratos y esperas por los estados de la interfaz. La prueba sigue comprobando errores, redirección y conservación de campos. |
| El servicio de fragmentos tenía `TimeoutStopSec=300`, aunque 300 s es el timeout predeterminado por etapa/solicitud y un fragmento puede hacer varias llamadas JEV. | El ejemplo usa `infinity` para drenar el fragmento sin SIGKILL automático. Se documenta que la parada puede tardar varias llamadas; una cota finita requiere medir el tiempo total y prever recuperación forzada. |

También se actualizó el README principal: la raíz sí tiene interfaz, las alertas
HTTP sí existen, hay recuperación web, agenda SQL y comandos reales de coordinador
y consumidor. `.env.example` apunta la recuperación al servidor local de Django;
el `.env` privado existente se conservó.

## Evidencia propia de esta revisión

| Comprobación | Resultado |
|---|---|
| Suite inicial del servidor | 301 pruebas descubiertas, OK, 5 omitidas. |
| Regresiones nuevas antes de corregir | Tres fallos reproducidos: fecha Excel, archivo de agenda y limpieza de secuencias dependientes. |
| Suite final del servidor | 305 pruebas descubiertas: 300 ejecutadas correctamente y 5 omitidas. |
| Instalación temporal desde `requirements.txt`, con hashes | Aprobada; sin dependencias del agente. Misma suite: 305 pruebas, OK, 5 omitidas. |
| `check` y `makemigrations --check --dry-run` | Aprobados. Sin cambios de modelo pendientes. |
| `scripts/check_boundaries.py` | Aprobado: imports centrales y hashes de contratos. |
| Dependencias exportadas | `requirements.txt` coincide con el export del lock, descontando el encabezado generado. |
| Suite cruzada explícita | Aprobada, incluidos sus seis casos históricos HTTP/ACK. |
| JavaScript con Node | 11 pruebas aprobadas. |
| Navegador Chrome con Playwright | Aprobado: acceso, carga, doble envío, reintentos, estados HTTP, sesión vencida, filtros y selección/registro de evaluación. APIs simuladas y plantillas/scripts reales. |
| Arranque con `DEBUG=false` y base temporal | Migraciones, `collectstatic`, coordinador `--once`, salud y ASGI aprobados. HTTP redirige a HTTPS; la cabecera de proxy confiable permite renderizar la interfaz sin bucle de redirección. |
| Trabajador continuo vacío y SIGTERM | Parada limpia, sin proveedores. |
| `git diff --check` | Aprobado. |

Las cinco omisiones ordinarias son cuatro pruebas con MongoDB real y una carga
optativa de muestras Excel externas. Los fixtures sintéticos de agenda sí corrieron.

Wheel usado por la integración cruzada:

```text
psycode_agent-1.0.0-py3-none-any.whl
SHA-256: 2b3acf48a1d795a2ac496b9ffa89f45faba14a4332b2a681e288947a2d1528d4
```

La suite verificó dos procesos ASGI, sustitución de conexión mediante lease SQL,
reconexión, ACK perdido después del commit, uploads idempotentes, detención y
última secuencia, agenda recibida por HTTP observada por otro coordinador y
runtime autónomo con OBS/FFmpeg simulados. El análisis sintético conserva roles
desconocidos y resultado indeterminado; no se asignó S1 al paciente.

## Límites y comprobaciones antes de producción

- No se ejecutaron Nginx ni systemd en Linux. Se prepararon sus ejemplos; falta
  validar configuración, certificados, permisos, volúmenes y supervisión en el VPS.
- No se ejecutó captura real, OBS/FFmpeg/MediaMTX institucional, Smile real ni
  instalación/inicio de sesión Windows. La integración usa dobles para esos servicios.
- MongoDB real, SMTP real, Speechmatics/JEV y carga de cinco boxes no se validaron.
  No se enviaron datos a proveedores ni se consumieron créditos.
- La prueba de SIGTERM del trabajador fue sobre una cola vacía. El drenaje de un
  fragmento con proveedores reales puede tardar varias llamadas. El ejemplo de
  servicio prioriza conservar una entrega incierta frente a imponer una cota fija.
- La atribución fiable de hablantes sigue siendo necesaria para generar alertas
  clínicas. Los roles desconocidos y la pérdida de contexto tras reinicio conservan
  sus políticas documentadas; no equivalen a un análisis clínico completo.

Los comandos de reproducción y la operación vigente están en
[OPERACION-SEPARADA.md](OPERACION-SEPARADA.md) y en el [README](../README.md).
