# Revisión de instalación y operación de PCs

> Antecedente de revisión: los hallazgos siguientes describen el estado anterior
> a la implementación de esta sesión. Para el comportamiento actualizado, consultar
> [GESTION-DE-PCS.md](GESTION-DE-PCS.md) y [ENTREGA-OPERACION-PCS.md](ENTREGA-OPERACION-PCS.md).

> Aclaración posterior de alcance: el instalador gráfico `.exe` pertenece a la
> siguiente tarea del usuario; sus propuestas aquí son una dirección futura, no
> un requisito para cerrar esta pantalla y API.

Fecha: 8 de noviembre de 2026. Revisión del código local del servidor y de
`psycode-agent`; no acredita el estado de los computadores de la clínica.

Este documento distingue el comportamiento comprobado de la propuesta pendiente.
La guía [GESTION-DE-PCS.md](GESTION-DE-PCS.md) describe el flujo implementado hoy.

## Resultado

Existe una base reutilizable: identidad de máquina, credenciales individuales,
vinculación temporal, reconexión, persistencia local y diagnóstico. Todavía no
equivale a una aplicación Windows entregable a un administrador no técnico.

El mismo programa debe instalarse en cada PC, con identidad, credencial y estado
privados propios. El técnico realiza la instalación inicial; el administrador
consulta funcionamiento y sigue instrucciones sencillas. Una desconexión normal
no requiere volver a vincular, emitir claves ni modificar archivos.

## Hallazgos comprobados

| Hallazgo | Evidencia en código | Consecuencia |
|---|---|---|
| El agente guarda box, credencial y URLs al vincularse. Conserva los otros ajustes. | Agente: `src/psycode_agent/pairing.py`, `pair`. | El código temporal no debe pedirse en cada arranque; vincular no configura por sí solo OBS ni la captura. |
| Hay reconexión con esperas crecientes y variación aleatoria ante errores de conexión. | Agente: `src/psycode_agent/runtime.py`, `run`. | La pérdida de red no justifica renovar credenciales. Los rechazos de control pueden terminar el proceso y necesitan tratamiento diferente. |
| La tarjeta ofrece «Generar nuevo código» en equipos ya registrados. Emitirlo invalida la credencial y la conexión antes del canje. | `backend/apps/web/static/web/js/pcs.js`, `tarjeta`; `backend/apps/capture/pairing.py`, `_issue_code`. | La acción puede convertir una incidencia de red en una instalación que requiere intervención local. |
| El alta de la pantalla exige una sala previamente publicada por el colector. | `backend/apps/capture/pairing.py`, `create_pairable_agent`; `backend/apps/agenda/catalogue.py`. | La preparación de Smile queda expuesta como prerrequisito administrativo; debe resolverse en la puesta en marcha. |
| El mensaje de catálogo vacío pide ejecutar el colector; se muestran IDs técnicos de Smile y comandos. | `backend/apps/web/static/web/js/pcs.js`; `backend/apps/web/templates/web/pcs.html`. | La interfaz traslada trabajo técnico al administrador. |
| El listado consulta `AgentRegistration`; la autenticación también admite identidades antiguas de `CAPTURE_AGENTS`. | `backend/apps/operational/views.py`, `AgentRegistrationListCreateView`; `backend/apps/capture/authentication.py`. | Compatibilidad de autenticación no equivale a visibilidad administrativa de todos los equipos existentes. |
| Se reutiliza el UUID si ya existe un registro administrado del box. Si solo existe la identidad antigua, el alta crea un UUID nuevo. El historial consulta eventos por UUID actual. | `backend/apps/capture/pairing.py`, `create_pairable_agent`; `backend/apps/operational/views.py`, `AgentConnectivityHistoryView`. | Debe definirse una transición explícita para unir la consulta del historial antiguo sin borrar ni reescribir su procedencia. |
| El arranque Windows usa Python y una tarea al iniciar sesión, con tres reinicios por fallo configurados. | Agente: `pyproject.toml`; `scripts/install-startup.ps1`. | Falta un instalador gráfico autónomo y validación de funcionamiento prolongado en Windows. El script no demuestra captura antes del inicio de sesión. |
| El panel carga al abrir y al pulsar actualizar o completar acciones; no tiene actualización periódica. Consulta PCs y salas conjuntamente con `Promise.all`. | `backend/apps/web/static/web/js/pcs.js`. | Puede quedarse mostrando estados antiguos; un error al consultar salas impide completar la actualización de PCs. |

## Diseño propuesto: instalación una vez, operación continua

### Instalación inicial, a cargo del técnico

1. Preparar el servidor, sus migraciones, HTTPS/WSS y los boxes configurados.
   Confirmar las correspondencias reales con Smile sin inventar sus IDs.
2. Instalar el mismo paquete Windows en todos los equipos. El instalador debe
   incluir o verificar los componentes de captura necesarios y presentar errores
   comprensibles; no depender de un checkout, consola o instalación manual de Python.
3. Seleccionar el PC/box desde la web y generar un código de instalación. El
   asistente local recibe el código y guarda la configuración privada. La URL
   institucional puede venir preconfigurada en el paquete y confirmarse al instalar.
4. Verificar micrófono, OBS, almacenamiento, conexión y permisos bajo la cuenta
   que se usará realmente. El código de instalación no prueba que la captura funcione.
5. Configurar inicio y recuperación automática de la aplicación y de sus
   dependencias. Si OBS necesita sesión interactiva, documentar esa condición y
   comprobarla tras un reinicio. No prometer captura sin sesión por convertir el
   agente en servicio.
6. Ejecutar una prueba autorizada con audio sintético y confirmar en la web
   captura, recepción y procesamiento por separado. Guardar versión, box,
   responsable y resultado, sin secretos ni datos clínicos.

La documentación definitiva del instalador debe indicar rutas reales de programa,
configuración y estado; permisos; cuenta de ejecución; actualización; reversión;
desinstalación y recuperación. Esos pasos deben verificarse en Windows antes de
entregar la clínica. Los comandos actuales no sustituyen esa guía del instalador.

### Operación habitual, a cargo del administrador

Una tarjeta por PC, con box y nombre reconocible. Estado principal comprensible,
última comunicación, captura y recepción recientes; detalles de pendientes,
capacidad, procesamiento e historial al ampliar. Conservar accesibilidad y teclado.

| Situación observada | Mensaje y acción administrativa | Responsabilidad del sistema |
|---|---|---|
| Instalación aún no completada | «Pendiente de instalación». Código disponible dentro del asistente. | No presentar este equipo como una caída de un PC que ya funcionaba. |
| Sin comunicación reciente | «Sin comunicación desde… Comprueba que el PC esté encendido y tenga conexión». | Reintentar automáticamente con la misma identidad y credencial; mostrar la causa como desconocida si no hay evidencia. |
| Fallo general del servidor o de la integración | Aviso común y última actualización válida, evitando repetir la misma incidencia en todas las tarjetas. | Recuperar servicios y sincronización; conservar información previa con su antigüedad. |
| Fallo de captura con PC conectado | «No se está recibiendo audio durante la sesión». Mostrar la causa comprobada y un paso sencillo cuando exista. | Diagnosticar micrófono/OBS/captura y recuperar lo recuperable dentro de la autorización. Estar conectado no demuestra audio sano. |
| Disco próximo al límite | «Queda poco espacio para continuar». Mostrar pendientes y autonomía estimada. | Reintentar envíos y aplicar retención segura; conservar audio pendiente. Escalar si requiere intervención. |
| Acceso retirado por el administrador | «Acceso deshabilitado». | Aplicar revocación a conexiones activas y códigos pendientes; no reactivar automáticamente una credencial revocada. |

El servidor no puede distinguir con certeza un PC apagado de una caída de red
solo por ausencia de mensajes. Tampoco puede garantizar un reinicio remoto de
un agente al que no puede llegar. No ofrecer botones que prometan esas soluciones.

### Recuperación y credenciales

- Conservar identidad, credencial, estado y cola tras reinicios, cortes de red y
  actualizaciones. Recuperar envíos sin duplicar ni reasignar audio.
- Mantener los límites autorizados de captura durante las caídas. Recuperación
  automática no concede permiso para iniciar grabaciones nuevas sin autorización.
- Reservar «Instalar PC» para el alta. Poner «Reinstalar o reemplazar» y
  «Deshabilitar acceso» entre acciones excepcionales, con consecuencias claras.
  Renovar un código vencido corresponde a una instalación incompleta.
- Separar renovación planificada y revocación de emergencia. La primera debe
  preparar la credencial, guardarla duraderamente en el agente y confirmar la
  transición antes de retirar la anterior. Acotar cualquier período de transición
  y permitir cancelarlo. La revocación explícita sí debe ser inmediata.
- Diseñar la negociación para recuperarse de respuestas perdidas y reinicios sin
  almacenar secretos en claro en el servidor ni reutilizar códigos entre equipos.
  Probar concurrencia con revocación y evitar dos instalaciones operativas para
  una misma identidad. Esta negociación todavía no está implementada.
- No introducir vencimientos de credenciales que exijan una visita periódica
  del técnico. Cualquier renovación automática requiere su protocolo recuperable.

### Smile y equipos existentes

El registro central de PCs y la integración de agenda tienen responsabilidades
distintas. Smile confirma la correspondencia de salas y aporta agenda; no debe
ser un requisito para consultar el estado de PCs ya conocidos.

Durante la puesta en marcha se debe disponer del registro de boxes configurados
(3–7 en el criterio original) y de los equipos existentes. Si falta una
correspondencia de Smile, conservar el PC visible y marcar la integración como
pendiente. Bloquear únicamente las operaciones que dependan de esa correspondencia.
No fabricar agendas ni autorizar captura a partir de una sala no verificada.

La falta de un catálogo nuevo no debe borrar el último catálogo correcto. Una
sincronización completa que retire una sala requiere un tratamiento explícito de
configuración; no se debe ocultar ese conflicto ni continuar capturando sin permiso.
En operación, mostrar «La agenda no se ha podido actualizar desde…» cuando esa
sea la evidencia, con actualización automática y escalamiento técnico disponible.
No pedir al administrador que ejecute un colector.

Para incorporar agentes antiguos, inventariar primero las identidades y huellas
ya configuradas, detectar conflictos y hacer una transición compatible. Un PC
que ya funciona no debe quedar deshabilitado por abrir la pantalla o preparar
una migración. La asociación con el registro administrado debe mantener una
referencia explícita a la identidad anterior para consultar eventos y audio
históricos, sin atribuirlos a otro PC por compartir un box.

Solo el colector designado necesita acceso a Smile. Todos los PCs usan el mismo
programa; esa responsabilidad especial se configura en la instalación técnica.
Separar ese proceso de un PC de captura puede evaluarse después, sin convertirlo
en requisito de esta corrección ni duplicar colectores activos.

## Orden de trabajo y coordinación con Jira

1. Completar inventario y compatibilidad del registro central para equipos nuevos
   y antiguos. Mantener la API y la separación entre captura, recepción y análisis.
2. Separar la consulta de PCs de fallos del catálogo; simplificar estados y
   acciones; actualizar automáticamente y marcar información desactualizada.
3. Resolver recuperación de instalación/renovación sin revocar por una incidencia
   de conectividad. Conservar revocación inmediata y límites de intentos.
4. Construir y documentar el instalador Windows; validar reinicio y recuperación
   bajo la cuenta real. El funcionamiento del agente es una dependencia de esta
   entrega, no una garantía obtenida solo por completar la pantalla.
5. Entregar un único registro a SCRUM-95. Coordinar con SCRUM-97 las órdenes y
   configuración remota, evitando otro registro u otra pantalla. No ampliar aquí
   estadísticas, sesiones integrales ni roles.

Esta revisión no consultó Jira ni verificó SCRUM-91/92/93/95/97. El catálogo
dinámico amplió el alcance inicial; conservar lo útil no exige exponer sus
detalles técnicos al administrador.

## Condiciones de aceptación de la operación permanente

- Reiniciar Windows y recuperar el agente bajo la cuenta prevista, sin introducir
  un código ni editar configuración; comprobar también cierre de sesión y suspensión.
- Cortar/restaurar red y reiniciar el servidor: misma identidad y credencial,
  reconexión automática e historial que distingue observaciones de inferencias.
- Interrumpir proceso y actualización: conservar cola, autorización, bytes e
  historial; evitar dobles procesos y regrabaciones no autorizadas.
- Perder la respuesta de instalación o renovación: recuperación definida y
  verificable, sin dejar dos instalaciones activas ni retirar acceso prematuramente.
- Ejecutar sin catálogo, con catálogo antiguo y con fallo de Smile: PCs conocidos
  visibles, información fechada y autorización de captura segura.
- Migrar una identidad antigua: seguir autenticando, ver el equipo y consultar su
  historial anterior sin duplicados ni pérdida de procedencia.
- Probar sin micrófono, con OBS detenido y con disco lleno: estados veraces,
  indicaciones útiles y conservación de pendientes.
- Rechazar supervisor en pantalla y API; revocar mientras hay conexión activa.
- Hacer que un administrador no técnico complete una revisión de funcionamiento
  y atienda una desconexión siguiendo la pantalla, sin consola ni códigos nuevos.

## Verificación realizada en esta revisión

Se ejecutaron las suites del servidor `capture.test_pairing`,
`agenda.test_catalogue` y `web.test_pcs` con configuración de pruebas aislada:
**28 pruebas aprobadas**. Validan comportamientos actuales de vinculación,
catálogo y permisos; no validan las propuestas de este documento.

La revisión del agente fue estática. No se probó un instalador, Windows, OBS real,
red institucional, recuperación física ni los PCs instalados. No se cambiaron
credenciales, migraciones, servicios ni comportamiento de la aplicación.
