# Pruebas del frontend

Desde la raíz, con Node.js 18 o superior, sin instalar dependencias:

```sh
node --test backend/apps/web/tests/*.test.cjs
```

Las pruebas de solicitudes ejecutan los scripts reales en contextos aislados y usan respuestas HTTP controladas. Cubren estados HTTP, respuestas inválidas, ausencia de resultados, errores de red, personalización de mensajes y delegación al manejo de sesión.
