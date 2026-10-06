# JavaScript del frontend

Scripts clásicos, sin framework ni compilación, cargados por las plantillas Django.

- `solicitudes.js`: `solicitarJson` y `leerRespuesta` validan el envelope; errores HTTP, de red y respuestas inválidas producen `ErrorSolicitud`. No propaga mensajes técnicos del servidor. 204 devuelve `null`.
- `estados.js`: `mostrarCarga`, `mostrarVacio`, `mostrarError`, `limpiarEstado`, `mostrarEstado` y `establecerCargaBoton` presentan estados accesibles. Los mensajes por HTTP pueden reemplazarse con textos **locales** mediante `mensajes`. No pasar `error.message` ni `error.details` de la API.
- `api.js`: manejo existente de tokens y sesión. `apiGetDatos` usa los helpers anteriores; `apiGet` y `apiPost` conservan su retorno `Response`. Un 401 protegido delega a `redirigirAlLogin`; el login público distingue credenciales incorrectas.
- `components.js`: conecta cierre de sesión. `utils.js`: formatos compartidos.
- `login.js`, `dashboard.js`, `evaluaciones.js`, `estadisticas.js`: comportamiento propio de cada pantalla.

Cargar `solicitudes.js` y `estados.js` antes de `api.js` y del script de pantalla.
`mostrarError(contenedor, error, {mensajes: {404: 'La alerta ya no está disponible.'}, reintentar: cargar})` ofrece reintento solo ante red, 408, 429, 500, 502, 503 o 504. La pantalla debe aportar una función que sea seguro repetir y que gestione su carga. Las escrituras requieren verificar antes su resultado; el helper nunca las repite automáticamente.
