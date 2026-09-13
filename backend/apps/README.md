# Módulos del backend

Organización por responsabilidad dentro de un único backend Django:

| Módulo | Responsabilidad | Rutas disponibles |
|---|---|---|
| [accounts](accounts/README.md) | Autenticación y recuperación | `/api/v1/auth/...` |
| [alerts](alerts/README.md) | Alertas y evaluaciones | Pendientes (SCRUM-32 / 33 / 34) |
| [dashboard](dashboard/README.md) | Resumen y estadísticas | Pendientes (SCRUM-36) |
| [notifications](notifications/README.md) | Teams y contingencia | Sin API pública; implementación pendiente (SCRUM-41) |

Cada módulo tendrá presentación, aplicación, dominio e infraestructura solo donde sean necesarios. Nombres comunes previstos: `urls.py`, `views.py`, `serializers.py`, `services.py`, `domain.py`, `ports.py`, `repositories.py` y `clients.py`; no todos son obligatorios para todas las apps.

Las dependencias se rigen por [ARCHITECTURE.md](../../ARCHITECTURE.md). Compartir datos mediante contratos tipados; no importar vistas de otra app ni acceder a su almacenamiento concreto.
