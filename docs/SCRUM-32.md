# SCRUM-32 — Persistencia de alertas en MongoDB

Responsable del backlog: Álvaro Farfán Reyes. Implementación local de conexión, esquema, repositorio y datos sintéticos. No activa las rutas HTTP de consulta (SCRUM-33) ni el POST de evaluación (SCRUM-34).

## Entregado

- Cliente PyMongo perezoso: no abre sockets al importar ni al arrancar Django. `MONGODB_URI` y `MONGODB_DATABASE` en `.env.example`.
- Fallo de URI vacía o servidor inalcanzable → `PERSISTENCE_UNAVAILABLE` (503), sin lista vacía ficticia y sin filtrar la URI en errores.
- Colecciones `alerts` y `audit_events` con validadores e índices de [MONGODB.md](MONGODB.md).
- Documento de alerta: `alerta_id` UUID único, `box`, `tipo_riesgo`, `nivel_severidad`, `semaforo` derivado, `fecha_hora`, `estado_evaluacion`, `sesion_id`, `trazabilidad` y `evaluacion` incrustada o `null`.
- `AlertsRepository` implementa alta, consulta por id y evaluación atómica condicionada a `pendiente`.
- Comando `seed_demo_alerts`: cinco alertas sintéticas variadas (boxes, tipos, severidades 0/1/2/3/7 y estados pendiente/correcta/falso_positivo/neutro). Idempotente; `--reset` las recrea.
- Verificación al sembrar: relectura de cada documento. Sin audio, transcripción ni datos de paciente.

## Uso local

```sh
docker run --name psycode-mongo -p 27017:27017 -d mongo:7
cp .env.example .env   # si aún no existe
uv run python manage.py seed_demo_alerts
```

Requiere `DJANGO_DEBUG=true`. El arranque de `runserver` no exige MongoDB.

## Pruebas

```sh
uv run python manage.py test backend.apps.alerts --settings=backend.config.test_settings
PSYCODE_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 uv run python manage.py test backend.apps.alerts.tests.test_persistence.MongoIntegrationTests --settings=backend.config.test_settings
```

Las pruebas unitarias usan un doble en memoria. La integración contra MongoDB real queda omitida si no hay URI de prueba.

## Fuera de esta tarea

- `GET /alerts` y filtros: SCRUM-33.
- `POST /alerts/{id}/evaluacion` público: SCRUM-34 (el repositorio ya persiste la evaluación).
- Teams y correo: SCRUM-41. El seed no envía notificaciones.
