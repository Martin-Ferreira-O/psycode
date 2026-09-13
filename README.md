# Psycode API

Backend del proyecto Psycode, desarrollado en Python y Django. Actualmente funcionan el inicio de sesión, la recuperación de contraseña y el manejo de sesión (SCRUM-31). Alertas, dashboard y notificaciones tienen su estructura creada, pero sus funcionalidades están pendientes.

## Primera instalación

Abre una terminal en la carpeta del proyecto, donde está `manage.py`. Necesitas Python 3.12 o 3.13. Elige una de las dos opciones siguientes; ambas instalan las mismas dependencias.

### Opción 1: uv

Si ya tienes [uv instalado](https://docs.astral.sh/uv/getting-started/installation/), ejecuta:

```sh
uv sync --locked
```

Crea el archivo de configuración **solo si todavía no tienes `.env`**:

- macOS/Linux: `cp .env.example .env`
- Windows PowerShell: `Copy-Item .env.example .env`

Luego crea las tablas, el usuario de prueba y arranca el servidor:

```sh
uv run python manage.py migrate
uv run python manage.py seed_demo_user
uv run python manage.py runserver
```

uv crea el entorno `.venv` y usa la versión de Python indicada en `.python-version`.

### Opción 2: venv + pip

En macOS/Linux:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
```

En Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
```

Si tienes Python 3.13, sustituye `python3.12` por `python3.13` o `py -3.12` por `py -3.13`.

Crea `.env` **solo si no existe**:

- macOS/Linux: `cp .env.example .env`
- Windows PowerShell: `Copy-Item .env.example .env`

En macOS/Linux, con el entorno activado:

```sh
python manage.py migrate
python manage.py seed_demo_user
python manage.py runserver
```

En Windows PowerShell:

```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_demo_user
.venv\Scripts\python.exe manage.py runserver
```

Deja esa terminal abierta. El servidor escucha en http://127.0.0.1:8000. Para detenerlo, presiona `Ctrl+C`. La dirección raíz muestra 404 porque este repositorio contiene una API, sin pantalla de inicio ni frontend.

## Volver a arrancar el proyecto

Desde la carpeta que contiene `manage.py`, usa el comando de tu instalación:

| Instalación | Comando |
|---|---|
| uv | `uv run python manage.py runserver` |
| pip, macOS/Linux | Ejecuta `source .venv/bin/activate` y luego `python manage.py runserver` |
| pip, Windows PowerShell | `.venv\Scripts\python.exe manage.py runserver` |

Después de actualizar el código, vuelve a instalar las dependencias con el comando de tu opción y ejecuta `manage.py migrate` antes de arrancar. No vuelvas a copiar `.env`.

## Usuario de prueba

Cada integrante crea esta cuenta en su propia base local con `seed_demo_user`:

| Campo | Valor |
|---|---|
| Usuario | `autonoma` |
| Contraseña | `autonoma` |
| Correo | `autonoma@example.test` |

La cuenta no tiene permisos de administrador. El comando requiere `DJANGO_DEBUG=true`, como viene en `.env.example`; estas credenciales son solo para desarrollo local.

Si ya tenías el proyecto instalado, ejecuta:

```sh
uv run python manage.py seed_demo_user
```

Las cuentas anteriores se conservan. Si repites el comando, no cambia los datos ni la contraseña del usuario existente. Para volver a la contraseña de la tabla después de haberla cambiado:

```sh
uv run python manage.py seed_demo_user --reset-password
```

Con pip, sustituye `uv run python` por `python` en el entorno activado, o por `.venv\Scripts\python.exe` en Windows.

## Probar el inicio de sesión

Con el servidor abierto, envía desde Postman u otro cliente HTTP:

- Método: `POST`
- URL: `http://127.0.0.1:8000/api/v1/auth/login`
- Body: selecciona **raw → JSON** y pega:

```json
{"usuario":"autonoma","password":"autonoma"}
```

La respuesta debe tener estado `200`, `success: true` y los campos `data.access_token` y `data.refresh_token`.

Para comprobar la sesión, envía `GET http://127.0.0.1:8000/api/v1/auth/me`. En Authorization, selecciona **Bearer Token** y pega el valor de `data.access_token`, sin comillas. Debes recibir los datos del usuario. Las rutas no llevan `/` al final.

## Probar la recuperación de contraseña

1. Envía `POST http://127.0.0.1:8000/api/v1/auth/password-reset` con un body JSON que contenga `correo` y el correo de la tabla anterior. Debe responder `202`.
2. Abre el archivo de correo más reciente de `.local/emails/`. El correo se guarda en tu equipo; no llega a una bandeja de entrada.
3. Copia el valor que aparece después de `token=` en el enlace del mensaje.
4. Envía `POST http://127.0.0.1:8000/api/v1/auth/password-reset/confirm` con ese valor en `token` y una contraseña nueva en `nueva_password`:

```json
{"token":"PEGA_AQUI_EL_TOKEN","nueva_password":"Prueba-Equipo-2026!"}
```

El token vence en una hora y solo se puede usar una vez. Al cambiar la contraseña, vuelve a iniciar sesión: los tokens de sesión anteriores dejan de servir. La contraseña nueva debe cumplir los validadores de la aplicación; el comando de usuario local permite restaurar la contraseña sencilla de prueba.

La pantalla web de recuperación está pendiente del frontend. Para configurar correo SMTP, consulta [SCRUM-31](docs/SCRUM-31.md#correo-y-configuración).

## Ubicar tu tarea de Jira

Lee tu tarea y abre el módulo y contrato correspondientes antes de modificar código. Las rutas documentadas como pendientes todavía responden 404.

| Tarea | Dónde trabajar o consultar | Estado del backend |
|---|---|---|
| SCRUM-30: arquitectura | [Arquitectura](ARCHITECTURE.md) y [contratos](API_CONTRACTS.md) | Documentados |
| SCRUM-31 / SCRUM-35: autenticación backend / frontend | [Accounts](backend/apps/accounts/README.md) y [contrato de autenticación](API_CONTRACTS.md#1-autenticación) | Disponible |
| SCRUM-32 / 33 / 34: persistencia, consulta y evaluación | [Alerts](backend/apps/alerts/README.md) y [contrato de alertas](API_CONTRACTS.md#2-alertas-y-evaluaciones) | Pendiente |
| SCRUM-36: dashboard | [Dashboard](backend/apps/dashboard/README.md) y [contrato dashboard](API_CONTRACTS.md#3-dashboard) | Pendiente |
| SCRUM-37 / 39 / 40: historial, detalle y registro en frontend | [Alerts](backend/apps/alerts/README.md) y [contrato de alertas](API_CONTRACTS.md#2-alertas-y-evaluaciones) | Pendiente |
| SCRUM-41: notificaciones | [Notifications](backend/apps/notifications/README.md) y [contrato interno](API_CONTRACTS.md#4-registro-y-notificaciones-contratos-internos) | Pendiente |

El código de este repositorio es el backend. Las tareas frontend consultan sus contratos aquí. El [handoff](HANDOFF.md) conserva las descripciones originales del backlog; para conocer lo que funciona en el código actual, usa esta tabla y los README de cada módulo.

## Comprobar los cambios

Ejecuta desde la raíz:

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test backend.apps.accounts --settings=backend.config.test_settings
```

Con pip, usa el mismo reemplazo de `uv run python` indicado arriba. Las pruebas crean una base separada y no modifican tu usuario local. Si cambias modelos, genera y revisa la migración correspondiente antes de comprobar que no quedan migraciones pendientes.

## Dependencias y documentación

La estructura del código está en [backend](backend/README.md) y los documentos de referencia en [docs](docs/README.md). `.env`, la base SQLite y los correos locales no se suben a Git. La base y la clave Django local se guardan en `.local/` con la configuración predeterminada.

Solo si necesitas cambiar dependencias, edita `pyproject.toml` y ejecuta con uv:

```sh
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
```

Incluye `pyproject.toml`, `uv.lock` y `requirements.txt` en el mismo cambio. `requirements.txt` se genera; no se edita a mano.
