# JavaScript del frontend

Scripts clásicos, sin framework ni compilación, cargados por las plantillas Django.

- `solicitudes.js`: `solicitarJson` y `leerRespuesta` validan el envelope; errores HTTP, de red y respuestas inválidas producen `ErrorSolicitud`. No propaga mensajes técnicos del servidor. 204 devuelve `null`.
- `estados.js`: `mostrarCarga`, `mostrarVacio`, `mostrarError`, `limpiarEstado`, `mostrarEstado` y `establecerCargaBoton` presentan estados accesibles. Los mensajes por HTTP pueden reemplazarse con textos **locales** mediante `mensajes`. No pasar `error.message` ni `error.details` de la API.
- `api.js`: manejo existente de tokens y sesión. `apiGetDatos` usa los helpers anteriores; `apiGet` y `apiPost` conservan su retorno `Response`. Un 401 protegido delega a `redirigirAlLogin`; el login público distingue credenciales incorrectas.
- `components.js`: conecta cierre de sesión. `utils.js`: formatos compartidos.
- `alertas_detalle.js`: presentación compartida de niveles 1–3 y fragmentos de transcripción con `textContent`. El número 1/2/3 tiene prioridad sobre el semáforo y se aceptan BAJO/MEDIO/ALTO. Cargar antes de `dashboard.js` o `evaluaciones.js`; `descripcion` se consulta en el detalle y se limpia al abrir/cerrar el modal.
- `completarContenidoDetalle`, en el mismo archivo, presenta los campos comunes de ambos modales: fecha/hora combinadas, sesión, estado, transcripción y evaluación registrada. Ambos utilizan la plantilla `components/modal_detalle.html`.
- `login.js`, `dashboard.js`, `evaluaciones.js`: comportamiento propio de cada pantalla.

Cargar `solicitudes.js` y `estados.js` antes de `api.js` y del script de pantalla.
`mostrarError(contenedor, error, {mensajes: {404: 'La alerta ya no está disponible.'}, reintentar: cargar})` ofrece reintento solo ante red, 408, 429, 500, 502, 503 o 504. La pantalla debe aportar una función que sea seguro repetir y que gestione su carga. Las escrituras requieren verificar antes su resultado; el helper nunca las repite automáticamente.
