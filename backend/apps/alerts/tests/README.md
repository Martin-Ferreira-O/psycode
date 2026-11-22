# Pruebas de alertas

Ejecuta desde la raíz del proyecto:

```sh
uv run python manage.py test backend.apps.alerts --settings=backend.config.test_settings --exclude-tag=mongo
```

Con pip, sustituye `uv run python` por `python` dentro del entorno activado, o por `.venv/Scripts/python.exe` en Windows PowerShell.

Las pruebas cubren dominio (niveles 1–3 con semáforo uno a uno, rechazo de límites inválidos y una evaluación por alerta), serialización API y persistencia (alta, consulta, duplicado, evaluación atómica, campos prohibidos y fallo de conexión). Usan un doble en memoria; no requieren un servidor MongoDB.

Para ejecutar persistencia y bitácora contra una instancia descartable de MongoDB:

```sh
PSYCODE_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 uv run python manage.py test backend.apps.alerts --settings=backend.config.test_settings --tag=mongo
```

El job de integración de CI inicia su propia instancia y ejecuta ambos grupos.
La matriz de Django selecciona el resto de la suite con `--exclude-tag=mongo`.
