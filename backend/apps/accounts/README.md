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

Logout revoca el refresh presentado; el frontend elimina sus tokens. El access ya emitido puede seguir válido hasta expirar, como establece el contrato. Recuperación usa tokens distintos de JWT, opacos, de un solo uso y 1 hora de vigencia. El enlace apunta a `FRONTEND_ORIGIN` y la futura pantalla `/password-reset/confirm?token=...`; es un enlace de navegación, no una API nueva.

Pruebas implementadas en [tests](tests/README.md): credenciales inválidas, inactividad, renovación/reutilización concurrente, cierre, token de recuperación vencido/usado, falta de sesión, cambio de contraseña y fallos. [seed_demo_user](management/commands/README.md) crea el usuario local del equipo.

RefreshSession guarda jti y revocación sin almacenar JWT completo. PasswordReset guarda digest SHA-256, huella de credencial y vencimiento. SQLite usa transacciones IMMEDIATE para serializar rotación y consumo. El servicio libera el bloqueo antes de enviar correo; email_worker limita la entrega mediante proceso hijo terminable y nunca imprime el enlace.

urls.patterns recibe la fábrica desde config; las apps no importan composition. No se usan sesiones de cookies ni la blacklist app de Simple JWT: la rotación está persistida explícitamente en SQLite.
