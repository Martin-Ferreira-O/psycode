# migrations/ — Esquema SQLite de accounts

Migración inicial para User UUID, RefreshSession y PasswordReset. Django genera los archivos a partir de models.py. Se ejecutan con `uv run python manage.py migrate` o `python manage.py migrate` en venv.

Sin rutas HTTP ni servicios. Dependencia: migraciones de auth/contenttypes de Django. No modificar una migración ya aplicada en un entorno compartido; crear una nueva. Tarea SCRUM-31; MongoDB no usa estas migraciones.
