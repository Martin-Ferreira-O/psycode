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

Los nuevos servidores y agentes negocian `audio.chunk-config.v2` junto con audio v2.
La orden incluye `audio_chunk_duration` y `audio_chunk_overlap=0`: bloques consecutivos
sin solapamiento. La capacidad anterior `audio.chunk-config.v1` conserva 1 s para
compatibilidad, por lo que no garantiza seis archivos exactos por hora.
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
Con negociación v2, cada bloque de 60 segundos aporta 60 segundos nuevos. Una
hora con bloques de 600 segundos produce exactamente seis trabajos de análisis;
modo sesión completa produce uno al cierre. El último bloque puede ser parcial.

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

Speechmatics transcribe cada WAV completo. En las sesiones operativas nuevas,
JEV recibe una sola solicitud con el texto completo de ese bloque, sus turnos y
roles conservados. Los turnos se interpretan como diálogo entre entrevistador
y paciente. Ya no se llama a JEV por cada intervención de 15 segundos.
Cada trabajo conserva un único resultado y genera como máximo una alerta del
bloque si hay evidencia atribuible y suficiente. Un resultado sin señal o
indeterminado no equivale a una alerta clínica. Los trabajos legacy ya iniciados
conservan su unidad de análisis para no duplicar solicitudes ni reinterpretar
respuestas persistidas.

El cliente directo de Typesafe puede volver a enviar el bloque completo con
contexto largo tras un rechazo explícito por contexto. Si el límite persiste,
el bloque queda en revisión y los demás bloques pueden seguir analizándose.
La alerta requiere una voz confirmada como paciente.

El modo sesión completa aumenta memoria y disco en agente y servidor (una hora
PCM son unos 115 MB, además de copias de trabajo y OBS). Los plazos de proveedores
siguen acotados por la configuración existente; un trabajo largo puede requerir
reintento/intervención. Antes de usarlo institucionalmente, medir memoria, disco,
tiempo de subida, plazo Batch y calidad con audio autorizado. Las pruebas locales
usan audio sintético y proveedores simulados; no validan rendimiento clínico ni
hardware Windows/OBS real.
