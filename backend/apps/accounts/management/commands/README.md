# Crear el usuario local

Después de aplicar las migraciones, ejecuta desde la raíz:

```sh
uv run python manage.py seed_demo_user
```

El usuario, correo y contraseña están en el [README principal](../../../../../README.md#usuario-de-prueba). Cada integrante ejecuta este comando en su equipo. La cuenta se crea sin permisos de administrador y requiere `DJANGO_DEBUG=true`.

Si el usuario ya existe, el comando conserva sus datos y contraseña. Para restaurar la contraseña de prueba:

```sh
uv run python manage.py seed_demo_user --reset-password
```

El restablecimiento se rechaza si el correo no coincide con el de prueba o la cuenta tiene permisos staff o superusuario. Si el correo ya pertenece a otro usuario, la creación también se rechaza; revisa esa cuenta antes de volver a intentarlo.

Con pip, sustituye `uv run python` por `python` dentro del entorno activado, o por `.venv\Scripts\python.exe` en Windows PowerShell. El servidor no crea usuarios al arrancar.
