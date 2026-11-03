// Las credenciales solo viajan en cookies HttpOnly; nunca se leen desde JavaScript.
function retirarTokensAntiguos() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
}

function limpiarSesion() {
    retirarTokensAntiguos();
    sessionStorage.clear();
}

// Retira las credenciales persistentes de versiones anteriores.
retirarTokensAntiguos();

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

window.addEventListener("pageshow", () => {
    apiGet("/api/v1/auth/me").catch(() => {});
});

// Mantiene apiGet/apiPost compatibles con consumidores que necesitan Response.
async function apiGetDatos(url, opciones = {}) {
    return solicitarJson(url, { ...opciones, method: "GET" }, apiRequest);
}
