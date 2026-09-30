# SCRUM-46 — Estados y errores comunes del frontend

## Alcance implementado

Se conserva el frontend existente: Django, plantillas y JavaScript clásico, sin dependencias de producción nuevas. La presentación compartida reside en `backend/apps/web/static/web/js/estados.js`; la lectura de respuestas en `solicitudes.js`. Las operaciones y sus datos siguen a cargo de cada pantalla.

| Criterio | Implementación |
|---|---|
| Carga común | `mostrarCarga` y `establecerCargaBoton`; botón bloqueado durante login y protección contra consultas simultáneas de evaluaciones |
| Ausencia de información | `mostrarVacio`; evaluaciones solo considera vacío un éxito con `items: []`; historial diferencia ausencia de alertas y filtros sin coincidencias |
| Error común | `mostrarError` y catálogo local por HTTP; no muestra cuerpos, trazas ni mensajes técnicos del servidor |
| 400 | Revisar los datos ingresados |
| 404 | Información no encontrada; admite mensaje específico de la pantalla |
| 409 | Información modificada o ya registrada; consultar su estado antes de continuar |
| 503 | Servicio temporalmente no disponible; reintento explícito |
| Reintentos | Botón accesible para red, 408, 429, 500, 502, 503 y 504 cuando la pantalla proporciona una operación segura; sin repetición automática |
| Conservar datos | Login mantiene usuario/contraseña en sus campos; filtros y selección del historial permanecen en memoria; un fallo del registro no borra los datos ya obtenidos |
| Mensajes específicos | Opción `mensajes` indexada por HTTP, con textos locales; usada en login y registro de evaluaciones |
| Sesión | 401 protegido delega al flujo existente de `api.js`; 401 público informa credenciales incorrectas |
| Accesibilidad | Roles `status`/`alert`, anuncios vivos, estado ocupado de controles y tabla, foco visible y reintento de al menos 44 px |

El registro oculta su tabla durante carga y error para no presentar datos anteriores como actuales. Un cuerpo inválido, JSON ilegible o `items` ausente genera error, nunca «sin evaluaciones». No se persisten respuestas clínicas ni borradores en almacenamiento del navegador.

## Límites de la integración

El historial, el guardado de evaluación de su modal y las estadísticas todavía funcionan con datos simulados. SCRUM-46 integra sus estados aplicables sin convertir esas operaciones en solicitudes reales. La conexión futura del historial/guardado con la API corresponde a sus tareas funcionales; debe consumir los helpers compartidos. Antes de reintentar una escritura de resultado incierto, esa operación debe consultar su estado, tal como exige la arquitectura.

La interfaz de recuperación de contraseña existente no se amplía ni se rediseña: su solicitud y presentación reutilizan los helpers para evitar mensajes técnicos. No se modifican endpoints de autenticación, duración de tokens ni renovación de sesión. Tampoco se modifica el diseño del login.

## Verificación

- 11 pruebas automatizadas de los scripts comunes: estados HTTP (incluido HTML de error), red, cancelación, respuesta inválida, vacío, 204, personalización y 401 protegido/público.
- Integración automatizada en Chromium contra las plantillas reales con respuestas de API controladas: carga, prevención de doble envío, reintento, conservación de campos, errores 400/404/409/503, lista vacía, listado con datos, respuesta incompleta, sesión, filtros y selección de evaluación.
- Inspección visual del error y reintento en login a 375 px y registro de evaluaciones a 1280 px.
- `manage.py check --settings=backend.config.test_settings`: sin incidencias.
- Pruebas Django de accounts, alerts y notifications: 69 ejecutadas, sin fallos, una omitida por no disponer de MongoDB de pruebas.

Comandos e instrucciones para repetir las pruebas en [tests del frontend](../backend/apps/web/tests/README.md).
