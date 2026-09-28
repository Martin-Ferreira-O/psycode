// Presentación compartida. Los mensajes específicos deben ser textos locales.
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

function mostrarEstado(contenedor, tipo, mensaje) {
    contenedor.hidden = false;
    contenedor.style.removeProperty("display");
    contenedor.classList.add("estado-solicitud");
    contenedor.dataset.estado = tipo;
    contenedor.setAttribute("role", tipo === "error" ? "alert" : "status");
    contenedor.setAttribute("aria-live", tipo === "error" ? "assertive" : "polite");
    contenedor.setAttribute("aria-atomic", "true");
    contenedor.textContent = mensaje;
}

function limpiarEstado(contenedor) {
    contenedor.replaceChildren();
    contenedor.hidden = true;
    delete contenedor.dataset.estado;
}

function mostrarCarga(contenedor, mensaje = "Cargando información…") {
    mostrarEstado(contenedor, "carga", mensaje);
}

function mostrarVacio(contenedor, mensaje = "No hay información disponible.") {
    mostrarEstado(contenedor, "vacio", mensaje);
}

function mostrarError(contenedor, error, { mensajes = {}, reintentar } = {}) {
    const descripcion = describirError(error, mensajes);
    if (descripcion.omitido) {
        limpiarEstado(contenedor);
        return;
    }
    mostrarEstado(contenedor, "error", descripcion.mensaje);
    // La pantalla decide si repetir la operación es seguro. Nunca hay reintento automático.
    if (descripcion.recuperable && reintentar) {
        const boton = document.createElement("button");
        boton.type = "button";
        boton.className = "boton-reintentar";
        boton.textContent = "Reintentar";
        boton.addEventListener("click", async () => {
            if (boton.disabled) return;
            boton.disabled = true;
            try {
                await reintentar();
            } catch (nuevoError) {
                mostrarError(contenedor, nuevoError, { mensajes, reintentar });
            } finally {
                boton.disabled = false;
            }
        });
        contenedor.appendChild(boton);
    }
}

const estadosBoton = new WeakMap();
function establecerCargaBoton(boton, cargando, mensaje = "Cargando…") {
    if (cargando && !estadosBoton.has(boton)) {
        estadosBoton.set(boton, { nodos: [...boton.childNodes], disabled: boton.disabled });
        boton.textContent = mensaje;
        boton.disabled = true;
        boton.setAttribute("aria-busy", "true");
    } else if (!cargando && estadosBoton.has(boton)) {
        const anterior = estadosBoton.get(boton);
        boton.replaceChildren(...anterior.nodos);
        boton.disabled = anterior.disabled;
        boton.removeAttribute("aria-busy");
        estadosBoton.delete(boton);
    }
}
