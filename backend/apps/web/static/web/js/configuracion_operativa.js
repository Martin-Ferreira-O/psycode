const URL_CONFIGURACION_OPERATIVA = "/api/v1/configuracion-operativa";
const MODO_LISTA_DISTRIBUCION = "lista_distribucion";
const MODO_SUPERVISORES_ACTIVOS = "supervisores_activos";

const elementosConfiguracion = {
    estado: document.querySelector("#estadoConfiguracion"),
    accesoDenegado: document.querySelector("#accesoDenegado"),
    contenido: document.querySelector("#contenidoConfiguracion"),
    formulario: document.querySelector("#formularioConfiguracion"),
    dias: document.querySelectorAll('input[name="enabled_days"]'),
    apertura: document.querySelector("#horaApertura"),
    cierre: document.querySelector("#horaCierre"),
    modosNotificacion: document.querySelectorAll('input[name="notification_mode"]'),
    modoLista: document.querySelector("#modoListaDistribucion"),
    modoSupervisores: document.querySelector("#modoSupervisoresActivos"),
    tarjetaLista: document.querySelector("#tarjetaListaDistribucion"),
    tarjetaSupervisores: document.querySelector("#tarjetaSupervisoresActivos"),
    insigniaLista: document.querySelector("#insigniaListaDistribucion"),
    insigniaSupervisores: document.querySelector("#insigniaSupervisoresActivos"),
    contenedorCorreoPrincipal: document.querySelector("#contenedorCorreoPrincipal"),
    correoPrincipal: document.querySelector("#correoPrincipal"),
    respaldoHabilitado: document.querySelector("#respaldoHabilitado"),
    correoRespaldo: document.querySelector("#correoRespaldo"),
    zonaHoraria: document.querySelector("#zonaHoraria"),
    ultimaActualizacion: document.querySelector("#ultimaActualizacion"),
    mensajeFormulario: document.querySelector("#mensajeFormularioConfiguracion"),
    confirmacion: document.querySelector("#confirmacionConfiguracion"),
    guardar: document.querySelector("#guardarConfiguracion")
};

function actualizarRespaldo(habilitado) {
    elementosConfiguracion.respaldoHabilitado.checked = habilitado;
    elementosConfiguracion.correoRespaldo.disabled = !habilitado;
    elementosConfiguracion.correoRespaldo.required = habilitado;
    if (!habilitado) {
        elementosConfiguracion.correoRespaldo.setCustomValidity("");
    }
}

function obtenerModoSeleccionado() {
    const seleccionado = Array.from(elementosConfiguracion.modosNotificacion).find((input) => input.checked);
    return seleccionado ? seleccionado.value : MODO_LISTA_DISTRIBUCION;
}

function actualizarModoNotificacion(modo) {
    const modoActivo = modo === MODO_SUPERVISORES_ACTIVOS ? MODO_SUPERVISORES_ACTIVOS : MODO_LISTA_DISTRIBUCION;
    const esLista = modoActivo === MODO_LISTA_DISTRIBUCION;

    if (elementosConfiguracion.modoLista) {
        elementosConfiguracion.modoLista.checked = esLista;
    }
    if (elementosConfiguracion.modoSupervisores) {
        elementosConfiguracion.modoSupervisores.checked = !esLista;
    }

    if (elementosConfiguracion.tarjetaLista) {
        elementosConfiguracion.tarjetaLista.classList.toggle("opcion-destinatario--activa", esLista);
        elementosConfiguracion.tarjetaLista.setAttribute("data-activa", String(esLista));
    }
    if (elementosConfiguracion.tarjetaSupervisores) {
        elementosConfiguracion.tarjetaSupervisores.classList.toggle("opcion-destinatario--activa", !esLista);
        elementosConfiguracion.tarjetaSupervisores.setAttribute("data-activa", String(!esLista));
    }

    if (elementosConfiguracion.insigniaLista) {
        elementosConfiguracion.insigniaLista.hidden = !esLista;
    }
    if (elementosConfiguracion.insigniaSupervisores) {
        elementosConfiguracion.insigniaSupervisores.hidden = esLista;
    }

    if (elementosConfiguracion.contenedorCorreoPrincipal) {
        elementosConfiguracion.contenedorCorreoPrincipal.hidden = !esLista;
    }
    if (elementosConfiguracion.correoPrincipal) {
        elementosConfiguracion.correoPrincipal.disabled = !esLista;
        elementosConfiguracion.correoPrincipal.required = esLista;
        if (!esLista) {
            elementosConfiguracion.correoPrincipal.setCustomValidity("");
        }
    }
}

function mostrarAccesoDenegado() {
    elementosConfiguracion.estado.hidden = true;
    elementosConfiguracion.contenido.hidden = true;
    elementosConfiguracion.accesoDenegado.hidden = false;
}

function mostrarErrorCarga(error) {
    elementosConfiguracion.contenido.hidden = true;
    mostrarError(elementosConfiguracion.estado, error, {
        mensajes: {
            403: "No tienes permiso para consultar la configuración operativa."
        },
        reintentar: cargarConfiguracion
    });
}

function extraerMensajeErrorGuardado(error) {
    if (error instanceof ErrorSolicitud) {
        if (error.estado === 403) {
            return "No tienes permiso para modificar la configuración operativa.";
        }
        const campos = error.detalles?.fields;
        if (campos && typeof campos === "object") {
            const mensajesCampos = Object.values(campos)
                .flat()
                .filter((item) => typeof item === "string" && item.trim());
            if (mensajesCampos.length > 0) {
                return mensajesCampos.join(" ");
            }
        }
    }
    return describirError(error).mensaje;
}

function mostrarErrorGuardado(error) {
    elementosConfiguracion.mensajeFormulario.hidden = false;
    elementosConfiguracion.mensajeFormulario.textContent = extraerMensajeErrorGuardado(error);
}

function limpiarMensajeFormulario() {
    elementosConfiguracion.mensajeFormulario.textContent = "";
    elementosConfiguracion.mensajeFormulario.hidden = true;
}

function rellenarFormulario(configuracion) {
    const diasHabilitados = new Set((configuracion.enabled_days || []).map(String));
    elementosConfiguracion.dias.forEach((dia) => {
        dia.checked = diasHabilitados.has(dia.value);
    });
    elementosConfiguracion.apertura.value = configuracion.open_time || "";
    elementosConfiguracion.cierre.value = configuracion.close_time || "";
    elementosConfiguracion.correoPrincipal.value = configuracion.primary_email ?? "";
    elementosConfiguracion.correoRespaldo.value = configuracion.backup_email ?? "";
    actualizarRespaldo(Boolean(configuracion.backup_enabled));
    actualizarModoNotificacion(configuracion.notification_mode || MODO_LISTA_DISTRIBUCION);

    elementosConfiguracion.zonaHoraria.textContent = configuracion.timezone || "America/Santiago";
    elementosConfiguracion.ultimaActualizacion.textContent = configuracion.updated_at
        ? `Última actualización: ${new Intl.DateTimeFormat("es-CL", {
            dateStyle: "medium",
            timeStyle: "short",
            timeZone: configuracion.timezone || "America/Santiago"
        }).format(new Date(configuracion.updated_at))}`
        : "Configuración vigente";
}

async function cargarConfiguracion() {
    limpiarEstado(elementosConfiguracion.estado);
    elementosConfiguracion.estado.hidden = false;
    elementosConfiguracion.estado.textContent = "Verificando permisos y cargando configuración…";
    elementosConfiguracion.contenido.hidden = true;
    elementosConfiguracion.accesoDenegado.hidden = true;

    try {
        const usuario = await solicitarJson(
            "/api/v1/auth/me",
            { method: "GET" },
            apiRequest
        );
        if (usuario?.rol !== "admin") {
            mostrarAccesoDenegado();
            return;
        }

        const configuracion = await solicitarJson(
            URL_CONFIGURACION_OPERATIVA,
            { method: "GET" },
            apiRequest
        );
        rellenarFormulario(configuracion);
        elementosConfiguracion.estado.hidden = true;
        elementosConfiguracion.contenido.hidden = false;
    } catch (error) {
        if (error?.estado === 403) {
            mostrarAccesoDenegado();
            return;
        }
        if (error?.codigo === "SESION_FINALIZADA") return;
        mostrarErrorCarga(error);
    }
}

function validarFormulario() {
    const modoSeleccionado = obtenerModoSeleccionado();
    actualizarModoNotificacion(modoSeleccionado);
    const respaldoHabilitado = elementosConfiguracion.respaldoHabilitado.checked;
    actualizarRespaldo(respaldoHabilitado);

    if (modoSeleccionado === MODO_LISTA_DISTRIBUCION) {
        const valorCorreo = elementosConfiguracion.correoPrincipal.value.trim();
        if (!valorCorreo) {
            elementosConfiguracion.mensajeFormulario.textContent =
                "Debes ingresar un correo válido para la lista de distribución.";
            elementosConfiguracion.mensajeFormulario.hidden = false;
            elementosConfiguracion.correoPrincipal.focus();
            return false;
        }
    }

    if (respaldoHabilitado) {
        elementosConfiguracion.correoRespaldo.value = elementosConfiguracion.correoRespaldo.value.trim();
        if (!elementosConfiguracion.correoRespaldo.checkValidity()) {
            elementosConfiguracion.mensajeFormulario.textContent =
                "Debes ingresar un correo válido para activar el respaldo.";
            elementosConfiguracion.mensajeFormulario.hidden = false;
            elementosConfiguracion.correoRespaldo.reportValidity();
            elementosConfiguracion.correoRespaldo.focus();
            return false;
        }
    }

    if (!elementosConfiguracion.formulario.reportValidity()) return false;

    if (elementosConfiguracion.apertura.value >= elementosConfiguracion.cierre.value) {
        elementosConfiguracion.mensajeFormulario.textContent =
            "La hora de apertura debe ser anterior a la hora de cierre.";
        elementosConfiguracion.mensajeFormulario.hidden = false;
        elementosConfiguracion.cierre.focus();
        return false;
    }
    return true;
}

async function guardarConfiguracion(evento) {
    evento.preventDefault();
    limpiarMensajeFormulario();
    elementosConfiguracion.confirmacion.hidden = true;
    if (!validarFormulario()) return;

    const modoSeleccionado = obtenerModoSeleccionado();
    const payload = {
        enabled_days: Array.from(elementosConfiguracion.dias)
            .filter((dia) => dia.checked)
            .map((dia) => Number(dia.value)),
        open_time: elementosConfiguracion.apertura.value,
        close_time: elementosConfiguracion.cierre.value,
        notification_mode: modoSeleccionado,
        primary_email: elementosConfiguracion.correoPrincipal.value.trim(),
        backup_enabled: elementosConfiguracion.respaldoHabilitado.checked,
        backup_email: elementosConfiguracion.correoRespaldo.value.trim()
    };

    establecerCargaBoton(elementosConfiguracion.guardar, true, "Guardando…");
    try {
        const configuracion = await solicitarJson(
            URL_CONFIGURACION_OPERATIVA,
            {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            },
            apiRequest
        );
        rellenarFormulario(configuracion);
        limpiarMensajeFormulario();
        mostrarEstado(
            elementosConfiguracion.confirmacion,
            "exito",
            "La configuración operativa se guardó correctamente."
        );
    } catch (error) {
        if (error?.codigo === "SESION_FINALIZADA") return;
        mostrarErrorGuardado(error);
    } finally {
        establecerCargaBoton(elementosConfiguracion.guardar, false);
    }
}

elementosConfiguracion.modosNotificacion.forEach((radio) => {
    radio.addEventListener("change", () => {
        limpiarMensajeFormulario();
        actualizarModoNotificacion(obtenerModoSeleccionado());
    });
});

elementosConfiguracion.formulario?.addEventListener("submit", guardarConfiguracion);
elementosConfiguracion.respaldoHabilitado.addEventListener("change", () => {
    limpiarMensajeFormulario();
    elementosConfiguracion.confirmacion.hidden = true;
    actualizarRespaldo(elementosConfiguracion.respaldoHabilitado.checked);
});
elementosConfiguracion.correoRespaldo.addEventListener("input", () => {
    limpiarMensajeFormulario();
    elementosConfiguracion.confirmacion.hidden = true;
});
cargarConfiguracion();
