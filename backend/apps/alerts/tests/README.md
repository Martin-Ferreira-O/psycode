# Pruebas de alertas

Ejecuta desde la raíz del proyecto:

```sh
uv run python manage.py test backend.apps.alerts --settings=backend.config.test_settings
```

Con pip, sustituye `uv run python` por `python` dentro del entorno activado, o por `.venv/Scripts/python.exe` en Windows PowerShell.

Las pruebas actuales cubren las reglas de dominio del esquema MongoDB: semáforo derivado del nivel 0–7, alta pendiente sin evaluación, una sola evaluación por alerta y límites de identificadores. No conectan a MongoDB; la persistencia pertenece a SCRUM-32.
