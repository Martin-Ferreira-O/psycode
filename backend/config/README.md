# config/ — Configuración y composición

Settings Django, URLs raíz y composición explícita de accounts implementados. Configuración técnica; no contiene reglas clínicas ni consultas. Las demás apps se incluyen con patrones vacíos hasta implementar sus tareas.

## Archivos y métodos

- `settings.py`: configuración por entorno; secretos leídos del entorno, nunca escritos en documentación.
- `urls.py`: monta `accounts`, `alerts` y `dashboard` bajo `/api/v1/`.
- `composition.py`: accounts_service construye AccountsService con AccountsRepository y EmailClient. AlertsService y DashboardService siguen pendientes.
- `asgi.py` y `wsgi.py`: puntos de entrada de la aplicación.
- `test_settings.py`: base de tests separada, correo simulado y configuración sin secretos reales.

Rutas públicas: únicamente las de [API_CONTRACTS.md](../../API_CONTRACTS.md). Los patrones se definirán sin barra final; no depender de redirecciones para solicitudes POST. No se añaden admin, healthcheck ni documentación HTTP como endpoints de producto en SCRUM-30.

## Configuración

| Variable | Uso / valor por defecto documental |
|---|---|
| `DJANGO_SECRET_KEY` | Obligatorio fuera de DEBUG; en local se genera una clave persistente privada si falta |
| `DJANGO_DEBUG` | `false`; habilitar solo localmente |
| `DJANGO_ALLOWED_HOSTS` | Lista explícita por entorno |
| `FRONTEND_ORIGIN` | Origen permitido del frontend; base de enlaces de recuperación |
| `SQLITE_PATH` | Ubicación local del archivo SQLite |
| `MONGODB_URI`, `MONGODB_DATABASE` | Conexión y base de alertas, obligatorias al activar MongoDB |
| `TEAMS_WORKFLOW_URL` | URL secreta del workflow; no registrar en logs |
| `NOTIFICATION_EMAIL_TO` | Destinatarios de contingencia autorizados por la clínica |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | Transporte de correo |
| `NOTIFICATIONS_ENABLED` | `false` para desarrollo/datos de prueba; requerido `true` para pruebas explícitas de envío |

Valores de política fijados en el contrato: access 3600 segundos, refresh 24 horas, recuperación 1 hora y plazo máximo de envío de 10 segundos por canal. Zona de negocio `America/Santiago`; almacenamiento UTC. CORS solo para el origen configurado y cabecera `Authorization`; no introducir autenticación por cookies sin revisar el contrato.

## Dependencias y tareas

Puede importar implementaciones de las apps para componerlas. Las apps no importan `composition.py`. SCRUM-31 crea la base; SCRUM-32 configura MongoDB; SCRUM-41 configura notificaciones. No hay variables reales ni credenciales creadas aquí.

La instalación local guarda .env y la clave en .local, excluidos de Git. settings carga .env sin sobrescribir variables del entorno. EMAIL_BACKEND y EMAIL_FILE_PATH seleccionan archivos privados de desarrollo; EMAIL_USE_SSL complementa TLS para SMTP. Dependencias MongoDB/Teams no se conectan al arrancar. Cada proceso de correo recibe su configuración del mismo entorno y .env.
