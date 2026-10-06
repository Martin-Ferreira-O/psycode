//Este archivo contiene funciones compartidas para autenticación y solicitudes a la API.

function obtenerAccessToken() {
    return localStorage.getItem("access_token");
}


function obtenerRefreshToken() {
    return localStorage.getItem("refresh_token");
}


function limpiarSesion() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    sessionStorage.clear();
}


function redirigirAlLogin() {
    limpiarSesion();

    if (window.location.pathname !== "/") {
        window.location.replace("/");
    }
}


function verificarSesion() {
    const token = obtenerAccessToken();

    if (!token) {
        redirigirAlLogin();
        return false;
    }

    return true;
}

let solicitudRenovacion = null;

async function renovarSesion() {
    const refreshToken = obtenerRefreshToken();
    if (!refreshToken) {
        return false;
    }

    if (!solicitudRenovacion) {
        solicitudRenovacion = (async () => {
            try {
                const response = await fetch("/api/v1/auth/refresh", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json",
                    },
                    body: JSON.stringify({ refresh_token: refreshToken }),
                });
                if ([400, 401, 403].includes(response.status)) {
                    return false;
                }
                if (!response.ok) {
                    return null;
                }

                const body = await response.json();
                const tokens = body.data;
                if (!body.success || !tokens?.access_token || !tokens?.refresh_token) {
                    return false;
                }

                localStorage.setItem("access_token", tokens.access_token);
                localStorage.setItem("refresh_token", tokens.refresh_token);
                return true;
            } catch (error) {
                return null;
            } finally {
                solicitudRenovacion = null;
            }
        })();
    }

    return solicitudRenovacion;
}


async function apiRequest(url, opciones = {}) {
    const token = obtenerAccessToken();

    if (!token) {
        redirigirAlLogin();
        return null;
    }

    const headers = new Headers(
        opciones.headers || {}
    );

    headers.set(
        "Authorization",
        `Bearer ${token}`
    );

    if (!headers.has("Accept")) {
        headers.set(
            "Accept",
            "application/json"
        );
    }

    const response = await fetch(url, { ...opciones, headers });

    if (response.status === 401) {
        const renovada = obtenerAccessToken() !== token
            ? true
            : await renovarSesion();
        if (renovada === true) {
            headers.set("Authorization", `Bearer ${obtenerAccessToken()}`);
            const reintentada = await fetch(url, { ...opciones, headers });
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
    const refreshToken =
        obtenerRefreshToken();

    try {
        if (
            refreshToken &&
            obtenerAccessToken()
        ) {
            await apiPost(
                "/api/v1/auth/logout",
                {
                    refresh_token:
                        refreshToken,
                }
            );
        }
    } catch (error) {
        console.error(
            "Error al cerrar sesión:",
            error
        );
    } finally {
        redirigirAlLogin();
    }
}

window.addEventListener(
    "pageshow",
    () => {
        verificarSesion();
    }
);
// Mantiene apiGet/apiPost compatibles con consumidores que necesitan Response.
async function apiGetDatos(url, opciones = {}) {
    return solicitarJson(url, { ...opciones, method: "GET" }, apiRequest);
}
