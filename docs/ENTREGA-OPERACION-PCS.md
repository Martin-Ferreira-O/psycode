# Implementación de gestión y operación de PCs

Se implementaron las observaciones de [la revisión](REVISION-OPERACION-PCS.md) en
el servidor y en `psycode-agent` 1.1.0. La guía de comportamiento vigente está en
[GESTION-DE-PCS.md](GESTION-DE-PCS.md). Los cambios locales anteriores se conservaron.

## Cambios entregados

| Área | Resultado |
|---|---|
| Operación diaria | Sin comunicación conserva la instalación y ofrece pasos de encendido/red; no propone códigos como reparación de Internet. |
| Pantalla | Crear nuevo PC con nombre y boxes 3–7 disponibles por defecto, sin depender de equipos previos ni Smile; explicación si todos están ocupados; actualización cada 15 s; errores de boxes independientes; información anterior fechada; foco y menús preservados; mantenimiento separado del uso habitual. |
| Registro | Incorpora identidades antiguas sin cambiar claves. Conserva referencia explícita al ID anterior para consultar audio e historial. |
| Smile | Los PCs configurados son visibles y administrables sin catálogo. No se fabrican IDs ni se amplía autorización de captura al descubrir una sala. Las salas retiradas siguen bloqueadas. |
| Credenciales | Preparar reemplazo conserva el acceso vigente; canje ligado a una instalación; archivo candidato durable; confirmación atómica e idempotente; cancelación de pendientes y revocación inmediata. |
| Agente | Intención de instalación recuperable; mismo programa por PC; supervisor con recuperación de fallos y parada coordinada; no insiste indefinidamente con acceso rechazado. |
| Arranque del agente | Supervisión del proceso por CLI y script técnico existente, recuperación de OBS configurado y subprocesos sin consola. |
| Alcance de distribución | Paquete Python y CLI existentes. El instalador `.exe` y la interfaz gráfica local se separaron para la siguiente tarea. |
| Compatibilidad | Se conservan las rutas anteriores, los contratos previos y el alcance del colector. Contrato nuevo de instalación v2 sincronizado en ambos repositorios. |
| Roles | Administración y CSRF para la web/API; rechazo del supervisor, incluidas preparación y cancelación. Sin roles nuevos. |

El registro sigue siendo el que consume SCRUM-95 y que ampliará SCRUM-97. No se
crearon pantallas integrales de sesiones, estadísticas ni configuración remota.
No se consultó ni actualizó Jira, ni se acreditó el estado de SCRUM-91/92/93.

## Verificación propia

- Servidor: **514 pruebas**, resultado OK, **5 omitidas**.
- Agente instalado desde las fuentes actuales: **326 aprobadas**.
- Transporte JavaScript compartido: **14 aprobadas**.
- Navegador: pantalla y cookies reales; alta, canje HTTPS, confirmación y WSS del
  agente; permisos; carga, vacío, errores independientes; historial; filtros;
  inyección de nombres como texto; teclado; foco preservado durante actualización
  automática; anchos 375/768/1024/1440.
- Integración cruzada: **7 casos**, cinco agentes simulados, sesiones consecutivas,
  pendientes previos, respuestas HTTPS/ACK perdidas, reconexión, dos procesos ASGI,
  reemplazo de lease, autorización y análisis simulado.
- Wheel `psycode_agent-1.1.0-py3-none-any.whl` construido y usado en la integración.
  Su SHA-256 y los límites de la verificación están en
  [VERIFICACION-OPERACION-PCS.json](VERIFICACION-OPERACION-PCS.json).
- Sin migraciones de modelo faltantes; revisión visual de capturas de escritorio
  y móvil; contratos sincronizados; comprobación de diferencias sin espacios finales.

La suite del agente se ejecutó en una copia aislada sin configuración privada.
Antes de aplicar sus archivos al repositorio original se comprobaron sus hashes
para conservar las ediciones previas y detectar cambios concurrentes. No se
iniciaron grabaciones reales ni se utilizaron cuentas institucionales.

## Corrección del alcance y del alta

Al revisar la base local se encontraron PCs en los boxes 3 y 4, sin catálogo de
Smile. El selector anterior deducía su alcance únicamente de los equipos y las
fuentes existentes; por eso daba por ocupados todos los boxes y deshabilitaba el
alta. Ahora `PC_REGISTRY_BOXES` declara el alcance administrativo, con 3–7 por
defecto. No crea PCs o salas ni autoriza captura por sí solo. El botón siempre
abre el formulario y explica cuándo no quedan boxes libres.

El usuario aclaró que el instalador gráfico `.exe` corresponde a su siguiente
tarea. Se retiraron del código activo la ventana local, los puntos de entrada
GUI, PyInstaller y los archivos de instalador, conservándolos como borrador en
`.local/next-task/windows-installer`. Se mantiene la vinculación y recuperación
por CLI y la supervisión del proceso; la tarea web/API no depende de un instalador.

Antes de desplegar, verificar migraciones, HTTPS/WSS y funcionamiento real del
agente. Durante esta corrección se comprobó que `capture.0018` ya estaba aplicada
en la base local; no se crearon equipos ni se cambiaron sus credenciales para
resolver el bloqueo. La validación de OBS, micrófono, red institucional y Windows
físico sigue siendo independiente de las pruebas sintéticas. No hubo despliegue,
publicación ni grabaciones reales.
