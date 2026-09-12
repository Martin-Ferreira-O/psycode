# Arquitectura — Psycode API

**Estado:** arquitectura SCRUM-30 conservada; Martin activó SCRUM-31 y la generación de las apps. Accounts y la base Django están implementados. El resto continúa como diseño futuro. Nombre técnico `psycode-api`; API pública `/api/v1/`. Ver [implementación SCRUM-31](docs/SCRUM-31.md).

## 1. Decisión y alcance

Un **monolito modular con capas ligeras** permite desplegar un solo backend y repartir trabajo por módulos. Los contratos separan el desarrollo de frontend, consultas, persistencia, evaluaciones y notificaciones. Las capas son responsabilidades dentro de cada módulo, no servicios distribuidos.

No se incorporan microservicios, buses de eventos, CQRS, contenedores de inyección, repositorios genéricos, colas ni componentes de negocio preconstruidos. Tampoco se incorporan captura de audio, transcripción, clasificación automática, gestión de pacientes o CRUD de sesiones/boxes. `sesion_id` y `box` son referencias recibidas por el caso de uso interno de registro.

### Base tecnológica prevista

| Tecnología | Uso |
|---|---|
| Python 3.12 y Django 5.2, con parche mantenido al implementar | Base de referencia del equipo; compatible con el mínimo Python 3.10+ del handoff |
| Django REST Framework | Validación HTTP, vistas y serialización explícita |
| Simple JWT | Emisión y validación de tokens; rotación y revocación de refresh |
| ORM y autenticación de Django + SQLite | Usuarios, contraseñas, recuperación y estado de tokens |
| PyMongo | Controlador oficial para alertas y evaluaciones; no usar el ORM relacional para MongoDB |
| HTTPS a Teams Workflows y correo mediante Django | Adaptadores de notificación propios |

La elección de librerías base fue confirmada por Martin. SCRUM-31 fija dependencias en pyproject.toml y uv.lock, con requirements.txt exportado para pip. Se agregan django-cors-headers y python-dotenv para el origen frontend y configuración local. Versiones efectivamente verificadas y comandos en [README](README.md).

## 2. Módulos, capas y dependencias

```text
backend/
  config/             composición, configuración y rutas raíz
  common/             respuestas, errores y auditoría técnica compartida
  apps/
    accounts/         autenticación y recuperación
    alerts/           persistencia, consulta y evaluación de alertas
    dashboard/        resumen y estadísticas sobre alertas
    notifications/    envío por Teams y contingencia por correo
```

Cada carpeta de código incluye su propio README. Accounts ya tiene capas implementadas, migraciones, comando y tests; las otras apps tienen archivos base sin comportamiento. Solo se crearán subcarpetas adicionales cuando su contenido lo justifique.

| Capa | Archivos previstos | Regla |
|---|---|---|
| Presentación/API | `urls.py`, `views.py`, `serializers.py` | Recibe HTTP, valida estructura, identifica usuario, delega y traduce resultado/errores |
| Aplicación | `services.py` | Coordina casos de uso, permisos y efectos explícitos |
| Dominio | `domain.py` | Tipos y reglas del negocio sin imports de Django, DRF, PyMongo ni clientes de red |
| Infraestructura | `repositories.py`, `clients.py`; `models.py` en accounts | Implementa almacenamiento y comunicación externa |

Los servicios de alertas reciben interfaces específicas definidas en `alerts/ports.py`, implementadas por infraestructura. Se pasan como argumentos o dependencias de constructor; `config` conecta las implementaciones. Los objetos de intercambio serán estructuras tipadas de Python, sin `Request`, `Response`, `QuerySet`, `ObjectId` ni cursores de MongoDB.

- API → aplicación → dominio e interfaces de almacenamiento/envío.
- Infraestructura implementa interfaces e interpreta resultados del proveedor.
- Dashboard usa `AlertQueryPort`, no importa el repositorio concreto de MongoDB.
- Alerts recibe un `AlertNotifier` implementado por notifications; no conoce la URL de Teams.
- Notifications no consulta ni modifica alertas: recibe el payload ya permitido.
- Accounts aprovecha autenticación, hashing y recuperación de Django; no reimplementa criptografía ni replica su modelo de usuarios en un segundo dominio.
- Common no importa módulos de negocio y no recibe lógica específica de alertas.
- La orquestación de registro y envío es explícita; no se oculta en señales de guardado.

### Contratos de colaboración

Firmas conceptuales que deben respetar las futuras implementaciones. Los DTO de alerta, evaluación, página y notificación se definen por los campos de [API_CONTRACTS.md](API_CONTRACTS.md); estas firmas no son endpoints adicionales.

| Interfaz / método previsto | Entrada | Salida / condición |
|---|---|---|
| `AlertQueryPort.list_alerts(filters, limit, offset)` | Filtros normalizados del contrato | `AlertPage`: total e items tipados, sin envelope HTTP |
| `AlertQueryPort.get_alert(alerta_id)` | UUID | `AlertDetail` o `AlertNotFound` |
| `AlertQueryPort.get_evaluation(alerta_id)` | UUID | `Evaluation` o `AlertNotFound` / `EvaluationNotFound` |
| `AlertQueryPort.summarize(start_utc, end_utc)` | Intervalo con fin exclusivo | Total, pendientes, revisadas y conteos por semáforo |
| `AlertQueryPort.daily_counts(start_utc, end_utc, timezone)` | Intervalo y zona Santiago | Lista ordenada de fecha local y total |
| `AlertWritePort.insert_alert(alert)` | Alerta validada sin evaluación | Alerta persistida o `AlertAlreadyExists` |
| `AlertWritePort.record_evaluation(alerta_id, evaluation)` | UUID y evaluación con autor autenticado | Evaluación registrada o `AlertNotFound` / `EvaluationAlreadyRegistered` |
| `AlertNotifier.notify_alert(alerta_id, payload)` | UUID para auditoría y payload mínimo | `NotificationResult`; no borra ni modifica la alerta |
| `AuditWriter.record(event)` | Evento técnico con resultado | Escritura de auditoría; sin datos clínicos libres ni secretos |

`AlertsService` expondrá `register_alert`, `list_alerts`, `get_alert`, `record_evaluation` y `get_evaluation`; `DashboardService`, `get_summary` y `get_statistics`; `AccountsService`, `login`, `refresh`, `logout`, `get_current_user`, `request_password_reset` y `confirm_password_reset`. Los errores tipados se traducen a los códigos públicos en presentación. No se exponen trazas internas al cliente.

## 3. Persistencia y flujos

### SQLite

Accounts tendrá un usuario propio basado en las capacidades de Django, con UUID estable desde la primera migración. Conservará usuario, correo institucional único, nombre, contraseña hasheada y estado activo. Los nombres internos de Django se traducen a los nombres públicos del contrato. El usuario se define antes de iniciar migraciones; los usuarios de prueba pertenecen a SCRUM-31.

Refresh y revocaciones se almacenan en SQLite. La sesión de autenticación no es la sesión clínica indicada por `sesion_id`. No se crean relaciones SQL con colecciones MongoDB.

### MongoDB

Colección `alerts`, con `alerta_id` UUID serializado canónicamente como string e índice único. Fechas almacenadas como fechas UTC, serializadas ISO 8601. `semaforo` se deriva de `nivel_severidad`; no se permite una segunda fuente contradictoria. Las evaluaciones se incrustan como objeto único `evaluacion` o `null` en el mismo documento.

Una evaluación guarda UUID del profesional y una copia de su identificador visible (`usuario`) al evaluar. No depende de una consulta posterior a SQLite para reconstruir la trazabilidad. El actor llega del contexto autenticado, nunca del JSON enviado por el frontend.

La actualización de `evaluacion`, `estado_evaluacion` y `trazabilidad.actualizada_en` será atómica y condicionada a `estado_evaluacion=pendiente`. Dos solicitudes concurrentes no pueden registrar dos evaluaciones: una obtiene éxito y la otra conflicto. La consulta distinguirá conflicto de alerta inexistente.

Índices previstos: unicidad de `alerta_id`; orden por `fecha_hora` y `alerta_id`; filtros por `box`/fecha y por `estado_evaluacion`/fecha. No se introduce un buscador externo para `q`.

### Registro y notificación

```text
Entrada interna validada
  → guardar alerta en MongoDB
  → si semáforo no es NULO: Teams
      → si falla: correo
  → registrar resultado de cada intento
```

El contrato de registro se define para SCRUM-32/41; no implica crear un productor de alertas. Los datos de prueba invocarán el registro con envío deshabilitado por defecto. No habrá `POST /alerts` público en esta fase.

Los fallos de MongoDB impiden el registro y el envío. Los fallos de notificación no revierten una alerta guardada. La auditoría técnica usa eventos estructurados en el sistema de logging de Django; la trazabilidad de evaluación se conserva además en el documento. Un fallo del destino de logs debe dirigirse al log de error local, nunca presentarse como prueba de entrega.

La secuencia es síncrona y acotada según el contrato. No hay transacción entre MongoDB, SQLite, Teams y correo, ni garantía de entrega exactamente una vez. Una caída entre persistir y notificar puede dejar una alerta sin aviso; la recuperación automática duradera queda fuera del backlog actual. Esta limitación debe revisarse antes de uso clínico real.

## 4. Trabajo en paralelo

| Tarea | Responsabilidad | Módulo / consumo | Responsable del handoff |
|---|---|---|---|
| SCRUM-30 | Arquitectura y contratos | Toda la documentación | Martin Ferreira |
| SCRUM-31 | Auth, SQLite, recuperación y pruebas | accounts | Martin Ferreira |
| SCRUM-32 | Persistencia, repositorios y datos sintéticos | alerts / infraestructura | Álvaro Farfán Reyes |
| SCRUM-33 | Listado, filtros y detalle | alerts / consulta | Bernardo Arenas |
| SCRUM-34 | Evaluación y transición atómica | alerts / evaluación | Alejandra Ulloa |
| SCRUM-35 | Interfaz de autenticación | API auth | Bernardo Arenas |
| SCRUM-36 | Dashboard y estadísticas frontend | API dashboard | Sin asignar |
| SCRUM-37 | Historial frontend | GET alerts | Danya Andrea Duran Fabres |
| SCRUM-39 | Modal de detalle/evaluación | GET detalle y POST evaluación | Danya Andrea Duran Fabres |
| SCRUM-40 | Registro de evaluaciones frontend | GET alerts con revisadas y GET evaluación | Aarón Orellana |
| SCRUM-41 | Teams y correo de contingencia | notifications | Sin asignar |

El backlog asigna SCRUM-36 al frontend pero necesita agregaciones backend. Su contrato y módulo se definen aquí; **el responsable de implementar esas agregaciones no está asignado**. No se atribuye ese trabajo a otra persona ni se marca la tarea como implementada.

El frontend puede preparar respuestas simuladas con los ejemplos del contrato. Los desarrolladores backend podrán usar dobles de `AlertQueryPort`, `AlertWritePort` y `AlertNotifier`, sin esperar conexiones reales. Si varias personas editan `alerts/services.py`, coordinarán integración por métodos; no se crean módulos artificiales para evitar toda colaboración.

## 5. Fuentes y mantenimiento

Referencias consultadas para esta definición, 2026-09-12:

- [Compatibilidad Python/Django](https://docs.djangoproject.com/en/5.2/faq/install/).
- [Usuario personalizado de Django](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/).
- [Vistas DRF](https://www.django-rest-framework.org/api-guide/views/) y [autenticación](https://www.django-rest-framework.org/api-guide/authentication/).
- [Simple JWT](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/).
- [Controlador oficial PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/).
- [Teams: webhooks y Workflows](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/what-are-webhooks-and-connectors).

Context7 no estuvo disponible durante la revisión; se consultaron las fuentes oficiales como alternativa. El contrato y las decisiones locales prevalecen sobre los ejemplos de respuesta predeterminados de las librerías. Los criterios de aceptación están en [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).
