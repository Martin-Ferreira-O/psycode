# Pruebas de autenticación

Ejecuta desde la raíz del proyecto:

```sh
uv run python manage.py test backend.apps.accounts --settings=backend.config.test_settings
```

Con pip, sustituye `uv run python` por `python` dentro del entorno activado, o por `.venv\Scripts\python.exe` en Windows PowerShell.

Las pruebas cubren login, credenciales incorrectas, usuarios inactivos, renovación y cierre de sesión, recuperación de contraseña, fallos de persistencia y correo, concurrencia y creación/restablecimiento de la cuenta local.

Django crea y elimina la base de pruebas `.local/test-auth.sqlite3`; la base de desarrollo se conserva. Las pruebas de concurrencia usan conexiones independientes. El correo se simula, salvo una prueba que escribe en una carpeta temporal; no se envían correos por SMTP.
