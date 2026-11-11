# Operación del servidor y agente de sala

Implementación local del 27 de octubre de 2026. El servidor conserva el historial de
`sprint/6`; la rama de implementación es `codex/separacion-agente-servidor`.
El agente es un paquete independiente en `/Users/martin/Desktop/psycode-agent`.
No se crearon remotos, publicaciones, instalaciones institucionales ni despliegues.

## Instalación y arranque central

Configurar las variables centrales de `.env.example`, SQL, MongoDB, correo,
almacenamiento privado, proveedores y `CAPTURE_AGENTS`. El servidor conserva solo
el SHA-256 del token completo `<agent_id>.<secret>`. El secreto del agente no es
un JWT profesional ni el hash configurado en el servidor.

```sh
uv sync --locked --no-dev
uv run python manage.py migrate
npm ci --prefix frontend
npm run build --prefix frontend
uv run python manage.py collectstatic --noinput
uv run uvicorn backend.config.asgi:application --host 127.0.0.1 --port 8000 --workers 2 --ws-max-size 65536 --proxy-headers --forwarded-allow-ips 127.0.0.1 --timeout-graceful-shutdown 90
```

Configurar `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY` privada, hosts permitidos y
`FRONTEND_BASE_URL` con el origen HTTPS real de esta interfaz (se incluye en Django).
Nginx sirve `/static/` desde `STATIC_ROOT` (por defecto `staticfiles/`). El `alias`
del ejemplo debe coincidir con la ruta absoluta de ese directorio, con permisos de
lectura para el usuario de Nginx. Mantenerlo separado de `.local/`, que contiene
SQL, secretos, audio y journals, y nunca publicar el checkout completo. Uvicorn no sirve los
estáticos de la interfaz. Para cada versión, compilar la interfaz con Node.js 22.12
o superior y ejecutar `collectstatic`.
Este es el flujo de [estáticos de Django 5.2](https://docs.djangoproject.com/en/5.2/howto/static-files/deployment/).

En procesos supervisados separados:

```sh
uv run python manage.py coordinate_capture
uv run python manage.py process_fragment_jobs --continuous --idle-seconds 1
```

`coordinate_capture --once` hace una revisión acotada y recupera vencimientos.
`coordinate_capture --stop-all` solicita cortes y no genera nuevos inicios.
Un lease SQL impide coordinadores simultáneos. El trabajador tiene otro lease;
se conserva un único consumidor secuencial porque el contexto analítico es local.
Los leases duran 30 s y se renuevan; no se inician trabajadores en imports, vistas,
AppConfig ni startup ASGI. La renovación del trabajador usa un hilo independiente.
`process_fragment_jobs --max-jobs 100` conserva el procesamiento por lote.

Parámetros centrales: `CAPTURE_COORDINATOR_INTERVAL_SECONDS=5`,
`CAPTURE_COMMAND_INTERVAL_SECONDS=1`, `CAPTURE_HEARTBEAT_SECONDS=30`,
`CAPTURE_START_TIMEOUT_SECONDS=120`, `CAPTURE_INACTIVITY_TIMEOUT_SECONDS=120`,
`CAPTURE_FINALIZATION_TIMEOUT_SECONDS=300`. No amplían la ventana autorizada.
Los archivos siguen limitados a 25 MiB. El proxy admite 26 MiB para el envoltorio
multipart. [deployment](../deployment/) contiene ejemplos de Nginx y systemd,
preparados pero no instalados; completar certificados, usuarios y rutas.

## Salud, mantenimiento y parada

```sh
uv run python manage.py capture_health
uv run python manage.py recover_capture_sessions
uv run python manage.py cleanup_capture_uploads --older-than-seconds 3600
```

`capture_health` muestra estados técnicos, pendientes, concesiones y frescura de
agenda sin imprimir tokens ni contenido de reportes. Una concesión expirada no
prueba que el proceso esté sano. El diagnóstico OBS y el disco se informan desde
el agente; `seen_at` permite detectar información antigua.

Los módulos `backend.apps.accounts.email_worker` y
`backend.apps.notifications.email_worker` ya existen: sus clientes los crean
como procesos hijos acotados por entrega y les pasan información por stdin.
No hay un daemon de correo adicional que deba arrancarse manualmente. Mantener
la configuración SMTP y la activación de notificaciones existentes.

Orden de parada: detener el supervisor del coordinador (SIGTERM solicita cortes),
mantener HTTP/WS disponible, observar `capture_health` hasta cerrar sesiones y
recibir pendientes dentro de 300 s; después drenar el trabajador y detenerlo con
SIGTERM, y por último detener Uvicorn. Si termina el plazo, conservar el estado
SQL y el audio pendiente; no reabrir ni renumerar sesiones para forzar uploads.
No reiniciar automáticamente el coordinador mientras se intenta una parada.
Una parada forzada requiere `recover_capture_sessions` y recuperación local del
agente. SIGTERM impide tomar el siguiente trabajo y drena el fragmento actual,
incluidas sus llamadas a Speechmatics/JEV, persistencia y notificaciones. El timeout
de proveedor se aplica por etapa/solicitud: un fragmento puede realizar varias
evaluaciones JEV, por lo que 300 s no es una cota total. El ejemplo systemd usa
`TimeoutStopSec=infinity` para no matar automáticamente una entrega externa incierta.
La parada puede esperar varias llamadas; si se configura una cota finita, medir el
tiempo total y tratar su vencimiento como una parada forzada con revisión posterior.

## Smile y agenda entre procesos

La fuente entregada por el usuario está en `/Users/martin/Downloads/smile_scraper`.
El agente incorpora `smile_scraper.py` sin cambiar login, consultas, JavaScript ni
normalización. [Procedencia y checksum](SMILE-PROVENANCE.json). Su formato nativo
es JSON: `smile_cita_id`, `box`, `smile_box_id`, `fecha`, `hora_inicio`,
`duracion_minutos`, `estado`, `codigo_estado`. El componente excluye otras columnas
del HTML y no devuelve pacientes, psicólogos ni supervisores. No se inventaron esas
relaciones. El servidor conserva todos sus bytes/campos originales y deriva la
ocupación con `AgendaService.load_smile_json`. El lector Excel anterior permanece.

El colector llama la CLI existente en un proceso separado, con boxes designados y
fecha local, salida JSON privada y sin imprimir citas. Instalar el extra `smile`
y Chromium/Chrome en el colector; las credenciales/URL permanecen allí. Si la CLI
termina con error, se marca revisión requerida y no se repiten credenciales a ciegas;
tras corregir el problema se usa `psycode-agent retry-smile`. No se ejecutó login ni
consulta institucional durante estas pruebas. La implementación ya está conectada
con fixtures; queda pendiente su validación real en la red de Smile.

`CAPTURE_AGENDA_SOURCES` designa un colector por fuente y su alcance:

```json
{"smile":{"collector_id":"agent-box-3","boxes":["box-3","box-4","box-5","box-6","box-7"]}}
```

No se asume que cada sala obtiene un reporte global. Configurar el alcance real;
los boxes de una fuente no pueden superponerse con otra. Un reemplazo se designa
cambiando esa configuración central; no hay elección distribuida entre PCs.

El agente solicita una generación mediante `POST /api/v1/internal/agenda-collections`
(JSON `source`). Recibe `collection_id`, generación SQL y boxes. Sube el reporte original JSON o Excel a
`POST /api/v1/internal/agenda-reports` con multipart `archivo` y `metadata` JSON.
El schema está en [contracts](../contracts/agenda-v1.schema.json).

Una recolección conserva identidad, bytes y metadatos al reintentar. Se devuelve
201 al recibir por primera vez y 200 para un reintento idéntico. Una revisión
antigua no reemplaza otra mayor. Solo `outcome=valid` con todas sus filas válidas
actualiza los boxes declarados; los demás se conservan. Un reporte válido vacío (array JSON `[]` o Excel con cabecera)
vacía explícitamente el box; `partial` y `failed` registran el intento sin vaciar.
Los reportes inválidos se rechazan. JSON nativo limitado a 10 MiB/100000 filas,
con fecha y scope comprobados. Estados desconocidos se rechazan para revisión;
no se autoriza por suposición. Citas de duración cero se conservan y no ocupan
un intervalo positivo. XLSX: 10 MiB comprimidos, 50 MiB expandidos y
1000 entradas ZIP como límites de entrada.

El coordinador conserva una instancia de `AgendaService`, la carga desde SQL y
la actualiza antes de cada revisión. Otros consumidores reconstruyen la vista
desde SQL al evaluar autorización. Continúa el respaldo por horario clínico si
el box no tiene agenda cargada; una agenda válida vacía deniega ocupación. Una
falla de descarga no elimina una revisión previa. La política de frescura no
introduce una caducidad nueva que cambie ese respaldo silenciosamente.

## Análisis y reinicios

La ingesta solo publica `FragmentJob`; ningún proveedor corre en un request.
Los estados técnicos y resultados clínicos permanecen separados. Sin atribución
confiable, los roles siguen `unknown`; no se mapea S1 a paciente.

El contrato de almacenamiento no tiene un checkpoint de transcripciones/contexto.
Tras perder el contexto de una sesión, las secuencias posteriores fallan con
`ANALYSIS_CONTEXT_LOST`, sin llamar proveedores con historial vacío. Las pendientes
precedidas por un trabajo fallido quedan explícitamente `PREVIOUS_FRAGMENT_FAILED`.
Se requiere revisión operacional; no hay promesa de reanudación automática ni
reenvío ciego ante envíos inciertos. Los journals existentes de proveedores siguen
protegiendo sus solicitudes. Los contextos de sesiones terminales se liberan cuando
no quedan trabajos pendientes/procesando. Las evidencias en memoria están acotadas.

## Verificación

Para una primera ejecución, seguir [Cómo probar el servidor junto con
psycode-agent](PRUEBAS-SERVIDOR-AGENTE.md). Esa guía explica cómo construir el
wheel actualizado en el otro repositorio, qué comandos van en cada carpeta,
cómo reconocer el resultado y qué requiere una prueba con hardware real.
El siguiente bloque es una referencia breve para un entorno ya preparado:

```sh
uv run python scripts/check_boundaries.py
uv run python manage.py test --settings=backend.config.test_settings --noinput
uv run python manage.py makemigrations --check --dry-run --settings=backend.config.test_settings
uv run python -m tests.cross.run --agent-wheel /ruta/psycode_agent-1.0.0-py3-none-any.whl
```

La última suite crea bases y entornos temporales, levanta un servidor real ASGI y
un agente instalado en otro proceso, simula OBS/proveedores y comprueba HTTP v1/v2,
ACK perdido después de commit, reconexión, agenda y coordinador entre procesos.
Recibe un wheel explícito y registra su SHA-256; no depende de carpetas hermanas.
No ejecutar dos suites sobre el mismo SQLite de pruebas: usar
`PSYCODE_TEST_SQLITE_PATH` diferente si se paralelizan. El CI actual del servidor
ejecuta su suite propia en Linux con Python 3.12/3.13, pero no la integración
cruzada. El agente actualmente no incluye workflows; la matriz Linux/Windows
mencionada en los reportes de separación es histórica. Ejecutar explícitamente
la suite cruzada y registrar el sistema donde corrió.
