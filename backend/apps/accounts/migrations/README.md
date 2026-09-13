# Migraciones de accounts

Esta carpeta contiene los cambios del esquema SQLite para `User`, `RefreshSession` y `PasswordReset` (SCRUM-31).

Para aplicar las migraciones, ejecuta desde la raíz:

```sh
uv run python manage.py migrate
```

Si tu tarea cambia `models.py`, genera la migración y revisa el archivo antes de incluirlo en el cambio:

```sh
uv run python manage.py makemigrations accounts
uv run python manage.py migrate
```

Con pip, sustituye `uv run python` por `python` en el entorno activado, o por `.venv\Scripts\python.exe` en Windows. No edites migraciones que el equipo ya haya aplicado; agrega una nueva. Estas migraciones no gestionan MongoDB.
