const URL_CONFIGURACION_OPERATIVA = "/api/v1/configuracion-operativa";

const elementosConfiguracion = {
    estado: document.querySelector("#estadoConfiguracion"),
    accesoDenegado: document.querySelector("#accesoDenegado"),
    contenido: document.querySelector("#contenidoConfiguracion"),
    formulario: document.querySelector("#formularioConfiguracion"),
    dias: document.querySelectorAll('input[name="enabled_days"]'),
    apertura: document.querySelector("#horaApertura"),
    cierre: document.querySelector("#horaCierre"),
    correoPrincipal: document.querySelector("#correoPrincipal"),
    correoRespaldo: document.querySelector("#correoRespaldo"),
    zonaHoraria: document.querySelector("#zonaHoraria"),
    ultimaActualizacion: document.querySelector("#ultimaActualizacion"),
    mensajeFormulario: document.querySelector("#mensajeFormularioConfiguracion"),
    confirmacion: document.querySelector("#confirmacionConfiguracion"),
    guardar: document.querySelector("#guardarConfiguracion")
};

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

function mostrarErrorGuardado(error) {
    elementosConfiguracion.mensajeFormulario.hidden = false;
    elementosConfiguracion.mensajeFormulario.textContent =
        error instanceof ErrorSolicitud && error.estado === 403
            ? "No tienes permiso para modificar la configuración operativa."
            : describirError(error).mensaje;
}

function limpiarMensajeFormulario() {
    elementosConfiguracion.mensajeFormulario.textContent = "";
    elementosConfiguracion.mensajeFormulario.hidden = true;
}

function rellenarFormulario(configuracion) {
    const diasHabilitados = new Set(configuracion.enabled_days.map(String));
    elementosConfiguracion.dias.forEach((dia) => {
        dia.checked = diasHabilitados.has(dia.value);
    });
    elementosConfiguracion.apertura.value = configuracion.open_time;
    elementosConfiguracion.cierre.value = configuracion.close_time;
    elementosConfiguracion.correoPrincipal.value = configuracion.primary_email;
    elementosConfiguracion.correoRespaldo.value = configuracion.backup_email;
    elementosConfiguracion.zonaHoraria.textContent = configuracion.timezone;
    elementosConfiguracion.ultimaActualizacion.textContent = configuracion.updated_at
        ? `Última actualización: ${new Intl.DateTimeFormat("es-CL", {
            dateStyle: "medium",
            timeStyle: "short",
            timeZone: configuracion.timezone
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

    const payload = {
        enabled_days: Array.from(elementosConfiguracion.dias)
            .filter((dia) => dia.checked)
            .map((dia) => Number(dia.value)),
        open_time: elementosConfiguracion.apertura.value,
        close_time: elementosConfiguracion.cierre.value,
        primary_email: elementosConfiguracion.correoPrincipal.value.trim(),
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

elementosConfiguracion.formulario?.addEventListener("submit", guardarConfiguracion);
cargarConfiguracion();
