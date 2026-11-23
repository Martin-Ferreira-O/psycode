# Credenciales Smile desde el VPS

## Configuración y entrega

La cuenta Smile se configura únicamente mediante `SMILE_USERNAME` y
`SMILE_PASSWORD` en el entorno privado del servidor. En el VPS documentado se
usa `/srv/psycode/shared/server.env`, con permisos `0600`, fuera del checkout.
No copiar los valores a `.env.example`, al código, al instalador ni a los logs.
Actualizar el entorno y reiniciar el servicio web por el procedimiento de
operación del VPS para cargar cambios. La configuración operativa de la web
sigue administrando colector, fuente y URL; nunca devuelve los secretos.
Una instalación nueva puede inicializar la URL mediante `SMILE_DEFAULT_URL`
en el mismo archivo privado. Una URL guardada se conserva y se puede editar
en el panel operativo.

Después de confirmar la vinculación recuperable, el servidor anuncia
`smile_credentials_version: "1"`. El agente consulta por HTTPS
`GET /api/v2/internal/smile-credentials` con su credencial `Agent` ya activada.
Solo el colector vigente recibe usuario y contraseña. Un PC sin designación
recibe `data: null`: puede completar su vinculación sin tener la cuenta Smile.
Si se lo designa después, el runtime la obtiene automáticamente al consultar
su perfil. No hace falta volver a vincular los equipos ya instalados.

El endpoint rechaza HTTP, credenciales de máquina pendientes/revocadas y
sesiones de la web. Responde solo JSON, con `Cache-Control: no-store, private`.
El código temporal y la respuesta de confirmación no contienen la cuenta
Smile. El contrato nuevo está en
[`smile-credentials-v1.schema.json`](../contracts/smile-credentials-v1.schema.json).
El perfil `agenda.smile-config.v1` conserva sus campos anteriores.

## Almacenamiento en el PC

El agente guarda un archivo hermano de su configuración, con nombre
`.<archivo-configuración>.smile.dpapi` en Windows y
`.<archivo-configuración>.smile.json` en POSIX. En Windows usa DPAPI con alcance
de la cuenta actual, incluso si la configuración principal es un `.env`.
La carpeta usa la ACL privada existente. En POSIX usa directorio `0700` y
archivo `0600`; allí el contenido no está cifrado por este módulo y debe
residir en el almacenamiento privado/cifrado del equipo. Mantener ambos
archivos fuera del checkout y usar la misma cuenta que ejecuta el agente.

El secreto queda ligado mediante una huella al servidor, box y credencial de
máquina, y se valida contra fuente, URL y revisión del perfil recibido. No se
incluye en journals, diagnósticos, argumentos de procesos ni confirmaciones.
Solo se entrega al extractor mediante el entorno de su proceso hijo; su salida
se descarta como en el flujo anterior. Un usuario con control de la cuenta que
ejecuta el colector puede acceder a los secretos que este necesita para operar.

Antes de consultar Smile, el agente actualiza su almacén por el canal
HTTPS autenticado. La rotación de contraseña se recoge sin reinstalar el PC.
Un perfil no asignado elimina el almacén local en la siguiente consulta exitosa;
desvincular desde el asistente también lo elimina. Una máquina desconectada no
puede recibir el borrado hasta reconectar. Para invalidar copias previamente
entregadas se debe rotar la contraseña en Smile y actualizar el VPS.

Ante respuestas inválidas, timeouts o errores de disco no se abre Smile ni se
usa silenciosamente una contraseña anterior. La vinculación conserva su
intención durable y se recupera con **Recuperar vinculación**. Los fallos de
Smile no bloquean el control de audio. Los reportes ya pendientes conservan sus
bytes e identidad y pueden reenviarse sin iniciar otra descarga.

## Compatibilidad y despliegue

Actualizar primero el servidor y configurar sus secretos; después distribuir
un instalador nuevo del agente. El servidor conserva el perfil v1 y permite
agentes anteriores, pero esos binarios todavía contienen la cuenta antigua.
El agente nuevo puede vincularse con un servidor anterior sin el anuncio; para
recolectar Smile requiere el endpoint nuevo. No recurre a las credenciales
hardcodeadas, a `USUARIO`/`PASSWORD` ni al `.env` legado.

El flujo automático ya no utiliza `--sin-tls`: valida certificado y nombre del
servidor Smile, además del HTTPS/WSS de Psycode. La instalación institucional
debe contar con certificado válido o una CA confiable mediante
`SSL_CERT_FILE` en el entorno del proceso, sin desactivar la verificación.
Esto requiere comprobación en el colector real antes de operar.

Este despliegue conserva el usuario y la contraseña institucionales actuales,
según la decisión del operador. Retirar las credenciales del código actual no
elimina las copias del historial ni las de ejecutables anteriores. La rotación
no es un requisito de esta implementación; si se cambia la cuenta en el futuro,
se actualiza el entorno privado del VPS por el procedimiento descrito arriba.

## Verificación

Las pruebas usan solo secretos sintéticos. Cubren autorización por colector,
HTTPS, secretos ausentes, rotación, revocación, confirmación repetida,
almacenamiento privado, uso de DPAPI simulado, pérdida de respuesta y fallos de
disco/publicación. No acreditan DPAPI nativo de Windows, certificado, cuenta ni
red institucional. No se cambió el extractor de procedencia registrada.
