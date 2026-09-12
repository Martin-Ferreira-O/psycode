# Psycode API

Backend Python/Django del equipo Psycode. Nombre técnico `psycode-api`; API `/api/v1/`.

## Estado

**SCRUM-31 implementada localmente:** autenticación con SQLite, recuperación de contraseña, JWT con rotación/logout, usuario UUID y pruebas automatizadas. Apps `accounts`, `alerts`, `dashboard` y `notifications` registradas. Solo accounts tiene funcionalidades; las demás conservan archivos base y contratos pendientes.

SCRUM-30 permanece como arquitectura acordada. No se implementan detección de voz, audio, MongoDB ni Teams. No se modificó Jira.

## Instalación con uv

Python de referencia: **3.12**; también se permite 3.13. Ejecutar desde la raíz:

~~~sh
uv sync --locked
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py seed_demo_user
uv run python manage.py runserver
~~~

Copiar .env solo en una instalación nueva; conservarlo si ya existe. En Windows PowerShell usar `Copy-Item .env.example .env`. uv crea .venv y usa .python-version. Si falta uv, seguir la alternativa siguiente o consultar [instalación oficial](https://docs.astral.sh/uv/getting-started/installation/).

Servidor local: http://127.0.0.1:8000. No hay página de inicio ni frontend; consultar endpoints de auth.

## Alternativa sin uv: venv + pip

Tener Python 3.12 o 3.13 instalado. En macOS/Linux:

~~~sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo_user
python manage.py runserver
~~~

En Windows PowerShell:

~~~powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_demo_user
.venv\Scripts\python.exe manage.py runserver
~~~

requirements.txt se exporta de uv.lock, incluye versiones exactas y hashes. Quien usa pip no necesita uv. No usar pip global ni sudo. Elegir un flujo por entorno para evitar mezclar instalaciones.

## Usuario de prueba

Solo con DJANGO_DEBUG=true:

| Campo | Valor local |
|---|---|
| Usuario | `martin.demo` |
| Correo | `martin.demo@example.test` |
| Contraseña | `Psycode-Local-2026!` |

Cuenta sintética sin privilegios de administración. El comando es idempotente y no sobrescribe una cuenta existente. `seed_demo_user --reset-password` restablece explícitamente su contraseña si sigue siendo la cuenta sintética prevista. Nunca usar estas credenciales fuera de desarrollo.

Ejemplo de login local:

~~~sh
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"usuario":"martin.demo","password":"Psycode-Local-2026!"}'
~~~

Usar el access devuelto como Bearer en GET /api/v1/auth/me. Las rutas no llevan barra final.

## Recuperación local

POST /api/v1/auth/password-reset con el correo de prueba guarda un mensaje en `.local/emails/`, sin envío externo. Abrir el archivo y copiar el token del enlace; POST /api/v1/auth/password-reset/confirm recibe `token` y `nueva_password`. La pantalla del enlace todavía pertenece al trabajo del frontend.

El token dura una hora, solo sirve una vez y se guarda hasheado en SQLite. Cambiar la contraseña invalida access y refresh anteriores. El correo local sí contiene el enlace sensible y se excluye de Git.

Para SMTP, configurar EMAIL_BACKEND y las variables de .env.example; ver [SCRUM-31](docs/SCRUM-31.md). No se ha verificado entrega real SMTP.

## Verificación

~~~sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test backend.apps.accounts --settings=backend.config.test_settings
~~~

Sin uv, ejecutar los mismos comandos quitando `uv run`, dentro del venv. Las pruebas usan una base separada y no modifican al usuario local.

## Documentación y mantenimiento

- [Arquitectura](ARCHITECTURE.md): capas, módulos y colaboración.
- [Contratos API](API_CONTRACTS.md): solicitudes, respuestas y errores.
- [Implementación SCRUM-31](docs/SCRUM-31.md): decisiones, pruebas y límites.
- [Backend](backend/README.md): estructura de archivos.
- [Handoff](HANDOFF.md): tareas y responsables.
- [Insumos](docs/README.md): referencias clínicas preservadas.

Cada carpeta de código incluye README; carpetas generadas (.git, .venv, .local, cachés) quedan fuera de esta regla. La clave Django local se genera y persiste en .local con permisos restringidos cuando DEBUG=true. Fuera de desarrollo se exige secreto explícito y HTTPS.

Al cambiar dependencias, el mantenedor actualiza pyproject.toml y uv.lock y vuelve a exportar:

~~~sh
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
~~~

Versionar esos tres archivos juntos. No editar requirements.txt a mano. [Referencia oficial de uv sobre lock y exportación](https://docs.astral.sh/uv/concepts/projects/sync/).
