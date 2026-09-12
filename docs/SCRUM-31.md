# SCRUM-31 — Autenticación y recuperación

Responsable: Martin Ferreira. Implementación local autorizada después de SCRUM-30; no cambia estados de Jira ni inicia las funcionalidades de SCRUM-32+.

## Entregado

- Proyecto Django y cuatro apps registradas: accounts funcional; alerts, dashboard y notifications con archivos base pendientes.
- User UUID, correo único sin distinción de mayúsculas, nombre de usuario sin @, estado activo y hashing Django.
- Seis rutas auth del [contrato](../API_CONTRACTS.md#1-autenticación), con envelopes y errores comunes, permisos y CORS limitado al origen configurado.
- Access de 1 hora; refresh de 24 horas, rotación y revocación persistidas en SQLite. Logout idempotente para refresh propio; access conserva vigencia restante.
- Recuperación con token aleatorio de 256 bits, digest SHA-256, un token por usuario y vigencia de 1 hora; consumo y cambio de contraseña atómicos. Cambiar contraseña invalida JWT anteriores.
- Comando seed_demo_user, cuenta sintética local y migración inicial aplicada localmente.
- pyproject.toml, uv.lock y requirements.txt con versiones/hash equivalentes para uv y pip. Python 3.12 de referencia; rango 3.12–3.13.

## Decisiones de implementación

Presentación valida JSON y delega; servicios coordinan casos de uso; AccountsRepository concentra persistencia. La autenticación reutiliza User de Django y Simple JWT. No se duplica el modelo de identidad en otra capa.

RefreshSession almacena jti, usuario, vencimiento y revocación, nunca JWT completo. La blacklist app de Simple JWT no se instala: el repositorio serializa verificación y rotación con transacciones SQLite IMMEDIATE. Esto evita doble renovación concurrente y protege el consumo de recuperación, pero implica un único escritor SQLite y no pretende resolver alta concurrencia de producción.

La huella de la contraseña hasheada se comprueba en access y refresh. No se usa como algoritmo para guardar contraseñas: Django sigue usando su hasher seguro. Una actualización externa de contraseña invalida también recuperación y JWT previos.

El servicio termina la transacción antes de enviar correo. EmailClient inicia email_worker con el enlace por stdin, sin argumentos sensibles ni stdout/stderr. El proceso puede terminarse tras 10 segundos y no queda un hilo enviando indefinidamente. Un timeout puede ocurrir después de que un proveedor haya aceptado el mensaje; el token se descarta si se informó fallo, por lo que el usuario deberá solicitar otro. No hay cola ni confirmación de lectura.

## Correo y configuración

Desarrollo usa backend filebased de Django: archivos en .local/emails con permisos privados, sin SMTP. Estos archivos contienen tokens y se excluyen de Git. El frontend del enlace todavía no está implementado; copiar el token para probar la confirmación por API.

Para correo real, configurar EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend, host, puerto, usuario, contraseña, remitente y TLS/SSL en .env. No habilitar ambos TLS y SSL. Fuera de DEBUG se exige secreto largo y origen frontend HTTPS, con redirección HTTPS. La configuración del proxy y entrega SMTP real no se han desplegado ni verificado en esta tarea.

Se conserva AUTH_USER_NOT_FOUND (404) según el contrato, con la exposición de existencia de cuentas ya documentada. No se agregan roles ni páginas frontend. Las apps futuras responden 404 hasta tener rutas implementadas.

## Pruebas y reproducción

Comandos de instalación y credenciales sintéticas en [README](../README.md). Pruebas en [accounts/tests](../backend/apps/accounts/tests/README.md).

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test backend.apps.accounts --settings=backend.config.test_settings
```

Sin uv, usar python dentro del venv. Instalación alternativa: python -m pip install --require-hashes -r requirements.txt. Ambas vías se verifican con las mismas versiones.

La suite cubre contratos, errores, UUID/hashing, usuarios inactivos, renovación repetida y concurrente, logout, recuperación vencida/usada/sustituida, rollback ante fallo, invalidación por cambio de contraseña, CORS y worker de correo local. Usa SQLite de tests separada; ningún test envía SMTP ni modifica datos clínicos.

### Resultado verificado el 2026-09-12

- **35 pruebas aprobadas**, incluidas conexiones SQLite independientes para concurrencia y envío local real mediante email_worker.
- Django check sin errores y makemigrations --check --dry-run sin cambios pendientes.
- uv sync completado; instalación pip independiente con --require-hashes completada, pip check sin dependencias rotas y Django check también correcto en ese entorno.
- Versiones instaladas: Python 3.12.13, Django 5.2.17, DRF 3.17.2, Simple JWT 5.5.1, PyMongo 4.18.1, django-cors-headers 4.9.0 y python-dotenv 1.2.3.
- Migración SQLite local aplicada; martin.demo creado y verificado por login, me, logout y rechazo de refresh revocado, sin imprimir tokens.
- Revisión de 21 Markdown, 59 enlaces locales y sintaxis de 55 archivos Python sin errores. .env, .local y .venv excluidos de Git.

SMTP real, Teams, MongoDB, frontend y despliegue no fueron ejecutados ni se presentan como terminados.

## Fuentes técnicas

Context7 no estuvo disponible; se consultaron fuentes oficiales:

- [uv: sincronización y exportación](https://docs.astral.sh/uv/concepts/projects/sync/).
- [Django: usuario personalizado](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/), [SQLite y transacciones](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes) y [correo](https://docs.djangoproject.com/en/5.2/topics/email/).
- [Simple JWT: configuración](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/settings.html).
- [CORS](https://github.com/adamchainz/django-cors-headers) y [python-dotenv](https://bbc2.github.io/python-dotenv/).
- [Python subprocess](https://docs.python.org/3/library/subprocess.html#subprocess.run).
