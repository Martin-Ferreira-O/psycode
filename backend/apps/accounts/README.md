# Accounts: autenticación

Gestiona identidad de profesionales, inicio/cierre de sesión y recuperación. Persistencia SQLite mediante Django; no conoce alertas ni MongoDB. Tareas: SCRUM-31 y consumo frontend SCRUM-35.

SCRUM-31 está implementada. Para integrar el frontend de SCRUM-35, empieza por las rutas de abajo y el ejemplo de [login con el usuario del equipo](../../../README.md#probar-el-inicio-de-sesión). El detalle de la implementación está en [SCRUM-31](../../../docs/SCRUM-31.md).

## Rutas

Prefijo `/api/v1/auth`; nombres Django con namespace `accounts`:

| Método | Sufijo | Nombre |
|---|---|---|
| POST | `/login` | `login` |
| POST | `/refresh` | `refresh` |
| POST | `/logout` | `logout` |
| GET | `/me` | `me` |
| POST | `/password-reset` | `password_reset` |
| POST | `/password-reset/confirm` | `password_reset_confirm` |

Solicitudes, respuestas, tiempos de tokens y errores: [contrato de autenticación](../../../API_CONTRACTS.md#1-autenticación).

## Capas y métodos

- API: `urls.py`, `views.py`, `serializers.py`; adapta los nombres públicos sin exponer directamente las respuestas predeterminadas de Simple JWT.
- Aplicación: `AccountsService.login`, `refresh`, `logout`, `get_current_user`, `request_password_reset`, `confirm_password_reset`.
- Reglas de identidad/credenciales en models, tokens y services.
- Infraestructura: `models.py` con usuario UUID desde la primera migración; `repositories.py` para acceso cuando el servicio lo necesite y `clients.py` para correo. Reutiliza autenticación, hashing y validadores de contraseña Django, y Simple JWT.

UUID y `usuario` autenticados se pasan a evaluaciones como contexto. Ninguna API permite que el cliente elija el autor de una evaluación. Contraseñas nunca se almacenan en claro.

## Condiciones de integración

Autenticar con usuario o correo; los correos son únicos y normalizados a minúsculas. Los nombres de usuario no contienen `@`, evitando ambigüedad con correos. Usuarios desactivados no pueden autenticar ni renovar tokens. Cada petición protegida comprueba usuario activo.

Logout revoca el refresh presentado. En la interfaz, los JWT viajan en cookies HttpOnly, Secure en producción y SameSite=Strict, con CSRF explícito en escrituras; el access de cookie comprueba también la sesión persistida y deja de autenticar tras logout. Para clientes Bearer, el access conserva su vigencia hasta expirar. Recuperación usa tokens distintos de JWT, opacos, de un solo uso y 1 hora de vigencia. El enlace apunta a `FRONTEND_BASE_URL` y `PASSWORD_RESET_PATH`; es un enlace de navegación, no una API nueva. La respuesta pública es genérica para cuentas registradas, inexistentes e inactivas.

Pruebas implementadas en [tests](tests/README.md): credenciales inválidas, inactividad, renovación/reutilización concurrente, cierre, token de recuperación vencido/usado, falta de sesión, cambio de contraseña y fallos. [seed_demo_user](management/commands/README.md) crea el usuario local del equipo.

RefreshSession guarda jti y revocación sin almacenar JWT completo. PasswordReset guarda digest SHA-256, huella de credencial y vencimiento. SQLite usa transacciones IMMEDIATE para serializar rotación y consumo. El servicio libera el bloqueo antes de enviar correo; email_worker limita la entrega mediante proceso hijo terminable y nunca imprime el enlace.

urls.patterns recibe la fábrica desde config; las apps no importan composition. No se usa el backend de sesiones Django ni la blacklist app de Simple JWT: la rotación está persistida explícitamente en SQLite. La interfaz usa cookies JWT; los clientes de API conservan Authorization Bearer.

## Protección del acceso

Los valores predeterminados admiten 30 solicitudes de login por IP y 10 por cuenta en 15 minutos. Usuario y correo de una misma cuenta comparten presupuesto entre IP distintas. También cuentan los éxitos; no se reinicia el límite al acertar. Los límites de IP se aplican antes de parsear el JSON, y los rechazos no ejecutan hashing. Hay límites independientes para renovación (120/15 min) y solicitud/confirmación de recuperación (20/15 min por ruta), además del límite existente de correo/IP en recuperación. `429 AUTH_RATE_LIMITED` incluye `Retry-After`; el vencimiento no se prolonga por insistir.

`AuthRateLimit` usa huellas HMAC y transacciones, compartidas por todos los workers y persistentes tras reinicios. Si SQL no está disponible, el acceso falla con 503. Solo se usa REMOTE_ADDR: el proxy debe reemplazar X-Forwarded-For y Uvicorn confiar exclusivamente en el proxy local. Configuración y mantenimiento: [seguridad de autenticación](../../../docs/SEGURIDAD-AUTENTICACION.md).
