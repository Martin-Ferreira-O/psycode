# tests/ — Verificación SCRUM-31

Pruebas de contratos HTTP, hashing, identidad, rotación/logout, recuperación de un solo uso, invalidación de sesiones, errores de persistencia/correo y concurrencia SQLite real. No tienen rutas propias.

Ejecutar desde la raíz: `uv run python manage.py test backend.apps.accounts --settings=backend.config.test_settings`. Alternativa: el mismo comando sin `uv run` dentro del venv. No usar datos clínicos.

`test_settings` usa una base temporal de tests en `.local/test-auth.sqlite3`; Django la crea y elimina. Las pruebas de concurrencia abren conexiones independientes. El correo se simula salvo una prueba del worker que escribe en un directorio temporal privado, sin envío SMTP.
