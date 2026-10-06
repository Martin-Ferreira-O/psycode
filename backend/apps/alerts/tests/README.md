# Pruebas de alertas

Ejecuta desde la raíz del proyecto:

```sh
uv run python manage.py test backend.apps.alerts --settings=backend.config.test_settings
```

Con pip, sustituye `uv run python` por `python` dentro del entorno activado, o por `.venv/Scripts/python.exe` en Windows PowerShell.

Las pruebas cubren dominio (semáforo 0–7, una evaluación por alerta) y persistencia (alta, consulta, duplicado, evaluación atómica, campos prohibidos y fallo de conexión). Usan un doble en memoria; no requieren un servidor MongoDB.

Para el ciclo real contra MongoDB:

```sh
PSYCODE_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 uv run python manage.py test backend.apps.alerts.tests.test_persistence.MongoIntegrationTests --settings=backend.config.test_settings
```
