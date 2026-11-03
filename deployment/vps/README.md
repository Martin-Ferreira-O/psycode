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
dependencias fijadas, ejecuta límites de módulos, pruebas Django, comprobación
de migraciones y chequeos de producción, y recopila estáticos. Después detiene
el coordinador, espera hasta cinco minutos por las sesiones abiertas y drena
el trabajador. Si siguen abiertas, cancela el despliegue y reanuda los servicios.
Con los procesos detenidos, crea un respaldo SQLite, ejecuta las migraciones y
apunta `/srv/psycode/current` a la nueva versión. Reinicia y verifica los tres
servicios, incluyendo una petición HTTP al ASGI. El SHA instalado queda en
`/srv/psycode/shared/deployed-revision`.

Un fallo previo al cambio conserva la versión en ejecución. Si falla durante el
cambio, se intenta reactivar el código anterior. Las migraciones y las llamadas
externas no se revierten automáticamente: revisar el respaldo y los logs antes
de restaurar una base. El trabajador puede esperar a que finalice una entrega
externa; no se lo mata con un timeout de systemd. Los despliegues no prometen
cero interrupción: reinician HTTP y las conexiones WebSocket.

Los archivos operativos en `/usr/local/sbin`, `/etc/systemd/system` y
`/etc/nginx` son de root. Cambiar sus ejemplos en Git no los reinstala: requieren
una actualización explícita de mantenimiento como `ubuntu` mediante `sudo`.

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

Los tres procesos se habilitan al arrancar la VPS y systemd los recupera si fallan.
Los despliegues manuales y automáticos ejecutan el mismo script. No actualizar
el checkout ni editar una versión directamente.

Esta VPS caduca al mes. Antes de eliminarla, exportar SQL, MongoDB, configuración
privada y cualquier audio pendiente por un canal privado. Los respaldos en el
disco de la VPS no sobreviven a su eliminación. Al retirarla, eliminar en GitHub
la deploy key y los secretos de esta VPS y desactivar el workflow.
