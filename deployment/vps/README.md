# VPS temporal de Psycode

Destino: `144.22.56.52`, Ubuntu 22.04, usuario SSH de mantenimiento `ubuntu`.
Aplicación: `https://144.22.56.52/`. Se despliega exclusivamente `main`.

## Despliegue automático

`.github/workflows/deploy-vps.yml` se ejecuta con cada push a `main` y permite
ejecución manual en GitHub Actions. La variable de repositorio `VPS_HOST` contiene
la IP. Los secretos `VPS_SSH_KEY` y `VPS_KNOWN_HOSTS` contienen una clave exclusiva
de despliegue y la identidad SSH fijada del servidor. No se usa la clave personal
de mantenimiento en GitHub. El servidor usa una deploy key de GitHub de solo
lectura, limitada a este repositorio.

La clave de Actions únicamente puede ejecutar `/usr/local/sbin/psycode-deploy-main`
como `psycode`; no permite una shell interactiva, túneles ni acceso como root.
El script está instalado con propietario root y verifica que el SHA solicitado
coincida con el `main` actual. Los eventos de commits superados se omiten.
`flock` y la concurrencia de Actions evitan despliegues simultáneos.

El script prepara una versión en `/srv/psycode/releases/<SHA>`, instala las
dependencias fijadas, compila React, ejecuta límites de módulos, pruebas Django, comprobación
de migraciones y chequeos de producción, y recopila estáticos. Después detiene
el coordinador, espera hasta cinco minutos por las sesiones abiertas y drena
el trabajador. Si siguen abiertas, cancela el despliegue y reanuda los servicios.
Con los procesos detenidos, crea un respaldo SQLite, ejecuta las migraciones y
apunta `/srv/psycode/current` a la nueva versión. Reinicia y verifica web,
fragmentos y coordinador, incluyendo una petición HTTP al ASGI. Si
`psycode-storage.service` está instalado, también lo drena antes de migrar y
lo vuelve a comprobar. El SHA instalado queda en
`/srv/psycode/shared/deployed-revision`.

Un fallo previo al cambio conserva la versión en ejecución. Si falla durante el
cambio, se intenta reactivar el código anterior. Las migraciones y las llamadas
externas no se revierten automáticamente: revisar el respaldo y los logs antes
de restaurar una base. El trabajador puede esperar a que finalice una entrega
externa; no se lo mata con un timeout de systemd. La limpieza periódica, si está
instalada, también termina la pasada en curso antes de detenerse. Los despliegues
no prometen cero interrupción: reinician HTTP y las conexiones WebSocket.

Los archivos operativos en `/usr/local/sbin`, `/etc/systemd/system` y
`/etc/nginx` son de root. Cambiar sus ejemplos en Git no los reinstala: requieren
una actualización explícita de mantenimiento como `ubuntu` mediante `sudo`.
Antes del primer despliegue de la interfaz React, instalar Node.js 22.12 o
superior con `npm` disponible en el `PATH` del script y actualizar
`/usr/local/sbin/psycode-deploy-main` desde `deployment/vps/deploy-main.sh`.

## Datos y configuración

- `/srv/psycode/shared/server.env`: configuración privada, permisos `0600`.
- `/srv/psycode/shared/db.sqlite3`: usuarios y datos SQL persistentes.
- `/srv/psycode/shared/runtime`: journals de análisis y estado privado de `.local`.
- `/srv/psycode/shared/capture-fragments`: audio temporal privado.
- `/srv/psycode/backups`: respaldo SQLite previo a cada actualización.
- MongoDB en `127.0.0.1:27017`, datos en `/var/lib/mongodb`.

Las versiones comparten estos datos; un despliegue no copia `.env` desde Git ni
reemplaza las credenciales. Nginx sirve únicamente los estáticos y el proxy ASGI;
no publica estos directorios privados. ASGI escucha solo en `127.0.0.1:8000`.

El login tiene límites SQL por IP/cuenta y usa cookies HttpOnly con CSRF en el
navegador. Las variables nuevas tienen valores seguros por defecto; el despliegue
crea la tabla de contadores con las migraciones. Consultar [seguridad del
acceso](../../docs/SEGURIDAD-AUTENTICACION.md), incluido el comando opcional de
mantenimiento diario `cleanup_auth_rate_limits`.

La configuración inicial deja deshabilitados los proveedores externos y las
notificaciones; el correo se escribe en archivos privados. No se copian claves
del entorno local. Para conectarse con agentes reales, configurar `CAPTURE_AGENTS`
y `CAPTURE_AGENDA_SOURCES`; ver `docs/OPERACION-SEPARADA.md`.
La cuenta administradora inicial y su contraseña aleatoria se entregan en un
archivo privado, fuera del repositorio. No se crea la cuenta demo `autonoma`.

## HTTPS y red

Oracle Cloud debe permitir TCP 80 y 443 desde Internet en la Security List o
NSG de la instancia; también se abren en el firewall de Ubuntu. Conservar SSH 22.
MongoDB y ASGI no se exponen al exterior.

Certbot 5.3 o superior permite certificados de IP de Let's Encrypt con el perfil
`shortlived`. `psycode-certificate.timer` comprueba cada hora si hay que emitir o
renovar y recarga Nginx después de la emisión. El certificado de IP dura seis
días y necesita renovación automática. Durante el bloqueo de puertos el servicio
de emisión falla y conserva su reintento horario. Tras abrirlos:

```sh
sudo systemctl start psycode-certificate.service
sudo systemctl status psycode-certificate.timer
curl -I https://144.22.56.52/
```

Referencias: [certificados de IP de Let's Encrypt](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/),
[proxy HTTPS de Django](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header).

## Operación

```sh
sudo systemctl status psycode-web psycode-coordinator psycode-fragments mongod nginx
sudo journalctl -u psycode-web -u psycode-coordinator -u psycode-fragments --since '15 minutes ago'
sudo journalctl -u psycode-certificate --since '1 day ago'
sudo cat /srv/psycode/shared/deployed-revision
sudo -u psycode -H bash -c 'cd /srv/psycode && /usr/local/sbin/psycode-deploy-main'
```

Web, coordinador y fragmentos se habilitan al arrancar la VPS y systemd los
recupera si fallan. La limpieza de almacenamiento se habilita aparte, cuando la
unidad está instalada.
Los despliegues manuales y automáticos ejecutan el mismo script. No actualizar
el checkout ni editar una versión directamente.

Esta VPS caduca al mes. Antes de eliminarla, exportar SQL, MongoDB, configuración
privada y cualquier audio pendiente por un canal privado. Los respaldos en el
disco de la VPS no sobreviven a su eliminación. Al retirarla, eliminar en GitHub
la deploy key y los secretos de esta VPS y desactivar el workflow.


## Conservación y almacenamiento sensible

El nuevo servicio `psycode-storage.service` aplica conservación y recupera borrados
cada 15 minutos, incluso tras reinicios. Antes de habilitar material real, seguir
[la política y verificación de cifrado](../../docs/CONSERVACION-Y-ALMACENAMIENTO.md).
La actualización incorpora migraciones SQL; el check de despliegue falla si no se
acreditan volúmenes cifrados y archivos de clave protegidos. No deshabilitar ese
control para desbloquear un despliegue.

Instalar la unidad, tras revisar las rutas y con los volúmenes ya montados:

```sh
sudo install -m 644 deployment/vps/psycode-storage.service /etc/systemd/system/psycode-storage.service
sudo systemctl daemon-reload
sudo systemctl enable --now psycode-storage.service
sudo systemctl status psycode-storage.service
```

Configurar las raíces, claves y directorios de Mongo/respaldos en `server.env`.
La unidad incluye `RequiresMountsFor`, impide core dumps y deshabilita swap para su
cgroup. `LimitCORE=0` y `MemorySwapMax=0` también quedan en web, fragmentos y
coordinador: un volcado o el swap no deben conservar material sensible ni el
entorno. Si se usa swap fuera de esos servicios, debe estar cifrado. No guardar
respaldos que contengan contexto/transcripción más allá de su plazo de recuperación.

Cuando la unidad esté instalada, el despliegue la drena y la reinicia junto a los
trabajadores. El usuario `psycode` necesita los mismos permisos de systemctl que
ya tiene para los otros servicios, sobre estos comandos:

```sh
/usr/bin/systemctl stop psycode-storage.service
/usr/bin/systemctl start psycode-storage.service
/usr/bin/systemctl is-active psycode-storage.service
```

`systemctl cat` se consulta sin sudo para saber si la unidad existe. No ejecutar
el servicio contra una base con migraciones pendientes. El panel administrativo
muestra retrasos si el proceso no está activo y conserva fallos/outbox de bitácora.
La instalación de esta unidad y el cifrado real son acciones de operaciones.
Versionar los archivos no ejecuta ni acredita un despliegue: en un equipo sin
volúmenes dm-crypt ni archivos de clave protegidos, `verify_sensitive_storage`
termina en `ENCRYPTION_UNVERIFIED`.

## Publicación del instalador Windows

`PC_WINDOWS_INSTALLER_DIR` apunta a `/srv/psycode/shared/agent-installers`.
El directorio es de `root:psycode` con permisos `0750` y está fuera de los
estáticos y del checkout. Se conserva entre despliegues web. Cada versión
se guarda en su propio directorio y los servicios leen el enlace `current`.

Desde el checkout de mantenimiento en Ubuntu, instala el publicador y valida
la regla de sudo. La cuenta dedicada queda con contraseña bloqueada. Su
directorio y el archivo de claves son propiedad de root.

```sh
sudo install -d -m 0750 -o root -g psycode /srv/psycode/shared/agent-installers
sudo install -m 0755 -o root -g root deployment/vps/agent-installer.py /usr/local/sbin/psycode-agent-installer
sudo visudo -cf deployment/vps/agent-installer.sudoers
sudo install -m 0440 -o root -g root deployment/vps/agent-installer.sudoers /etc/sudoers.d/psycode-agent-installer
id psycode-installer >/dev/null 2>&1 || sudo useradd --system --home-dir /var/lib/psycode-installer --shell /bin/sh psycode-installer
sudo install -d -m 0755 -o root -g root /var/lib/psycode-installer /var/lib/psycode-installer/.ssh
```

Genera una clave ED25519 exclusiva para este workflow. Instala en
`/var/lib/psycode-installer/.ssh/authorized_keys` una sola línea que combine
las opciones siguientes y la clave pública generada. El archivo debe tener
propietario `root:root` y permisos `0644`.

```text
restrict,command="/usr/bin/sudo -n /usr/bin/timeout 900 /usr/local/sbin/psycode-agent-installer receive" ssh-ed25519 <clave-pública>
```

Configura `AGENT_INSTALLER_SSH_KEY` en los secretos del repositorio del
agente con la clave privada exclusiva. Configura
`AGENT_INSTALLER_KNOWN_HOSTS` con la entrada ED25519 del VPS verificada
por el operador. El workflow tiene acceso de solo lectura a Releases con
su `GITHUB_TOKEN`. Configura la huella de 40 caracteres del certificado
institucional de firma de código en la variable
`PSYCODE_WINDOWS_SIGNER_THUMBPRINT`. La firma y la comprobación de la
versión interna se hacen en Windows antes del envío. El VPS valida nombre,
versión y SHA-256 recibido con la clave exclusiva. El acceso de mantenimiento
usa su propia clave.

Una sesión SSH con la clave del workflow solo puede entregar un paquete por
stdin. El formato contiene la versión, el tamaño decimal y la línea del
manifiesto, seguidos por los bytes del ejecutable. El publicador valida en
una carpeta temporal, conserva los bytes de cada versión y cambia el enlace
bajo bloqueo. Usa `rollback` y `resume` para mantenimiento. Las instrucciones
y las verificaciones del panel están en
[Gestión de PCs](../../docs/GESTION-DE-PCS.md#publicación-estable-del-instalador).

```sh
python3 deployment/vps/test_agent_installer.py
```
