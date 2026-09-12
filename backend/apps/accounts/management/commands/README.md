# commands/ — Usuario de prueba

`seed_demo_user` crea `martin.demo`, correo `martin.demo@example.test`, contraseña local `Psycode-Local-2026!`, sin permisos staff/superusuario. Solo funciona con DJANGO_DEBUG=true. Esas credenciales son públicas y exclusivamente sintéticas.

Ejecutar `uv run python manage.py seed_demo_user` después de migrate. Si existe el usuario, no modifica contraseña ni datos. `--reset-password` restablece explícitamente la contraseña de prueba, solo si el usuario existente corresponde al correo sintético y no tiene privilegios. El método `handle` valida estas condiciones y usa el modelo de accounts. Sin rutas HTTP.
