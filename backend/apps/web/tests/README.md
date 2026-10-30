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
