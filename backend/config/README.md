# Configuración del backend

> Actualización de separación: [operación vigente](../../docs/OPERACION-SEPARADA.md). Agente en el repositorio independiente `psycode-agent`; control WS autenticado, audio v1/v2 y agenda durable. Las instrucciones históricas incompatibles quedan sustituidas por ese runbook.


Aquí se configuran Django, las rutas raíz y la composición de los servicios.

La ingesta de captura está implementada en `/api/v1/internal/fragments`, con
credencial de agente, archivos privados y cola SQL. La composición expone
`fragment_storage()` y `fragment_ingestion_service()` sin iniciar trabajadores.

## Archivos y métodos

- `settings.py`: configuración por entorno; secretos leídos del entorno, nunca escritos en documentación.
- `urls.py`: monta autenticación, alertas, dashboard, configuración operativa, captura interna y web.
- `composition.py`: construye servicios de cuentas, alertas, autorización/sesiones de captura, ingesta y análisis.
- `asgi.py` y `wsgi.py`: puntos de entrada de la aplicación.
- `test_settings.py`: base de tests separada, correo simulado y configuración sin secretos reales.

Los contratos implementados y pendientes se describen en [API_CONTRACTS.md](../../API_CONTRACTS.md). Define las rutas sin barra final; el cliente debe usar la URL exacta, especialmente en solicitudes POST.

## Configuración

| Variable | Uso |
|---|---|
| `CAPTURE_AGENTS` | JSON de identidades a `{box, token_sha256}`; hash del token completo; `{}` deniega toda ingesta. |
| `CAPTURE_FRAGMENT_ROOT` | Volumen local privado persistente en Windows/macOS/Linux; por defecto `.local/capture-fragments`. |
| `CAPTURE_FRAGMENT_MAX_BYTES` | Tamaño máximo de archivo, `26214400` por defecto; multipart permite 64 KiB adicionales. |
| `CAPTURE_ORPHAN_MAX_AGE_SECONDS` | Antigüedad mínima de huérfanos en `cleanup_capture_uploads`, `3600` por defecto. |
| `DJANGO_SECRET_KEY` | Obligatorio fuera de DEBUG; en local se genera una clave persistente privada si falta |
| `DJANGO_DEBUG` | `false`; habilitar solo localmente |
| `DJANGO_ALLOWED_HOSTS` | Lista explícita por entorno |
| `FRONTEND_BASE_URL`, `PASSWORD_RESET_PATH` | Origen del frontend para CORS y ruta del enlace de recuperación |
| `SQLITE_PATH` | Ubicación local del archivo SQLite |
| `STATIC_ROOT` | Destino de `collectstatic` para Nginx; por defecto `staticfiles/`, separado del estado privado `.local/`. |
| `MONGODB_URI`, `MONGODB_DATABASE` | Conexión y base `psycode` de `alerts` y `audit_events`; obligatorias al activar MongoDB. Esquema en [MONGODB.md](../../docs/MONGODB.md) |
| `TEAMS_WORKFLOW_URL` | URL secreta del workflow; no registrar en logs |
| `NOTIFICATION_EMAIL_TO` | Destinatarios de contingencia autorizados por la clínica |
| `EMAIL_BACKEND`, `EMAIL_FILE_PATH`, `EMAIL_FROM` | `file` o `smtp`, directorio local privado y remitente |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Transporte SMTP; contraseña solo en secretos del entorno |
| `EMAIL_TIMEOUT_SECONDS` | Plazo máximo de entrega |
| `PASSWORD_RESET_RATE_LIMIT_MAX`, `PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS` | Límite por IP y correo normalizado |
| `NOTIFICATIONS_ENABLED` | `false` para desarrollo/datos de prueba; requerido `true` para pruebas explícitas de envío |

Valores de política fijados en el contrato: access 3600 segundos, refresh 24 horas y recuperación 1 hora. El plazo de envío y el límite de solicitudes son configurables. Zona de negocio `America/Santiago`; almacenamiento UTC. CORS solo para el origen configurado y cabecera `Authorization`; no introducir autenticación por cookies sin revisar el contrato.

## Dependencias y tareas

Puede importar implementaciones de las apps para componerlas. Las apps no importan `composition.py`. SCRUM-31 tiene implementada la base; SCRUM-32 conecta MongoDB al usar el repositorio, no al arrancar; SCRUM-41 configura notificaciones.

La instalación local guarda `.env` en la raíz y la clave Django en `.local/`; ambos están excluidos de Git. settings carga .env sin sobrescribir variables del entorno. `EMAIL_BACKEND=file` guarda archivos privados en `.local/emails`; `EMAIL_BACKEND=smtp` usa el servidor indicado. MongoDB no se conecta al arrancar. Cada proceso de correo recibe su configuración del mismo entorno y .env.
