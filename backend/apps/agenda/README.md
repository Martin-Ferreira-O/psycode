# Agenda Excel

> Actualización de separación: [operación vigente](../../../docs/OPERACION-SEPARADA.md). Agente en el repositorio independiente `psycode-agent`; control WS autenticado, audio v2 y agenda durable. Las instrucciones históricas incompatibles quedan sustituidas por ese runbook.


`AgendaService` mantiene en memoria la ocupación de las salas registradas/configuradas (3–7 en el despliegue inicial),
sin guardar datos personales. Cada carga reemplaza los boxes incluidos y conserva
los demás. Las inasistencias, cancelaciones y anulaciones no ocupan el box.

## Ejecutar

Desde la raíz del proyecto:

```powershell
uv sync --locked
uv run python
```

En Python, conservar la misma instancia para cargar y consultar:

```python
from datetime import datetime
from backend.apps.agenda.services import AgendaService

agenda = AgendaService()

# Un archivo.
informe = agenda.load_excel(r"C:\ruta\box3.xlsx")

# Los cinco archivos juntos.
informe = agenda.load_excel([r"C:\ruta\box3.xlsx", r"C:\ruta\box4.xlsx",
                            r"C:\ruta\box5.xlsx", r"C:\ruta\box6.xlsx", r"C:\ruta\box7.xlsx"])

print(informe.aceptadas, informe.boxes_actualizados)
print(informe.rechazadas)  # Archivo, hoja, fila y motivo.
agenda.is_busy(3, datetime(2026, 10, 13, 10, 30))  # Hora de Santiago.

# Actualizar solo un box.
agenda.load_excel(r"C:\ruta\box3_actualizado.xlsx")
```

El box se identifica por la cabecera A2 o la columna `CLINICA FISICA`/`BOX`, con
títulos de citas en la fila 7. Cada box debe aparecer en un único archivo del lote.
Un archivo ilegible cancela el lote; una fila inválida se reporta y se continúa.
Un box identificado sin citas válidas queda vacío. Un box todavía no cargado
produce `AgendaNotLoaded`. Cerrar el proceso elimina las agendas de memoria.

## Pruebas

```powershell
uv run python manage.py test backend.apps.agenda --settings=backend.config.test_settings
```

Las pruebas de Excel generan sus propios archivos sintéticos.
