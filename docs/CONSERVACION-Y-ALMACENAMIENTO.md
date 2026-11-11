# Conservación y almacenamiento

La política es fija en código (`capture/retention.py`); no se edita desde la web.

| Material | Conservación |
|---|---|
| WAV central procesado | Al menos 24 h desde `AcceptedSequence.accepted_at` UTC; se elimina en una pasada posterior. Ni mtime, ni fecha del agente, ni fin del análisis sustituyen esa fecha. |
| Cargas activas, WAV en análisis | Protegidos por bloqueos de asignación, archivo y lease, incluso si el archivo es antiguo. |
| Trabajos pendientes, fallidos o en revisión recuperables | Protegidos hasta 7 días desde la última recepción de la sesión, y hasta cerrar la recepción. Un análisis activo impide vencer la sesión. |
| Transcripción/checkpoints/contexto | Solo mientras sean necesarios para recuperación o continuidad. Se retiran de sesiones cerradas al terminar todos los trabajos, o al vencer su recuperación. |
| Temporales huérfanos propios | Se retiran tras una hora y solo sin trabajo SQL ni lease vivo. |
| Alertas, extractos, revisiones, bitácora, usuarios, configuración, agenda, recibos y metadatos | Se conservan. No se eliminan tablas ni colecciones de negocio. |

El vencimiento convierte pendientes/fallidos en `revision` con `RETENTION_EXPIRED`
y `sensitive_expired_at`. No permite reanudarlos ni volver a enviar datos a
proveedores. La recepción debe estar completa (`final_sequence`) o haber agotado
su gracia/extensión; no se deduce del estado de captura por sí solo. Los análisis
activos con más de una hora se muestran como demorados: revisar el trabajador y
su recuperación de trabajos atascados. No quitar locks ni borrar manualmente
archivos de un análisis vivo.

Los fallos ordinarios de análisis requieren revisión después de tres intentos,
según el trabajador existente. Revisarlos antes del vencimiento con
`process_fragment_jobs --report-processing` y sus opciones de intervención. No
usar una reautorización para fabricar identidad o confirmaciones.

`StorageDeletion` confirma intención antes de unlink, conserva intentos, siguiente
reintento y código técnico; tras reiniciar reconcilia archivos ya ausentes y vuelve
a intentar los restantes con espera exponencial de un minuto a una hora. Desde
diez fallos se informa intervención sin suspender reintentos. Revisar permisos,
archivos bloqueados y disco. SQL no disponible implica no inferir archivos
huérfanos. El bloqueo de limpieza dura hasta terminar o morir el proceso.

Los DELETE pendientes de Speechmatics se reintentan usando exclusivamente su
identificador/región registrados; no se reenvía audio ni texto. Tras vencer la
recuperación se conserva solo la identidad técnica del proveedor que aún debe
borrarse, sin transcripción/contexto. El borrado externo necesita su credencial y
la habilitación externa existentes; si faltan se informa fallo y permanece
pendiente. Cada pasada acota este trabajo a tres peticiones con plazo individual
de tres segundos. No se accede a archivos de terceros ni vídeos completos de OBS.

`StorageCleanupRun` es la bitácora SQL durable, con origen automático/manual,
actor, bytes, archivos, fallos, protecciones y contextos retirados. Las pasadas
automáticas exitosas con todos los contadores en cero se conservan solo en SQL.
El outbox publica los demás eventos `storage.cleanup` en Mongo con el mismo UUID
y upsert idempotente. Si Mongo cae, conserva el evento y vuelve a publicarlo.
El evento contiene solo metadatos técnicos, sin texto clínico,
nombres de archivos, rutas ni secretos. Una caída de SQL después de unlink deja
la intención pendiente; se reconcilia sin contabilizar espacio dos veces.

## Operación

```sh
uv run python manage.py migrate
uv run python manage.py cleanup_sensitive_storage --preview
uv run python manage.py cleanup_sensitive_storage
uv run python manage.py cleanup_sensitive_storage --continuous
```

La consulta de vista previa no borra. El proceso continuo ejecuta la política cada
15 minutos desde la última ejecución registrada (incluidas las manuales), respeta
los reinicios y reintenta los fallos. Si no alcanza a consultar SQL, el disco o el
bloqueo antes de registrar la pasada, espera 30 segundos y vuelve a intentar. Una
pasada ya registrada, aunque falle, mantiene el intervalo de 15 minutos.
Ejecutarlo en un servicio separado; `runserver` no lo inicia. El servicio atiende
SIGTERM entre pasadas y deja terminar la pasada en curso. El panel informa ejecución, resultado, próxima ejecución, retraso y
outbox pendiente. La próxima ejecución es una previsión: si el servicio está
apagado, el retraso crece. Cada pasada elimina hasta 1000 archivos; los protegidos
no consumen ese cupo.

El comando histórico `cleanup_capture_uploads` solo recupera huérfanos: no es el
servicio periódico de conservación ni sustituye el nuevo comando.

## Cifrado y claves

El mecanismo de cifrado en reposo es el volumen del sistema operativo: LUKS2 /
dm-crypt en Linux, incluyendo audio, SQLite/WAL, journals, temporales, swap y
respaldos. No confundir permisos 0700/0600 con cifrado. MongoDB y respaldos locales
del VPS también deben residir en volúmenes cifrados. Proveedores externos necesitan
su política contractual de eliminación, fuera del cifrado del disco central.

Configurar `CAPTURE_FRAGMENT_ROOT`, `ANALYSIS_STATE_ROOT`, la ruta SQL y
`SENSITIVE_STORAGE_EXTRA_ROOTS` (lista JSON de raíces adicionales) en volúmenes
cifrados ya provisionados por operaciones. El VPS verifica además `/var/lib/mongodb`
y `/srv/psycode/backups` por defecto. Una ruta inexistente verifica su ancestro
existente: crear/montar los destinos antes de habilitar producción. No se crea,
formatea ni cifra ningún disco automáticamente.

`SENSITIVE_STORAGE_KEY_FILES` contiene únicamente rutas absolutas de los archivos
de clave provisionados, fuera del checkout y las raíces de datos. En Linux se
verifican archivo regular sin enlace, tamaño mínimo, propietario root/cuenta de
servicio, modo privado y ancestros sin escritura para otros. No se leen ni muestran
sus bytes. Restringir su distribución a operaciones, guardar recuperación en una
bóveda institucional fuera del servidor y no copiar claves junto a datos o
respaldos. La prueba automática comprueba protección local, no acredita custodia
de copias externas ni que la clave declarada corresponda al mapper; operaciones
debe verificar esa asociación, rotación y recuperación en instalación.

```sh
uv run python manage.py verify_sensitive_storage
uv run python manage.py check --deploy
```

La verificación exige que todos los caminos de dispositivos del volumen sean
dm-crypt; overlay, discos sin cifrar, errores o utilidades ausentes fallan cerrado.
La ingesta y el trabajador exigen esta verificación fuera de desarrollo
(`SENSITIVE_STORAGE_ENCRYPTION_REQUIRED`, activa por defecto sin DEBUG), con caché
máxima de 60 s. El check de despliegue rechaza deshabilitarla en producción.
`test_settings` la desactiva exclusivamente para fixtures sintéticos.

Windows permite verificar BitLocker al 100 % con protectores activos, pero la
verificación automática de custodia de claves aún falla cerrado: requiere adaptar
la validación a la ACL institucional antes de habilitar material real en un
servidor Windows. Los agentes mantienen su operación Windows y sus propios permisos.

El cifrado del volumen protege el soporte apagado; no impide lectura por procesos
autorizados con el volumen montado. La eliminación lógica de filas no promete
sobrescritura de páginas SQLite, SSD, snapshots o backups. Aplicar caducidad de
respaldos/snapshots que contienen checkpoints, cifrarlos y custodiar sus claves por
separado; no ejecutar VACUUM bloqueante durante recepción. Desactivar core dumps y
swap sin cifrar en los servicios con material real. No conservar copias históricas
con transcripción indefinidamente.

Referencias: [dm-crypt del kernel](https://www.kernel.org/doc/html/latest/admin-guide/device-mapper/dm-crypt.html),
[operación de BitLocker](https://learn.microsoft.com/en-us/windows/security/operating-system-security/data-protection/bitlocker/operations-guide?tabs=powershell),
[transacciones y select_for_update de Django 5.2](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).
