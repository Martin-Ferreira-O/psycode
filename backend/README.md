# Backend

> Actualización de separación: [operación vigente](../docs/OPERACION-SEPARADA.md). Agente en el repositorio independiente `psycode-agent`; control WS autenticado, audio v2 y agenda durable. Las instrucciones históricas incompatibles quedan sustituidas por ese runbook.


El backend es un único proyecto Django. `accounts` tiene implementada la autenticación de SCRUM-31. `alerts` persiste en MongoDB (SCRUM-32) sin rutas HTTP todavía. `dashboard` y `notifications` tienen archivos base pendientes.

Para instalar, crear el usuario local y arrancar, sigue el [README principal](../README.md#primera-instalación). Ejecuta los comandos desde la raíz, donde está `manage.py`.

## Dónde modificar código

| Carpeta | Uso |
|---|---|
| [config](config/README.md) | Variables de entorno, rutas raíz y construcción de servicios. |
| [common](common/README.md) | Formato de respuestas, errores y auditoría compartida. |
| [apps](apps/README.md) | Funcionalidades agrupadas por módulo y tarea Jira. |

Las vistas reciben solicitudes HTTP y llaman a los servicios. Los servicios coordinan las reglas y el acceso a datos. Consulta la [arquitectura](../ARCHITECTURE.md) antes de agregar dependencias entre módulos.

Las rutas usan `/api/v1/` y no llevan barra final. El [contrato API](../API_CONTRACTS.md) define lo que el frontend debe enviar y recibir. Al completar una tarea, actualiza el README del módulo para indicar qué rutas ya funcionan y cómo comprobarlas.
