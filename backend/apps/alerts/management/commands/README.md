# Crear alertas locales de prueba

Requiere MongoDB y `DJANGO_DEBUG=true`. Desde la raíz:

```sh
uv run python manage.py seed_demo_alerts
```

Crea cinco alertas sintéticas con boxes, tipos de riesgo, severidades y estados distintos. No incluye audio ni datos de pacientes. Si ya existen los mismos UUID, no las modifica. Para borrar esas cinco y volver a cargarlas:

```sh
uv run python manage.py seed_demo_alerts --reset
```

El comando comprueba la conexión, aplica el esquema y vuelve a leer cada documento. La URI se configura en `.env` (`MONGODB_URI`, `MONGODB_DATABASE`). Con pip, sustituye `uv run python` por `python` en el entorno activado.
