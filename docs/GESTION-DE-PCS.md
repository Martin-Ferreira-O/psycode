# Gestión de PCs · Instalación y operación diaria

Pantalla: `/api/v1/pcs/panel`; `/gestion-pcs` redirige a ella. La pantalla y las
APIs administrativas exigen administrador activo. Con cookies, las mutaciones
requieren CSRF. El supervisor no puede consultar ni administrar estos equipos.

## Configuración remota por PC (SCRUM-97)

Gestión de PCs no ofrece un formulario ni una acción para configurar manualmente
el heartbeat, sus versiones técnicas o la recuperación de configuraciones.
El heartbeat y la recuperación funcionan automáticamente con los mecanismos
internos existentes. Los endpoints técnicos de SCRUM-97 permanecen disponibles
con sus permisos administrativos; no se invocan desde esta pantalla.
La duración y los modos «Duración fija»/«Sesión completa»
permanecen globales en **Configuración operativa** (`/configuracion-operativa`);
no se editan por PC. Se toma una instantánea al autorizar una sesión nueva y
se entrega la duración resuelta en su orden de inicio, sin cambiar sesiones
existentes. El solapamiento v2 permanece en cero. No se aceptan parámetros OBS,
comandos, URLs, credenciales, fragmentación por PC ni retención.

Los informes históricos por PC que incluían fragmentación se toleran al leer,
pero esos campos se descartan del perfil de control efectivo y de su journal.
No sobrescriben la configuración global. La versión y los ACK por PC describen
el control; no deben interpretarse como ACK global de audio de todos los equipos.
El audio usa el contrato de órdenes y su confirmación por sesión ya existente.
Los agentes sin negociación conservan su comportamiento local anterior; no se
presentan como receptores de la configuración global. El asistente Windows 2.1.1
no implementa selectores de modo; el agente compatible usa el perfil de la orden.

Internamente se conservan valores deseados y efectivos, versiones,
revisión local y estado pendiente, recibido, aplicado o fallido. Un HTTP 201
solo guarda una solicitud: aplicado exige un ACK válido del PC cuyos valores
coincidan con los solicitados. Una solicitud pendiente no oculta la última
configuración confirmada. La recuperación ante fallos conserva la última
configuración válida sin restaurar credenciales antiguas.

La API `GET/PUT /api/v1/internal/pcs/<agent_id>/config` conserva `version` como
revisión global para concurrencia, y añade `desired_version`, `effective_version`
y `effective_local_revision`. PUT envía `base_version`; una revisión ausente en
un registro existente u obsoleta devuelve 409. Los alias anteriores
`expected_version` y `version` se conservan, pero deben ser enteros coherentes.
Los valores inválidos reciben 400, sin errores de tipo 500. El versionado y los
conflictos continúan siendo parte del contrato técnico, sin edición manual en UI.

El agente y el servidor negocian `agent.config.v1`. La conexión conserva la
autenticación por registro y box, la validación TLS y las comprobaciones de
lease y credencial vigente. `config_sync` incluye `base_local_revision`;
`config_received` confirma recepción; `config_ack` confirma aplicación o fallo;
`config_receipt` confirma persistencia. `config_local` informa revisión local,
versión base y valores efectivos, sin secretos. El contrato canónico y su hash
están en `contracts/`, reflejados en el repositorio del agente.

Los cambios locales, incluso sin conexión, incrementan su revisión y conservan
la intención web en conflicto como fallida. Los ACK perdidos se reenvían sin
reaplicar el cambio. El servidor y el journal local conservan versiones tras
reiniciar. Las órdenes de inicio nuevas esperan una configuración pendiente;
las detenciones y los plazos autorizados no esperan. La duración ya negociada
de una sesión permanece congelada y limitada por su ventana autorizada.

Antes de integrar se necesita la migración `capture.0022`, que añade origen y
revisión local a las configuraciones existentes sin borrar datos. Un agente
2.1.1 sin esta extensión conserva su operación normal; sus solicitudes remotas
seguirán pendientes hasta que se distribuya una versión compatible. Este cambio
no construye ni instala ese ejecutable. Validar micrófono, reinicio de Windows,
red institucional y nueva distribución en un entorno de laboratorio antes de
aprobar su operación física.

## Para el administrador

- Una tarjeta identifica el computador y su box. Muestra conexión, última
  comunicación, captura, último audio, pendientes, disco, autonomía y el flujo
  separado de captura, recepción y procesamiento.
- **Sin comunicación** no significa credencial vencida ni permite afirmar que el
  PC está apagado. Comprobar encendido e Internet. La aplicación intenta
  reconectarse con la misma identidad y clave; no pedir un código nuevo.
- **Pendiente de instalación** requiere que el técnico complete la instalación
  inicial. Un código vencido permite preparar otro para el mismo registro.
- **Instalación y acceso** contiene acciones excepcionales: reinstalar/reemplazar,
  deshabilitar acceso y cancelar una instalación pendiente. La revocación es
  inmediata; no se utiliza para resolver una caída de Internet.
- **Ver historial** filtra por fechas y box y pagina los resultados. Distingue
  eventos del computador de caídas inferidas; no inventa causas ni horas físicas.

La pantalla se actualiza cada 15 segundos mientras está visible. Conserva el
foco del teclado y los menús abiertos; pausa la actualización automática durante
los diálogos. Un fallo conserva y fecha la última información válida. La consulta
de boxes falla de forma independiente: no impide consultar el estado de los PCs.

## Alta e instalación inicial

1. Desde el PC Windows x64, inicia sesión en Psycode como administrador y abre
   **Gestión de PCs**. Pulsa **Descargar instalador para Windows x64** y ejecuta
   el `.exe` con la cuenta de Windows que opera OBS. El instalador incluye
   Python y detecta OBS, FFmpeg y ffprobe. Si faltan, descarga y verifica las
   dependencias. Windows puede solicitar elevación para instalar OBS.
2. Con el asistente abierto, usa **Crear nuevo PC** para elegir el box y darle
   un nombre al equipo. Los boxes proceden de `PC_REGISTRY_BOXES` (3–7 por
   defecto), del registro existente y de las salas verificadas de Smile. El
   diálogo de alta también ofrece el instalador y su SHA-256. Puedes completar
   todo este flujo con el navegador y el asistente de Windows.
3. En **Vinculación** del asistente, introduce la dirección HTTPS y el código
   de cinco caracteres que muestra el diálogo. Pulsa **Vincular e iniciar**. El código
   vence a los cinco minutos por defecto. Si vence, cierra el diálogo y abre
   **Instalación y acceso → Generar otro código** en la tarjeta del mismo PC.
   Usa **Recuperar vinculación** en el asistente para continuar un canje
   interrumpido que ya tenga progreso guardado.
4. Comprueba que el equipo figure como **Conectado** en Gestión de PCs y que
   vuelva a conectarse al iniciar sesión en Windows. Para verificar el audio,
   comprueba OBS y la pista mediante una sesión sintética autorizada.

El mismo `.exe` sirve para todos los boxes. La descarga está separada del alta
y del canje, y no modifica el código. Si el instalador no está publicado, la
pantalla muestra un aviso y permite consultar equipos, generar códigos y
vincular desde un asistente que ya esté instalado.

## Publicación estable del instalador

GitHub Releases del agente es la fuente de versiones. Publica una Release
estable con etiqueta `vX.Y.Z` y los dos adjuntos definitivos
`PsycodeAgent-Setup-X.Y.Z-x64.exe` y `PsycodeAgent-Setup-X.Y.Z-x64.exe.sha256`.
Genera el SHA-256 después de aplicar la firma Authenticode institucional.
El workflow **Publish stable Windows installer to Psycode** valida la versión
interna, la firma y los hashes antes de enviar el par al VPS. Para reintentar,
ejecuta el workflow en `main` e indica la etiqueta de la misma Release.

El VPS coteja el nombre y la versión del manifiesto, comprueba el SHA-256 de los
bytes guardados y activa `current` mediante un reemplazo atómico. Conserva los
directorios de las versiones anteriores. El panel y la API de actualización del
agente leen el mismo enlace en cada petición. La nueva versión queda disponible
sin reiniciar el servicio. La automatización omite los reintentos de versiones
inferiores a la última recibida y rechaza sustituir los bytes de una versión
existente.

Para verificar una publicación, abre `/gestion-pcs` como administrador,
comprueba la versión visible y descarga ambos adjuntos. Comprueba el SHA-256
del `.exe` descargado. Repite la petición sin sesión y comprueba que se rechaza.
La aceptación en Windows se realiza por separado. Instala manualmente 1.3.0
sobre 1.2.1 con la misma cuenta operadora y comprueba la vinculación y los
pendientes. Para probar la autoactualización, usa dos builds de prueba y un
Psycode de ensayo con una identidad sintética vinculada. Comprueba el rechazo
de la descarga al elegir **No**, la instalación al elegir **Sí**, la integridad,
la reapertura y el aplazamiento durante una captura sintética.

### Revertir y reanudar

En el VPS, indica una versión conservada. El comando verifica sus bytes,
pausa la automatización y cambia `current` bajo el mismo bloqueo que usa la
publicación. El panel vuelve a servir esa versión en la próxima carga. Los
agentes con una versión posterior conservan la que ya tienen instalada.

```sh
sudo /usr/local/sbin/psycode-agent-installer rollback 1.2.1
```

Cuando mantenimiento quiera volver a publicar, reanuda y ejecuta el workflow
con la última etiqueta válida o publica una versión superior. Se conserva el
orden anterior a la reversión para impedir que un reintento viejo se active.

```sh
sudo /usr/local/sbin/psycode-agent-installer resume
```

La instalación del publicador y de su credencial exclusiva está en la
[guía del VPS](../deployment/vps/README.md#publicación-del-instalador-windows).

## Activación recuperable de credenciales

Preparar un código **no corta el acceso actual**. El agente actualizado:

1. Persiste una intención privada con UUID de instalación y una prueba aleatoria.
2. Canjea el código por HTTPS. El servidor genera la clave de máquina y guarda
   solo su huella pendiente. La misma solicitud puede recuperarse exclusivamente
   con el UUID y la prueba originales; otro equipo no puede volver a canjearla.
3. Guarda y sincroniza una configuración candidata, conservando la activa.
4. Confirma con la clave candidata. El servidor sustituye atómicamente la clave,
   invalida la conexión anterior y registra la instalación como activada.
5. Publica la configuración local y retira la intención privada.

Una respuesta perdida en preparación/confirmación o una interrupción al publicar
el archivo se recuperan con la misma intención. Confirmar una activación ya
realizada es idempotente aun después de vencer el código. Una preparación sin
activar sí vence. Cancelar la preparación conserva el acceso actual; deshabilitar
acceso elimina también cualquier preparación pendiente.

La generación recuperable usa HMAC-SHA256 con la clave del servidor, la identidad,
el código protegido y la prueba de la instalación; el cliente no elige la API key.
La BD no contiene el secreto de máquina, la prueba del cliente ni el código en
claro. La API key solo viaja al instalador autenticado por ese canje, nunca al
listado o al almacenamiento del navegador. La repetición protegida de una misma
instalación permite recuperar su respuesta; no es una consulta administrativa del
secreto. Rotar la clave global del servidor invalida preparaciones todavía no
confirmadas; emitir otro código si corresponde.

Compatibilidad: los agentes previos siguen usando el canje de una sola respuesta,
que activa al canjear. Para obtener recuperación en dos fases, actualizar primero
el servidor y después el agente. Las rutas antiguas de emisión/renovación directa
siguen disponibles para sus consumidores, con sus efectos inmediatos originales.

## Equipos existentes y Smile

Las identidades de `CAPTURE_AGENTS` se incorporan idempotentemente al registro al
consultarlo o autenticarse. Se conserva su hash y su identificador de transporte;
no requieren un código para seguir trabajando. La pantalla utiliza un UUID estable
con una referencia explícita al ID anterior. Audio e historial consultan ambos IDs
sin atribuir datos de otro PC por compartir box. Retirar una clave de la
configuración antigua sigue denegando su acceso; la incorporación nunca reactiva
una clave revocada desde la web.

Solo se asocia automáticamente una sala verificada cuando hay un único equipo
para ese box. Los conflictos permanecen visibles y requieren revisión técnica.
Preparar un reemplazo conserva el acceso antiguo hasta la activación. Esta última
retira las credenciales anteriores de la sala, también en conexiones activas.

El colector designado conserva su responsabilidad al pasar a la credencial nueva.
Sus reportes pendientes mantienen identidad de recolección, bytes y alcance. Solo
ese equipo necesita las credenciales privadas de Smile. Los demás PCs no consultan
agendas por su cuenta.

Un administrador puede usar **Probar colector** en la tarjeta del PC designado.
El PC debe estar conectado con una versión compatible. La prueba ejecuta el
extractor integrado en ese equipo: inicia sesión y verifica el selector de
salas. No descarga citas, no modifica la agenda ni recibe claves por la web.
La tarjeta muestra el resultado al actualizarse. Si indica que falta el perfil,
impórtalo desde **Soporte** en ese PC. Un resultado correcto no confirma la
entrega de una recolección completa; para eso revisa la sincronización normal.

El agente anuncia `agenda.smile-check.v1` y el servidor la negocia solo para el
colector autorizado. `POST /api/v1/internal/smile-collector-check` usa la
credencial del agente y el [contrato v1](../contracts/smile-collector-check-v1.schema.json).
La prueba se reclama una sola vez y vence tras diez minutos sin resultado.
Aplicar `agenda.0004` antes de activar la función. Las versiones anteriores
siguen recolectando con sus contratos vigentes.

Una descarga fallida no borra el catálogo anterior ni publica una agenda vacía.
Una sala retirada por una sincronización completa bloquea nuevas instalaciones y
captura. Registrar un PC no elimina los controles de autorización ni inventa una
agenda. Se conserva la política previa de horario clínico de respaldo configurado.

## Seguridad y API

HTTPS/WSS y certificados verificados; sin redirecciones en el canje. Cuerpos de
instalación limitados a 256 bytes. El código se guarda como HMAC-SHA256. Preparación:
5 intentos por IP y 20 globales cada 300 segundos por defecto, contando éxitos y
fallos. Confirmación con clave larga: presupuesto independiente de 60 por IP cada
300 segundos, para que el segundo paso no consuma el presupuesto de códigos.
Los archivos privados usan 0600 en POSIX y los helpers de ACL en Windows.

| Ruta | Comportamiento |
|---|---|
| `GET /api/v1/pcs` | Registro, estados y `installation_pending`; nunca devuelve secretos. |
| `GET /api/v1/pcs/salas` | Boxes configurados y salas verificadas; `room_id`/`smile_box_id` pueden ser nulos sin catálogo. |
| `GET /api/v1/pcs/instalador/windows-x64/{version}` | Descarga privada del `.exe` de la versión activa. Añade `/sha256` para descargar su checksum. Devuelve 404 si la versión solicitada no está disponible. |
| `GET /api/v1/internal/agent-updates/windows-x64` | Solo HTTPS con la credencial individual activa `Authorization: Agent <clave>`. Devuelve `version`, `size` en bytes y `sha256` de la versión activa, o 404 si no está disponible. |
| `GET /api/v1/internal/agent-updates/windows-x64/{version}` | Entrega el ejecutable de la versión activa con la misma autenticación del agente. Si cambió la versión desde la consulta, devuelve 404. |
| `POST /api/v1/pcs/alta` | `{name, box}` o `{name, room_id}`, exactamente una selección; devuelve código temporal. |
| `POST /api/v1/pcs/{id}/vinculacion` | Prepara instalación conservando la credencial vigente. |
| `POST /api/v1/pcs/{id}/cancelar-instalacion` | Cancela preparación sin revocar acceso actual; rechaza cancelar una activación ya confirmada. |
| `POST /api/v1/internal/pcs/vincular` | Canje compatible; con `installation_id` y `secret` prepara una credencial pendiente. |
| `POST /api/v1/internal/pcs/confirmar` | `{installation_id}` y `Authorization: Agent <clave-candidata>`; activa o confirma idempotentemente. |
| `POST /api/v1/pcs/{id}/revocar` | Revocación inmediata, incluida instalación pendiente. |
| `GET /api/v1/pcs/{id}/historial` | Fechas, box y paginación; conserva procedencia de eventos antiguos. |

Contrato canónico: `contracts/pc-installation-v2.schema.json`. Los consumidores de
SCRUM-95 utilizan el mismo registro; SCRUM-97 debe ampliarlo sin crear otro.

## Despliegue y comprobaciones

Aplicar las migraciones antes de arrancar la versión nueva:

```sh
uv run --no-sync python manage.py migrate
```

`capture.0018` añade referencia legacy y preparación/activación. Marca como
completados los canjes consumidos antes de esta actualización. No borra PCs,
sesiones, audio, claves existentes ni historial. Se mantienen las migraciones
previas `agenda.0002/0003` y `capture.0015–0017` de este desarrollo.

```sh
uv run --no-sync python manage.py test --settings=backend.config.test_settings --noinput
node --test backend/apps/web/tests/*.test.cjs
```

`capture.test_pc_lifecycle` y `capture.test_pairing` cubren activación, pérdida de
respuesta, concurrencia, cancelación, revocación, identidades previas y permisos.
`pcs.browser.cjs` cubre pantalla real, HTTPS/WSS con el agente instalado, carga,
vacío, error independiente de salas, actualización, foco, teclado y cuatro anchos.
En el agente, las pruebas de instalación/supervisión usan archivos y procesos
sintéticos. La validación física en Windows se registra por separado.
