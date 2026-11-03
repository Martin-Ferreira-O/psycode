# Seguridad del inicio de sesión

Implementado en `sprint/7`. Los controles se activan con las migraciones y el
reinicio ordinario del despliegue de `main`; no requieren Redis ni secretos nuevos.

## Límites predeterminados

| Operación | Presupuesto | Ventana |
|---|---|---|
| Login, por IP | 30 solicitudes, incluido JSON inválido | 15 minutos |
| Login, por cuenta | 10 intentos entre todas las IP | 15 minutos |
| Renovación, por IP | 120 solicitudes | 15 minutos |
| Solicitud de recuperación, por IP | 20 solicitudes antes de parsear JSON | 15 minutos |
| Confirmación de recuperación, por IP | 20 solicitudes | 15 minutos |
| Recuperación, por correo/IP | Se conserva el límite existente de 5 | 15 minutos |

Las variables `AUTH_LOGIN_IP_LIMIT`, `AUTH_LOGIN_ACCOUNT_LIMIT`,
`AUTH_LOGIN_WINDOW_SECONDS`, `AUTH_REFRESH_IP_LIMIT`, `AUTH_RESET_IP_LIMIT` y
`AUTH_OTHER_WINDOW_SECONDS` permiten ajustar los presupuestos. Deben ser positivos.
Las solicitudes válidas de recuperación conservan su código de límite específico
`PASSWORD_RESET_RATE_LIMITED`; los nuevos límites devuelven `AUTH_RATE_LIMITED`.

El usuario y su correo normalizado comparten contador de cuenta. Para cuentas
inexistentes se aplica el mismo presupuesto sobre el identificador normalizado.
Los éxitos también consumen presupuesto; un login correcto no borra intentos.
No hay bloqueo permanente: los rechazos no extienden la ventana. Los nuevos 429
incluyen `Retry-After` en segundos y nunca emiten tokens.

Los contadores son SQL, con transacciones IMMEDIATE en SQLite y bloqueo de fila
en motores compatibles. Los workers comparten la misma base persistente. No se
guardan IP ni identificadores en claro: las claves son HMAC-SHA256. No se permite
autenticar si la persistencia falla. El hash de contraseña se calcula fuera del
bloqueo de escritura y la credencial se vuelve a comprobar antes de emitir tokens.

## Navegador y API

La interfaz envía `X-Psycode-Browser: 1`. Login y refresh devuelven solamente
`data: {"authenticated": true}`; guardan JWT en cookies HttpOnly, SameSite=Strict
y Secure fuera de desarrollo. Access se limita a `/api/v1/` y refresh a
`/api/v1/auth/`. JavaScript elimina los tokens antiguos de localStorage y no
almacena las nuevas credenciales allí. Los usuarios de versiones anteriores deben
volver a iniciar sesión. Los assets cambiados usan URLs versionadas.

GET `/` emite la cookie CSRF; las escrituras de navegador envían `X-CSRFToken`.
El login y refresh comprueban CSRF incluso sin usuario autenticado. La
autenticación mediante cookie exige CSRF en todos los métodos inseguros, incluso
si no se envía la cabecera de navegador. Login rota el secreto CSRF. El logout
revoca la sesión y elimina ambas cookies; el access presentado como cookie se
contrasta con RefreshSession y queda invalidado inmediatamente tras la revocación.

Los clientes existentes siguen recibiendo tokens JSON si no envían la cabecera
de navegador y utilizan Authorization Bearer. Su contrato de rotación se conserva;
el access Bearer puede durar hasta una hora tras logout. La recuperación invalida
ambas modalidades al cambiar la contraseña. Las credenciales y los tokens tienen
límites de longitud antes de ejecutar hashing o validación criptográfica.

Las respuestas HTML/API usan `Cache-Control: no-store, private`. CSP permite
scripts únicamente del mismo origen, bloquea scripts inline, objetos y framing.
Se conservan estilos inline porque la interfaz los usa. También se envían
X-Frame-Options DENY, Referrer-Policy no-referrer, nosniff y Permissions-Policy.
HTTPS, HSTS y la validación de hosts permanecen habilitados en producción.

## Proxy y despliegue

El VPS ya configura Nginx para **reemplazar** X-Forwarded-For por `$remote_addr`,
y Uvicorn solo confía en cabeceras de `127.0.0.1`, con ASGI escuchando en loopback.
La aplicación usa REMOTE_ADDR y no lee directamente las cabeceras de IP enviadas
por el cliente. No habilitar `--forwarded-allow-ips '*'`. Si se introduce un CDN,
adaptar explícitamente la confianza del proxy antes de utilizarlo para las IP.
El ejemplo alternativo de Nginx también reemplaza la cabecera.

El despliegue existente ejecuta pruebas, migraciones y collectstatic antes de
reiniciar. La migración `accounts.0004_authratelimit` crea únicamente una tabla;
no cambia cuentas ni contraseñas. Los valores predeterminados se aplican sin
editar el archivo privado del servidor. Los logs registran `auth.rate_limit`
sin IP, correos, contraseñas ni tokens.

Eliminar periódicamente contadores vencidos, por ejemplo mediante una tarea
diaria de mantenimiento con el usuario de la aplicación:

```sh
cd /srv/psycode/current
.venv/bin/python manage.py cleanup_auth_rate_limits
```

El comando conserva todos los bloqueos vigentes. No hace falta ejecutarlo para
que los límites caduquen. No está programado automáticamente por este cambio.

## Validación y alcance

La suite comprueba intentos concurrentes, persistencia tras credenciales
incorrectas, expiración, aliases de una cuenta, IP falsificadas, errores de SQL,
cookies, CSRF, rotación, revocación y compatibilidad Bearer. Las pruebas JavaScript
comprueban el transporte con cookies, CSRF y una única renovación concurrente.

Estos controles reducen fuerza bruta, robo de tokens desde JavaScript y CSRF;
no garantizan una web imposible de comprometer. El límite por cuenta también
permite que un tercero provoque una indisponibilidad temporal de esa cuenta.
Para un servicio clínico público, MFA para administradores, un WAF con límites
antes de llegar al servidor y alertas operativas sobre rechazos repetidos son
capas adicionales recomendadas; no están habilitadas en esta entrega.

Referencias: [seguridad Django](https://docs.djangoproject.com/en/5.2/topics/security/),
[CSRF y AJAX en DRF](https://www.django-rest-framework.org/topics/ajax-csrf-cors/).
