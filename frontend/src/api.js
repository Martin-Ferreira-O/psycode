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

const mensajesSolicitud = Object.freeze({
    0: "No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.",
    400: "Revisa los datos ingresados e inténtalo de nuevo.",
    401: "Tu sesión terminó. Inicia sesión nuevamente.",
    403: "No tienes permiso para realizar esta operación.",
    404: "No encontramos la información solicitada.",
    409: "La información cambió o ya fue registrada. Consulta su estado actual antes de continuar.",
    408: "La solicitud tardó demasiado. Inténtalo de nuevo.",
    429: "Hay demasiadas solicitudes. Espera un momento antes de volver a intentarlo.",
    500: "No pudimos completar la solicitud. Inténtalo de nuevo más tarde.",
    502: "El servicio no está disponible temporalmente. Inténtalo de nuevo más tarde.",
    503: "El servicio no está disponible temporalmente. Inténtalo de nuevo más tarde.",
    504: "La solicitud tardó demasiado. Inténtalo de nuevo.",
});

function describirError(error, mensajes = {}) {
    const estado = error instanceof ErrorSolicitud ? error.estado : null;
    return {
        mensaje: mensajes[estado] || mensajesSolicitud[estado] ||
            "No pudimos completar la solicitud. Inténtalo de nuevo más tarde.",
        recuperable: [0, 408, 429, 500, 502, 503, 504].includes(estado),
        omitido: error?.name === "AbortError" || error?.codigo === "SESION_FINALIZADA",
    };
}

// Las credenciales solo viajan en cookies HttpOnly; nunca se leen desde JavaScript.
function retirarTokensAntiguos() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
}

function limpiarSesion() {
    retirarTokensAntiguos();
    sessionStorage.clear();
}

function redirigirAlLogin() {
    limpiarSesion();
    if (window.location.pathname !== "/") window.location.replace("/");
}

let solicitudRenovacion = null;
let revisionSesion = 0;

async function renovarSesion() {
    if (!solicitudRenovacion) {
        solicitudRenovacion = (async () => {
            try {
                const response = await fetch("/api/v1/auth/refresh", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: cabecerasNavegador({ "Content-Type": "application/json" }),
                    body: "{}",
                });
                if ([400, 401, 403].includes(response.status)) return false;
                if (!response.ok) return null;
                const body = await response.json();
                if (!body.success || body.data?.authenticated !== true) return false;
                revisionSesion++;
                return true;
            } catch {
                return null;
            } finally {
                solicitudRenovacion = null;
            }
        })();
    }
    return solicitudRenovacion;
}

async function apiRequest(url, opciones = {}) {
    const revision = revisionSesion;
    const headers = cabecerasNavegador(opciones.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    const opcionesSeguras = { ...opciones, headers, credentials: "same-origin" };
    const response = await fetch(url, opcionesSeguras);
    if (response.status === 401) {
        const renovada = revisionSesion !== revision ? true : await renovarSesion();
        if (renovada === true) {
            const reintentada = await fetch(url, opcionesSeguras);
            if (reintentada.status === 401) {
                redirigirAlLogin();
                return null;
            }
            return reintentada;
        }
        if (renovada === false) {
            redirigirAlLogin();
            return null;
        }
    }
    return response;
}

async function apiGet(url, opciones = {}) {
    return apiRequest(url, {
        ...opciones,
        method: "GET",
    });
}


async function apiPost(
    url,
    body = null,
    opciones = {}
) {
    const headers = new Headers(
        opciones.headers || {}
    );

    if (
        body !== null &&
        !headers.has("Content-Type")
    ) {
        headers.set(
            "Content-Type",
            "application/json"
        );
    }

    return apiRequest(url, {
        ...opciones,
        method: "POST",
        headers,
        body:
            body !== null
                ? JSON.stringify(body)
                : undefined,
    });
}


async function cerrarSesion() {
    try {
        const response = await apiPost("/api/v1/auth/logout", {});
        if (response && !response.ok) throw new Error("Logout no confirmado");
        redirigirAlLogin();
    } catch {
        window.alert("No se pudo cerrar la sesión. Revisa tu conexión e inténtalo nuevamente antes de dejar el equipo.");
    }
}

// Mantiene apiGet/apiPost compatibles con consumidores que necesitan Response.
async function apiGetDatos(url, opciones = {}) {
    return solicitarJson(url, { ...opciones, method: "GET" }, apiRequest);
}

export {
    apiGet, apiGetDatos, apiPost, apiRequest, cabecerasNavegador, cerrarSesion,
    describirError, ErrorSolicitud, leerRespuesta, retirarTokensAntiguos, solicitarJson,
};
