# Duración operativa de fragmentos de audio

En **Configuración operativa → Fragmentos de audio**, una cuenta administradora
puede seleccionar duración fija (segundos enteros, mínimo 10; predeterminado y
recomendado 60) o sesión completa. 600 segundos permite evaluar bloques de
10 minutos; no constituye una recomendación validada clínicamente.

La advertencia técnica informa del posible cambio en predicciones, falsos
positivos/negativos y latencia. Sesión completa retrasa el análisis hasta el cierre.
El permiso se verifica en el servidor. Los cambios de duración/modo guardan en
SQL el identificador del administrador, valores anteriores/nuevos y fecha; no
incluyen audio, nombres ni correos.

## Aplicación por sesión y compatibilidad

La configuración se congela en `CaptureSession.capture_chunk_config` al autorizar
una sesión nueva. No se resegmentan grabaciones activas ni pendientes históricos.
La duración fija efectiva se limita a la ventana programada; sesión completa usa
esa ventana, redondeada hacia arriba y con mínimo técnico de 10 segundos. Una
sesión más corta produce un WAV parcial. Un inicio tardío o revocación reduce el
audio capturado, nunca extiende la autorización.

Servidor y agente negocian `audio.chunk-config.v1` junto con audio v2. Solo entonces
la orden de inicio incluye `audio_chunk_duration`, con solapamiento de 1 segundo.
La decisión de negociación queda fija desde la primera entrega. Un reintento no
cambia el perfil ni convierte una sesión antigua a la nueva configuración.
Los equipos antiguos conservan su duración local; guardar el ajuste web no
actualiza su software. El perfil efectivo recibido queda en `audio_profile` y
se valida contra el solicitado en sesiones negociadas.

Instalar primero el servidor con las migraciones nuevas de `operational` y
`capture`, después el agente compatible. Conservar configuración privada y todo
el estado pendiente. El nuevo valor local predeterminado del agente es 60;
un `CHUNK_DURATION=10` explícito sigue vigente en conexiones sin negociación.

## Recepción, análisis y recursos

Se conservan WAV PCM mono/16 kHz/16 bits, secuencias consecutivas, checksum,
confirmación durable del inicio antes de subir, reintentos idénticos y recuperación.
El fragmento final incluye audio nuevo: no se envía solo el solapamiento.
Un fragmento de 60 segundos aporta 59 segundos nuevos después del primero.

La recepción v2 negociada tiene una cota de bytes por duración solicitada (32 000
bytes/s más margen de cabecera); legacy conserva 25 MiB y su perfil máximo de
600 segundos. La validación temporal también comprueba el fin autorizado.
Para sesión completa, revisar la configuración del proxy incluida en `deployment/`:
la plantilla permite 3 GiB solo en la ruta v2, suficiente para una jornada
clínica de hasta 25 h por cambio horario, con margen para WAV y multipart. Ajustar ese límite finito a la ventana
institucional máxima. Una configuración instalada que conserve 26 MiB puede
rechazar un WAV largo; ASGI recibe el cuerpo antes de autenticar y necesita
espacio temporal acotado.
No se despliega ni recarga nginx automáticamente al cambiar esta preferencia.

Speechmatics recibe el WAV completo por el flujo Batch existente. JEV sigue
evaluando intervenciones de hasta 15 segundos con historial acotado a 60 segundos
y 12 000 caracteres; no clasifica monolíticamente 10 minutos o una sesión entera.
No se modifican umbrales, atribución de hablantes ni reglas de alertas. La mayor
duración ofrece contexto a la transcripción, pero no demuestra mayor precisión.

El modo sesión completa aumenta memoria y disco en agente y servidor (una hora
PCM son unos 115 MB, además de copias de trabajo y OBS). Los plazos de proveedores
siguen acotados por la configuración existente; un trabajo largo puede requerir
reintento/intervención. Antes de usarlo institucionalmente, medir memoria, disco,
tiempo de subida, plazo Batch y calidad con audio autorizado. Las pruebas locales
usan audio sintético y proveedores simulados; no validan rendimiento clínico ni
hardware Windows/OBS real.
