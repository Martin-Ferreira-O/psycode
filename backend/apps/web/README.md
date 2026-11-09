# Frontend web

Plantillas Django en `templates/web/`, estilos y JavaScript clásicos en `static/web/`. No requiere framework frontend ni compilación. `views.py` entrega pantallas; el navegador consume la API mediante los scripts existentes.

| Ruta | Pantalla | Fuente actual |
|---|---|---|
| `/` | Autenticación | API de accounts |
| `/dashboard` | Dashboard e historial con detalle y evaluación | Datos y guardado simulados en memoria |
| `/alertas` | Acceso al historial | Redirige a `/dashboard#historial-alertas` |
| `/evaluaciones` | Registro de evaluaciones | `GET /api/v1/alerts?revisadas=true` |

SCRUM-46 centraliza presentación de estados y errores. Consulta [scripts](static/web/js/README.md), [estilos](static/web/css/README.md), [pruebas](tests/README.md) y [alcance y verificación](../../../docs/SCRUM-46.md).

Las pantallas conservan datos en memoria durante un fallo; no se agregan respuestas clínicas ni campos de formulario al almacenamiento del navegador. Login conserva los campos y bloquea envíos simultáneos. Evaluaciones distingue carga, éxito vacío y fallo, oculta los resultados anteriores durante la consulta y permite reintentar sin recargar la página. Historial usa el estado vacío común y el modal usa la validación común sin modificar la lógica simulada de evaluación.

El 401 de las solicitudes protegidas sigue pasando por `api.js`, que limpia sesión y redirige al login. El 401 del login público muestra credenciales incorrectas. No se implementa renovación de tokens.
