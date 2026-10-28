# Resultado de la separación

27 de octubre de 2026. Implementación local, sin publicación ni despliegue.

## Entrega

- Servidor: `/Users/martin/Desktop/consultoria-bn`, rama
  `codex/separacion-agente-servidor`, desde `59b250812459c0bafd775f1edd76e522215f85fa`.
  Se conservaron `sprint/6`, su historial y el remoto. Cambios sin commits para revisión.
- Agente: `/Users/martin/Desktop/psycode-agent`, repositorio Git local independiente,
  misma rama de tarea, sin commit inicial ni remoto. Paquete instalable `psycode-agent 1.0.0`,
  lock propio y ejemplos por box. No depende del checkout central ni de Django.
- Wheel local: `psycode-agent/dist/psycode_agent-1.0.0-py3-none-any.whl`.
- [Manifiesto de extracción](EXTRACCION-AGENTE.json),
  [evidencia estructurada](VERIFICACION-SEPARACION.json),
  [procedencia Smile](SMILE-PROVENANCE.json).

## Cambios realizados

Se extrajeron captura, OBS, fragmentación, journal, recuperación, privacidad y cola
local sin imports del servidor. El servidor conserva dominio, SQL, almacenamiento,
procesamiento y análisis. Se retiraron la implementación local y las dependencias
OBS del repositorio central; los locks/requirements se regeneraron con uv.

Se implementaron control WS autenticado, negociación, sincronización, propiedad
SQL de conexiones, entrega al menos una vez y ACK durable. El agente conserva el
contenido del ACK tras perder una respuesta, aplica el fin autorizado con reloj
monotónico y permite detener audio durante operaciones de red. La detención de
OBS no espera el drenaje HTTP. Las secuencias/manifiestos no se reescriben al reintentar.

La agenda se persiste por revisión/box y generaciones asignadas por el servidor.
El coordinador mantiene su instancia y observa actualizaciones de otros procesos.
Se conservó el respaldo por horario clínico. Se añadieron trabajador continuo,
exclusión SQL, cierre controlado, salud y ejemplos de proxy/supervisión.

La API de audio v1 sigue intacta. V2 negocia perfil/intervalos PCM y valida duración,
solapamiento y ventana completa. Los offsets de WAV son locales y se normalizan
por separado a sesión. Se mantuvieron los roles desconocidos, la abstención clínica
y los estados técnicos. La pérdida de contexto analítico tiene fallo explícito;
no se procesa fingiendo historial vacío ni se reenvían proveedores a ciegas.

Smile: se incorporó el archivo entregado desde `/Users/martin/Downloads/smile_scraper`
sin modificar su extractor. Se conectó su JSON nativo al transporte y a la agenda;
Excel sigue admitido como formato separado. Los ocho campos entregados se conservan.
Esa versión no devuelve pacientes, psicólogos ni supervisores. No se inventaron
identidades ni se amplió el scraper a columnas excluidas por su implementación.

## Verificación ejecutada

| Comprobación | Resultado observado |
|---|---|
| Línea base antes de cambios | 400 pruebas: 1 fallo, 2 errores por FFmpeg ausente, 5 omitidas |
| Servidor central, instalación habitual | 301 pruebas, OK, 5 omitidas |
| Servidor instalado desde lock en entorno temporal, sin OBS/agente | 301 pruebas, OK, 5 omitidas |
| Agente instalado desde su paquete | 120 pruebas, todas aprobadas |
| Suite cruzada explícita | Aprobada, incluye seis pruebas HTTP v1/ACK trasladadas |
| Dos procesos ASGI y un agente en procesos distintos | Propiedad SQL sustituye conexión antigua; WS y HTTP reales |
| Runtime autónomo con OBS/FFmpeg simulados | Inicio, parcial, upload, corte y journal confirmados |
| Smile original y JSON nativo | Normalización/IDs, transporte, agenda durable y autorización con fixtures |
| Trabajador continuo y SIGTERM | Parada limpia sobre base vacía temporal, sin proveedores |
| Migraciones, hashes, límites de imports y diferencias | Sin cambios de modelo pendientes; verificaciones aprobadas |

El JSON de evidencia registra el SHA-256 del wheel usado por la suite cruzada.
Las pruebas simulan proveedores y no consumen créditos. Los cinco skips centrales
son las omisiones existentes por entorno/servicios; las pruebas de captura con
FFmpeg quedaron explícitamente en la suite optativa del agente.

## Operación y límites

Seguir [OPERACION-SEPARADA.md](OPERACION-SEPARADA.md),
[CONTROL-Y-AUDIO.md](CONTROL-Y-AUDIO.md) y el README del agente. Las migraciones y
servicios se prepararon y probaron sobre bases temporales; no se aplicó un despliegue
sobre la base operativa ni se instalaron tareas/servicios institucionales.

Pendiente: validar login y red de Smile, OBS/audio/MediaMTX, permisos e inicio
interactivo en Windows, y carga real de cinco boxes. CI Linux/Windows está preparada,
pero esta ejecución fue macOS. No se afirma revisión humana o aceptación clínica.

Un fragmento ya cerrado antes de conocer una revocación tardía puede cruzar el corte:
el servidor lo rechaza y el agente lo conserva para intervención, sin reescribir
identidad/bytes ni ampliar la autorización. La cota física de OBS/streaming debe
medirse en hardware. La pérdida del contexto analítico requiere revisión explícita;
no existe un checkpoint clínico nuevo ni recuperación automática de contexto.

Las etapas de extracción, contratos, transporte, agenda, tiempo/análisis, operación,
limpieza y pruebas locales quedan implementadas. La validación institucional y el
alcance de datos ausentes en el extractor no se declaran cumplidos.
