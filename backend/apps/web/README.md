# Frontend web

React renderiza las pantallas definidas en [frontend/src/pages](../../../frontend/src/pages).
Django conserva las rutas, los permisos de los paneles protegidos y la entrega
de la plantilla `web/app.html`. La interfaz y la API comparten el mismo origen.
El cliente usa cookies HttpOnly y CSRF, con renovación de sesión en el módulo
[api.js](../../../frontend/src/api.js).

## Compilación local

Con Node.js 22.12 o superior, ejecutar desde la raíz:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
```

Vite genera `backend/apps/web/static/web/react/` para el servidor de desarrollo
de Django y `collectstatic`. Para recompilar al editar, ejecutar
`npm run watch --prefix frontend` en otra terminal junto con Django.

Los [componentes compartidos](../../../frontend/src/ui.jsx) usan los [estilos comunes](static/web/css/README.md).
Las [pruebas de navegador](tests/README.md) cubren la interfaz con datos sintéticos.
