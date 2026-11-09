# Pruebas del frontend

Desde la raíz, con Node.js 18 o superior, sin instalar dependencias:

```sh
node --test backend/apps/web/tests/*.test.cjs
```

Las pruebas de solicitudes ejecutan los scripts reales en contextos aislados y usan respuestas HTTP controladas. Cubren estados HTTP, respuestas inválidas, ausencia de resultados, errores de red, personalización de mensajes y delegación al manejo de sesión.

## Integración en navegador

`frontend.browser.cjs` usa las plantillas y scripts reales con respuestas HTTP interceptadas por Playwright. No necesita una cuenta real ni escribe evaluaciones en el backend. Requiere una instalación de Playwright con Chromium disponible; no es una dependencia de producción del proyecto.

Arrancar Django en una terminal:

```sh
.venv/bin/python manage.py runserver 127.0.0.1:8765 --settings=backend.config.test_settings --insecure --noreload
```

En otra terminal, si Playwright está disponible para Node:

```sh
node backend/apps/web/tests/frontend.browser.cjs
```

Si está instalado fuera del proyecto, indicar `PLAYWRIGHT_MODULE=/ruta/a/node_modules/playwright` al ejecutar. Opcionalmente, `CHROMIUM_PATH` selecciona un navegador instalado y `FRONTEND_TEST_URL` cambia el origen (por defecto `http://127.0.0.1:8765`). No usar un entorno de producción.

La prueba cubre carga, bloqueo de doble envío, restauración del botón, mensajes seguros, reintento, campos conservados, códigos 400/404/409/503, respuesta vacía/incompleta/con datos, 401 con redirección, filtros del historial y selección del modal.

Para comprobar la trazabilidad de notificaciones en la pantalla de bitácora,
con el mismo servidor y las mismas variables de navegador:

```sh
node backend/apps/web/tests/bitacora-notificaciones.browser.cjs
```

Usa la pantalla real y API simulada para verificar modalidad, resumen y conteos,
respaldo por fallo parcial, ausencia de destinatarios, filtro de resúmenes,
consulta de eventos históricos y detalle en móvil. No conecta MongoDB ni envía
correos. `FRONTEND_SCREENSHOT_DIR` permite guardar una captura del detalle en un
directorio existente.

## Gestión de PCs SCRUM-96

`pcs.browser.cjs` prueba registro sin catálogo, alta, instalación recuperable y
revocación contra el backend real,
acceso del supervisor con cookies reales, ausencia de secretos en el listado y
almacenamiento del navegador, teclado y anchos 375/768/1024/1440. Intercepta
solamente el listado y el historial en su segunda parte para comprobar carga,
vacío, errores, filtros, paginación y tiempos estimados/desconocidos.

Usar una **base SQLite nueva y sintética**, sin PCs registrados. El servidor debe
usar `backend.config.test_settings`. Crear los usuarios `pcs-browser` (admin) y
`pcs-supervisor` (supervisor), con correos de ejemplo y la contraseña sintética
`Synthetic-browser-2026!`, mediante `User.objects.create_user`. No usar cuentas o
bases clínicas. La prueba crea un PC y lo deja revocado; usar una base nueva al
repetirla.

```sh
FRONTEND_TEST_URL=http://127.0.0.1:8768 node backend/apps/web/tests/pcs.browser.cjs
```

`PLAYWRIGHT_MODULE` selecciona una instalación externa de Playwright;
`CHROMIUM_PATH` permite indicar Chromium. `FRONTEND_SCREENSHOT_DIR` guarda las
capturas de escritorio, móvil e historial en un directorio existente.

El flujo actual de `pcs.browser.cjs` necesita HTTPS en el servidor de prueba,
`PC_PAIRING_AGENT_PYTHON` apuntando al Python con el agente actualizado instalado
y `SSL_CERT_FILE` apuntando a la CA del certificado local de prueba. El navegador
acepta solamente para esta prueba el certificado sintético; el agente verifica
esa CA durante HTTPS y WSS. La prueba no desactiva la verificación TLS del agente.


Para ejecutar el flujo completo con SQLite nueva, certificados sintéticos y
servidor HTTPS/estáticos preparados automáticamente:

```sh
uv run --no-sync python -m tests.cross.run_pc_browser --agent-python /ruta/al/agente/.venv/bin/python --playwright-module /ruta/a/node_modules/playwright --chromium-path /ruta/a/chromium
```

El Python indicado debe tener instalado el agente actualizado. El runner solo
usa cuentas, credenciales y datos sintéticos, conserva capturas en el directorio
que informa y termina su servidor al concluir. `--artifacts-dir` selecciona ese
directorio. No prepara ni utiliza la base habitual del servidor. También cubre
fallo independiente de salas, actualización automática conservando foco y
acciones de instalación separadas de una desconexión normal.

El runner comprueba el aviso si no hay instalador publicado. Para comprobar
ambas descargas en Chromium, apunta `PC_WINDOWS_INSTALLER_DIR` a un directorio
de prueba con la estructura descrita en [Gestión de PCs](../../../../docs/GESTION-DE-PCS.md)
y pasa el hash esperado del `.exe` en `PC_BROWSER_INSTALLER_SHA256`. El navegador
descarga el archivo y verifica su hash sin ejecutarlo.
