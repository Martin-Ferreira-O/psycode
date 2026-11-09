# Gestión de PCs · Instalación y operación diaria

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

## Publicar el instalador en el VPS

El VPS sirve el `.exe` y su SHA-256 por HTTPS con la misma autorización de
administrador activo que el panel. `PC_WINDOWS_INSTALLER_DIR` apunta a un
directorio absoluto fuera de los checkouts y de los estáticos públicos. En
este VPS usa `/srv/psycode/shared/agent-installers`. Cada versión tiene su
propio directorio `X.Y.Z`. `current` es un enlace relativo al directorio de
la versión activa. Nginx usa su proxy existente para estas descargas. Los
archivos persisten entre despliegues y tras el vencimiento del artefacto de CI.

1. Prepara el paquete Windows x64 verificado. Para un build nuevo sigue
   `docs/INSTALACION-WINDOWS.md` del agente. Para la distribución institucional,
   esa guía pide revisar avisos y licencias, aprobar la identidad visual y
   aplicar la firma Authenticode. El binario local `1.2.1` de `psycode-agent/dist`
   está sin firmar. Después de firmar, genera el manifiesto sobre el `.exe`
   final con `shasum -a 256 "$exe" > "$exe.sha256"` desde el directorio que
   contiene el binario. Para verificar y subir el par desde la máquina de
   mantenimiento:

   ```sh
   set -eu
   cd /Users/martin/Desktop/psycode-agent/dist
   exe=PsycodeAgent-Setup-1.2.1-x64.exe
   shasum -a 256 -c "$exe.sha256"
   vps=ubuntu@144.22.56.52
   upload=$(ssh "$vps" 'mktemp -d "$HOME/psycode-installer.XXXXXX"')
   scp "$exe" "$exe.sha256" "$vps:$upload/"
   printf 'Directorio de carga en el VPS = %s\n' "$upload"
   ```

   El SHA-256 comprobado para los bytes locales de `1.2.1` antes de firmar es
   `9a1d311f18a0405f93380f4b6bc1a34a3ed4353a1226c050642e4c82985a8ba8`.

2. En el VPS, como usuario de mantenimiento, sustituye `upload` por la ruta
   que imprimió el paso anterior. El servicio web lee los archivos como
   `psycode`. Activa el enlace solo después de verificar la copia definitiva.
   Conserva el directorio de cada versión publicada para poder volver a ella.

   ```sh
   set -eu
   upload=/home/ubuntu/psycode-installer.XXXXXX
   root=/srv/psycode/shared/agent-installers
   version=1.2.1
   exe="PsycodeAgent-Setup-$version-x64.exe"
   (cd "$upload" && sha256sum --check --strict "$exe.sha256")
   sudo install -d -o root -g psycode -m 0750 "$root"
   sudo mkdir -m 0750 "$root/$version"
   sudo chgrp psycode "$root/$version"
   sudo install -o root -g psycode -m 0640 \
     "$upload/$exe" "$upload/$exe.sha256" "$root/$version/"
   sudo -u psycode sh -c 'cd "$1" && sha256sum --check --strict "$2"' \
     sh "$root/$version" "$exe.sha256"
   next="$root/.current-$$"
   sudo ln -s "$version" "$next"
   sudo mv -Tf "$next" "$root/current"
   ```

3. Añade `PC_WINDOWS_INSTALLER_DIR=/srv/psycode/shared/agent-installers` a
   `/srv/psycode/shared/server.env` con `sudoedit`. Despliega el cambio web por
   el procedimiento habitual de `main`. Si el código ya está desplegado,
   aplica la variable con `sudo systemctl restart psycode-web.service`.
   En `/gestion-pcs`, verifica como administrador que se ofrece `1.2.1`, que
   el navegador descarga ambos adjuntos y que su SHA-256 coincide. En una
   ventana sin sesión, verifica que la URL del `.exe` rechaza la solicitud.

### Volver a una versión anterior

En el VPS, indica una versión anterior que hayas conservado y verifica sus
archivos antes de reemplazar `current`. La próxima carga del panel refleja el
cambio sin reiniciar el servicio. Esto cambia lo que se descarga desde la web.

```sh
set -eu
root=/srv/psycode/shared/agent-installers
version=1.2.0  # Solo si se publicó y conservó esta versión.
sudo -u psycode sh -c 'cd "$1" && sha256sum --check --strict "$2"' \
  sh "$root/$version" "PsycodeAgent-Setup-$version-x64.exe.sha256"
next="$root/.current-$$"
sudo ln -s "$version" "$next"
sudo mv -Tf "$next" "$root/current"
```

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
| `GET /api/v1/pcs/instalador/windows-x64/{version}` | Descarga privada del `.exe` de la versión activa. Añade `/sha256` para descargar su checksum. Devuelve 404 si la versión solicitada no está disponible. |
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
