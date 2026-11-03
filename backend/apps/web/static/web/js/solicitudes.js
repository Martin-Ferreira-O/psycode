function cabecerasNavegador(iniciales = {}) {
    const headers = new Headers(iniciales);
    headers.set("X-Psycode-Browser", "1");
    const csrf = document.cookie.split("; ").find(c => c.startsWith("csrftoken="));
    if (csrf) headers.set("X-CSRFToken", decodeURIComponent(csrf.slice("csrftoken=".length)));
    return headers;
}

// Traducción de transporte: nunca se muestra el cuerpo de error de la API.
class ErrorSolicitud extends Error {
    constructor(estado = null, codigo = "RESPUESTA_INVALIDA") {
        super("No se pudo completar la solicitud.");
        this.name = "ErrorSolicitud";
        this.estado = estado;
        this.codigo = codigo;
    }
}

async function leerRespuesta(response) {
    // apiRequest ya entregó el control al manejo de sesión.
    if (!response) throw new ErrorSolicitud(401, "SESION_FINALIZADA");
    if (!response.ok) throw new ErrorSolicitud(response.status);
    if (response.status === 204) return null;

    let contenido;
    try {
        contenido = await response.json();
    } catch {
        throw new ErrorSolicitud();
    }
    if (contenido?.success !== true || contenido.data == null) {
        throw new ErrorSolicitud();
    }
    return contenido.data;
}

async function solicitarJson(url, opciones = {}, transporte = fetch) {
    let response;
    try {
        response = await transporte(url, opciones);
    } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ErrorSolicitud(0, "SIN_CONEXION");
    }
    return leerRespuesta(response);
}
