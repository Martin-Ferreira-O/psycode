# Configuración del backend

Aquí se configuran Django, las rutas raíz y la construcción del servicio de accounts. Las demás apps tienen rutas vacías hasta implementar sus tareas.

## Archivos y métodos

- `settings.py`: configuración por entorno; secretos leídos del entorno, nunca escritos en documentación.
- `urls.py`: monta `accounts`, `alerts` y `dashboard` bajo `/api/v1/`.
- `composition.py`: accounts_service construye AccountsService con AccountsRepository y EmailClient. AlertsService y DashboardService siguen pendientes.
- `asgi.py` y `wsgi.py`: puntos de entrada de la aplicación.
- `test_settings.py`: base de tests separada, correo simulado y configuración sin secretos reales.

Las rutas disponibles son las de autenticación. El resto de [API_CONTRACTS.md](../../API_CONTRACTS.md) está pendiente. Define las rutas sin barra final; el cliente debe usar la URL exacta, especialmente en solicitudes POST.

## Configuración

| Variable | Uso |
|---|---|
| `DJANGO_SECRET_KEY` | Obligatorio fuera de DEBUG; en local se genera una clave persistente privada si falta |
| `DJANGO_DEBUG` | `false`; habilitar solo localmente |
| `DJANGO_ALLOWED_HOSTS` | Lista explícita por entorno |
| `FRONTEND_ORIGIN` | Origen permitido del frontend; base de enlaces de recuperación |
| `SQLITE_PATH` | Ubicación local del archivo SQLite |
| `MONGODB_URI`, `MONGODB_DATABASE` | Conexión y base `psycode` de `alerts` y `audit_events`; obligatorias al activar MongoDB. Esquema en [MONGODB.md](../../docs/MONGODB.md) |
| `TEAMS_WORKFLOW_URL` | URL secreta del workflow; no registrar en logs |
| `NOTIFICATION_EMAIL_TO` | Destinatarios de contingencia autorizados por la clínica |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | Transporte de correo |
| `NOTIFICATIONS_ENABLED` | `false` para desarrollo/datos de prueba; requerido `true` para pruebas explícitas de envío |

Valores de política fijados en el contrato: access 3600 segundos, refresh 24 horas, recuperación 1 hora y plazo máximo de envío de 10 segundos por canal. Zona de negocio `America/Santiago`; almacenamiento UTC. CORS solo para el origen configurado y cabecera `Authorization`; no introducir autenticación por cookies sin revisar el contrato.

## Dependencias y tareas

Puede importar implementaciones de las apps para componerlas. Las apps no importan `composition.py`. SCRUM-31 tiene implementada la base; SCRUM-32 configura MongoDB; SCRUM-41 configura notificaciones.

La instalación local guarda `.env` en la raíz y la clave Django en `.local/`; ambos están excluidos de Git. settings carga .env sin sobrescribir variables del entorno. EMAIL_BACKEND y EMAIL_FILE_PATH seleccionan archivos privados de desarrollo; EMAIL_USE_SSL complementa TLS para SMTP. Dependencias MongoDB/Teams no se conectan al arrancar. Cada proceso de correo recibe su configuración del mismo entorno y .env.
