# Gestión de PCs: instalación única y operación diaria

Pantalla: `/api/v1/pcs/panel`; `/gestion-pcs` redirige a ella. La pantalla y las
APIs administrativas exigen administrador activo. Con cookies, las mutaciones
requieren CSRF. El supervisor no puede consultar ni administrar estos equipos.

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

1. El técnico prepara el servidor, HTTPS/WSS, migraciones, boxes configurados y
   componentes de captura. El mismo programa se instala en todos los equipos.
2. En **Crear nuevo PC**, seleccionar un box y escribir un nombre reconocible.
   Los boxes proceden de `PC_REGISTRY_BOXES` (3–7 por defecto), del
   registro existente y de las salas verificadas de Smile. No se inventan IDs de Smile ni se exige esperar a su catálogo para
   registrar un box ya configurado.
3. El técnico introduce el código de cinco caracteres mediante la CLI del agente
   en ese computador. Tiene cinco minutos de vigencia. El agente conserva OBS,
   estado y configuración existentes; guarda la credencial automáticamente.
4. Completar el inicio automático bajo la cuenta interactiva que opera OBS y
   verificar micrófono, audio, permisos y reinicio de Windows. La vinculación no
   inicia una grabación ni demuestra que haya audio.

El instalador `.exe` y su interfaz gráfica son una tarea posterior. Esta entrega
incluye el registro web/API, vinculación y recuperación del agente por la CLI.
El borrador gráfico previo se apartó del código activo y se conservó en
`.local/next-task/windows-installer` del servidor.
Para la configuración inicial y recuperación técnica se utiliza la CLI:

```sh
psycode-agent vincular --server https://servidor.example --env-file /ruta/privada/agent.env
psycode-agent resume-installation --env-file /ruta/privada/agent.env
```

No pasar códigos o claves como argumentos. El primer comando solicita el código
sin mostrarlo. El segundo recupera una instalación interrumpida con el progreso
privado guardado, sin volver a pedirlo.

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
