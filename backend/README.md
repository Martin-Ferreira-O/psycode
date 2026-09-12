# backend/ — Backend previsto

Monolito Django ejecutable. Accounts implementa SCRUM-31; alerts, dashboard y notifications son apps registradas con archivos base, sin funcionalidades. Instrucciones uv/pip en el [README raíz](../README.md).

## Organización

- [config](config/README.md): configuración, composición de dependencias y enrutamiento raíz.
- [common](common/README.md): respuestas, errores y auditoría técnica.
- [apps](apps/README.md): módulos de negocio.

La presentación recibe HTTP y delega a servicios; dominio define reglas; infraestructura implementa persistencia y comunicación. La especificación completa está en [arquitectura](../ARCHITECTURE.md).

## Rutas y desarrollo posterior

Prefijo `/api/v1/`; endpoints sin barra final. Las rutas y ejemplos oficiales están en [API_CONTRACTS.md](../API_CONTRACTS.md). Esta carpeta no añade endpoints.

manage.py en la raíz permite migrar, crear usuario de prueba, verificar y ejecutar el servidor. Cada nueva carpeta mantenida por el equipo incluirá README con propósito, rutas, métodos, dependencias y tarea Jira. Las otras apps se completarán cuando se activen sus tareas; sus rutas todavía responden 404, no datos simulados.
