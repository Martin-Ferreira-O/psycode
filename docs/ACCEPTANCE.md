# Revisión y aceptación — SCRUM-30

> Registro histórico de la entrega documental. SCRUM-31 fue activada posteriormente y ya tiene código y pruebas: ver [SCRUM-31](SCRUM-31.md). Las afirmaciones de “sin implementación” de esta página describen exclusivamente la fase SCRUM-30.

## Entrega actual

Arquitectura, rutas, nombres Django, interfaces entre módulos y ejemplos para desarrollo en paralelo. Solo Markdown y carpetas documentadas; **no se ejecutaron pruebas de un backend porque no existe implementación**.

La revisión documental comprueba:

- Cada carpeta mantenida por el equipo tiene README con propósito, rutas o ausencia, métodos previstos y dependencias.
- Las doce operaciones HTTP se corresponden con once patrones de URL; GET y POST evaluación comparten uno.
- Cada operación define acceso, petición, respuesta y errores; los ejemplos JSON son válidos y los envelopes coherentes, salvo 204 sin cuerpo.
- Los ejemplos usan UUID válidos, sumas consistentes y la misma forma de Evaluation en listado, detalle y evaluación.
- Las once tareas del handoff tienen correspondencia documental, sin atribuir implementación ni responsables nuevos.
- Los enlaces internos se resuelven y no hay archivos ejecutables, migraciones, credenciales ni librerías instaladas como parte de esta fase.
- El Excel y la transcripción clínica permanecen intactos, con discrepancia documentada por separado.

## Escenarios para implementación futura

Estos son criterios especificados, **no pruebas ejecutadas ni funcionalidades ya disponibles**.

| Área | Escenario | Resultado esperado |
|---|---|---|
| HTTP | JSON inválido, campo extra, UUID mal formado | 400 con error estándar |
| HTTP | Tipo de contenido incorrecto / método no soportado | 415 / 405; Allow para 405 |
| Auth | Credenciales incorrectas o usuario inexistente | 401 AUTH_INVALID_CREDENTIALS |
| Auth | Contraseña correcta con usuario inactivo | 403 AUTH_USER_INACTIVE |
| Auth | Ruta protegida sin token o token expirado | 401 específico, sin datos de recurso |
| Auth | Refresh válido y después reutilización | Nuevo par; antiguo rechazado con 401 |
| Auth | Logout y repetición con access aún válido | 204 sin cuerpo; refresh revocado |
| Auth | Access emitido antes de logout | Conserva vigencia restante; no prometer revocación inmediata |
| Auth | Refresh de otro usuario en logout | 403 AUTH_FORBIDDEN |
| Recuperación | Correo desconocido / proveedor de correo caído | 404 / 503 específicos |
| Recuperación | Token usado, vencido o sustituido | 400 AUTH_INVALID_RESET_TOKEN |
| Recuperación | Contraseña rechazada y luego válida | Error no consume token; segundo intento puede completar |
| Recuperación | Confirmación válida | Contraseña cambia, token se consume; access y refresh previos quedan inválidos |
| Alertas | Combinación q, box, fechas, estado y revisadas | AND entre filtros; búsqueda q literal |
| Alertas | Metacaracteres de regex en q | Se buscan literalmente, no se ejecuta regex del usuario |
| Alertas | Misma fecha en varias alertas | Orden estable por UUID ascendente |
| Alertas | Sin coincidencias / offset fuera de rango | 200, items vacío; total representa coincidencias reales |
| Alertas | Fechas invertidas, limit 0/101, offset negativo | 400 VALIDATION_ERROR |
| Alertas | Filtros contradictorios de revisadas/estado | 200 con cero coincidencias |
| Alertas | UUID válido inexistente | 404 ALERTA_NO_ENCONTRADA |
| Persistencia | MongoDB/SQLite no disponibles | 503 PERSISTENCE_UNAVAILABLE, nunca lista vacía ficticia |
| Evaluación | Estado válido y alerta pendiente | 201, autor autenticado, hora servidor, estado y trazabilidad consistentes |
| Evaluación | Autor o fecha enviados en JSON | 400; cliente no puede suplantar evaluador |
| Evaluación | Dos registros simultáneos | Un 201 y un 409; una sola evaluación persistida |
| Evaluación | Repetir mismo resultado | 409; GET permite confirmar registro anterior |
| Evaluación | GET de alerta existente sin evaluación | 404 EVALUACION_NO_ENCONTRADA |
| SCRUM-40 | Listado revisadas=true | Cada fila trae Evaluation; no requiere una petición por fila |
| Dashboard | Semana, mes, año bisiesto y fecha histórica | Límites de calendario correctos en Santiago |
| Dashboard | Cambio de hora local | Intervalos UTC representan días locales, sin asumir 24 horas |
| Dashboard | Período sin alertas | Conteos cero; registros vacío; conservar límites y zona |
| Dashboard | Período con datos | Pendientes + revisadas = total; suma severidades y conteos diarios coinciden |
| Dashboard | Revisión posterior a período histórico | Se muestra estado actual, no reconstrucción histórica |
| Registro interno | Alerta válida | Persistencia antes de envío; trazabilidad asignada por servidor |
| Registro interno | UUID duplicado o persistencia fallida | Error tipado; no enviar notificación |
| Notificación | Teams acepta | Un intento; no enviar correo |
| Notificación | Teams falla o supera 10 segundos | Intentar correo y auditar contingencia |
| Notificación | Ambos canales fallan | Resultado fallido; conservar alerta; sin garantía de entrega |
| Notificación | NULO o envíos deshabilitados | Resultado omitido y cero intentos |
| Privacidad | Notificación y logs | Ausencia de pacientes, audio, descripción libre, métodos operativos y secretos |

## Capa frontend: dashboard e historial

Ampliación arquitectónica solicitada el 2026-09-12. Son criterios para implementación futura, no pruebas ejecutadas.

| Escenario | Resultado esperado |
|---|---|
| Inicio de sesión válido | Acceso al dashboard; navegación protegida y permisos comprobados en backend |
| Seleccionar semana o mes | Resumen y estadísticas consultan el mismo período y fecha de referencia |
| Abrir historial del período | Listado usa las fechas inclusivas devueltas por el dashboard |
| Abrir todo el historial | Consulta sin restricción de fechas |
| Consultar historial | Filas con identificador, box, riesgo, severidad, fecha/hora y estado; orden y paginación del servidor |
| Combinar o limpiar filtros | Parámetros contractuales; offset vuelve a cero; respuestas antiguas no sustituyen la consulta vigente |
| Abrir y cerrar detalle | Se conservan filtros y página; semáforo con texto y modal accesible por teclado |
| Guardar evaluación | Actualizar detalle, listado, registro y agregados; autor y fecha asignados por backend |
| Conflicto o respuesta de guardado perdida | Consultar evaluación existente, sin sobrescribir ni repetir automáticamente el POST |
| Historial vacío o error de consulta | Estados diferentes; el error ofrece reintento y no muestra cero alertas como dato válido |
| Cerrar sesión o perder autenticación | Limpiar datos y credenciales locales; volver al inicio de sesión |

## Cierre de fase

### Verificación realizada el 2026-09-12

Revisión automática de los 16 Markdown: README presente en cada carpeta, 21 ejemplos JSON parseables, 44 enlaces locales con destinos y anclas válidos, 12 operaciones HTTP sobre 11 patrones de URL. Se comprobaron UUID de ejemplos, envelopes, sumas del dashboard, correspondencia de las once tareas y ausencia de archivos ejecutables en la entrega. Estos controles verifican documentación, no comportamiento de un servidor.

La entrega queda lista para revisión de Martin y el equipo. No marca tickets Jira como terminados ni asigna tareas. La implementación del backend de estadísticas y las decisiones clínicas previas a producción siguen siendo responsabilidades pendientes del equipo, sin bloquear esta definición de contratos.

Fuentes de revisión: [arquitectura](../ARCHITECTURE.md), [contratos](../API_CONTRACTS.md), [handoff](../HANDOFF.md) y [observaciones](SOURCE_NOTES.md).
