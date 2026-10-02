if (!verificarSesion()) {
    throw new Error("Sesión no válida");
}

const etiquetas = {
    riesgo_suicida: "Riesgo suicida",
    vulneracion_derechos: "Vulneración de derechos",
    pendiente: "Pendiente",
    correcta: "Correcta",
    falso_positivo: "Falso positivo",
    neutro: "Neutro",
};

const elementos = {
    total: document.querySelector("#totalAlertas"),
    pendientes: document.querySelector("#totalPendientes"),
    revisadas: document.querySelector("#totalRevisadas"),
    buscar: document.querySelector("#buscar"),
    box: document.querySelector("#filtroBox"),
    estado: document.querySelector("#filtroEstado"),
    desde: document.querySelector("#fechaDesde"),
    hasta: document.querySelector("#fechaHasta"),
    limpiar: document.querySelector("#limpiarFiltros"),
    actualizar: document.querySelector("#botonActualizar"),
    tabla: document.querySelector("#tablaAlertas"),
    tablaContenedor: document.querySelector("#tablaContenedor"),
    estadoVacio: document.querySelector("#estadoVacio"),
    resultadoTexto: document.querySelector("#resultadoTexto"),
    paginacion: document.querySelector("#paginacion"),
    textoPaginacion: document.querySelector("#textoPaginacion"),
    numerosPagina: document.querySelector("#numerosPagina"),
    anterior: document.querySelector("#paginaAnterior"),
    siguiente: document.querySelector("#paginaSiguiente"),
    modal: document.querySelector("#modalDetalle"),
    estadoDetalle: document.querySelector("#estadoDetalle"),
    guardar: document.querySelector("#guardarEvaluacion"),
};

let paginaActual = 1;
const registrosPorPagina = 10;
let alertas = [];
let totalAlertas = 0;
let totalCoincidencias = 0;
let offsetActual = 0;
let solicitudLista = 0;
let solicitudDetalle = 0;
let solicitudResumen = null;
let resumenCargado = false;
let temporizadorBusqueda;
let alertaSeleccionada = null;

async function cargarResumenAlertas(forzar = false) {
    if (solicitudResumen) return solicitudResumen;
    if (resumenCargado && !forzar) return;
    if (!resumenCargado) {
        elementos.total.textContent = "—";
        elementos.pendientes.textContent = "—";
        elementos.revisadas.textContent = "—";
    }

    solicitudResumen = (async () => {
        try {
            const [pendientes, revisadas] = await Promise.all([
                apiGetDatos("/api/v1/alerts?revisadas=false&limit=1&offset=0"),
                apiGetDatos("/api/v1/alerts?revisadas=true&limit=1&offset=0"),
            ]);
            if (!Number.isInteger(pendientes.total) || !Number.isInteger(revisadas.total)) {
                throw new ErrorSolicitud();
            }

            elementos.pendientes.textContent = String(pendientes.total);
            elementos.revisadas.textContent = String(revisadas.total);
            elementos.total.textContent = String(pendientes.total + revisadas.total);
            resumenCargado = true;
        } catch (error) {
            if (!resumenCargado) {
                elementos.total.textContent = "—";
                elementos.pendientes.textContent = "—";
                elementos.revisadas.textContent = "—";
            }
        }
    })();

    try {
        await solicitudResumen;
    } finally {
        solicitudResumen = null;
    }
}

function construirUrlAlertas(offsetSolicitado) {
    const parametros = new URLSearchParams({
        limit: String(registrosPorPagina),
        offset: String(offsetSolicitado),
    });
    const busqueda = elementos.buscar.value.trim();
    const codigoUuid = Object.entries(codigosAlerta)
        .find(([, codigo]) => codigo.toLowerCase() === busqueda.toLowerCase())?.[0];
    const estado = elementos.estado.value;

    if (busqueda) parametros.set("q", codigoUuid || busqueda);
    if (elementos.box.value) parametros.set("box", elementos.box.value);
    if (estado === "__revisadas__") {
        parametros.set("revisadas", "true");
    } else if (estado) {
        parametros.set("estado_evaluacion", estado);
    }
    if (elementos.desde.value) parametros.set("fecha_desde", elementos.desde.value);
    if (elementos.hasta.value) parametros.set("fecha_hasta", elementos.hasta.value);

    return `/api/v1/alerts?${parametros.toString()}`;
}

async function cargarAlertas(offsetSolicitado = 0) {
    const idSolicitud = ++solicitudLista;
    elementos.resultadoTexto.textContent = "Consultando alertas…";
    mostrarCarga(elementos.estadoVacio, "Cargando alertas…");
    elementos.tablaContenedor.hidden = true;
    elementos.paginacion.hidden = true;

    try {
        const data = await apiGetDatos(construirUrlAlertas(offsetSolicitado));
        if (!Array.isArray(data?.items) || !Number.isInteger(data.total)) {
            throw new ErrorSolicitud();
        }
        if (idSolicitud !== solicitudLista) return;

        alertas = data.items;
        totalCoincidencias = data.total;
        offsetActual = data.offset;
        paginaActual = Math.floor(offsetActual / registrosPorPagina) + 1;
        renderizarTabla();
    } catch (error) {
        if (idSolicitud !== solicitudLista) return;
        elementos.resultadoTexto.textContent = "No se pudieron consultar las alertas.";
        elementos.tablaContenedor.hidden = true;
        elementos.paginacion.hidden = true;
        mostrarError(elementos.estadoVacio, error, {
            mensajes: { 404: "No encontramos las alertas solicitadas." },
            reintentar: () => cargarAlertas(offsetSolicitado),
        });
    }
}

function crearCelda(texto, clase = "", descripcion = "") {
    const celda = document.createElement("td");
    if (!clase) {
        celda.textContent = texto || "—";
        return celda;
    }

    const etiqueta = document.createElement("span");
    etiqueta.className = clase;
    etiqueta.textContent = texto || "—";
    if (descripcion) {
        etiqueta.title = descripcion;
        etiqueta.setAttribute("aria-label", descripcion);
    }
    celda.append(etiqueta);
    return celda;
}

function renderizarTabla() {
    const totalPaginas = Math.ceil(totalCoincidencias / registrosPorPagina);
    const primero = totalCoincidencias === 0 ? 0 : offsetActual + 1;
    const final = Math.min(offsetActual + alertas.length, totalCoincidencias);

    elementos.resultadoTexto.textContent =
        `${totalCoincidencias} alerta${totalCoincidencias === 1 ? "" : "s"} encontrada${totalCoincidencias === 1 ? "" : "s"}`;

    if (totalCoincidencias === 0) {
        const hayFiltros = [elementos.buscar, elementos.box, elementos.estado,
            elementos.desde, elementos.hasta].some((control) => control.value.trim());
        mostrarVacio(elementos.estadoVacio, hayFiltros
            ? "No hay alertas que coincidan con los filtros. Prueba con otros criterios."
            : "Todavía no hay alertas registradas.");
    } else {
        limpiarEstado(elementos.estadoVacio);
    }
    elementos.tablaContenedor.hidden = totalCoincidencias === 0;
    elementos.paginacion.hidden = totalCoincidencias === 0;

    const filas = document.createDocumentFragment();
    alertas.forEach((alerta) => {
        const nivel = String(alerta.semaforo || "").toLowerCase();
        const estado = alerta.estado_evaluacion === "pendiente"
            ? "estado-pendiente"
            : "estado-revisada";
        const fila = document.createElement("tr");
        fila.append(
            crearCelda(codigoAlertaVisible(alerta.alerta_id), "identificador-alerta"),
            crearCelda(formatearBox(alerta.box)),
            crearCelda(formatearTipoRiesgo(alerta.tipo_riesgo), "etiqueta-tipo"),
            crearCelda(nivelVisual(alerta), `etiqueta-nivel nivel-${nivel}`, `Nivel ${alerta.nivel_severidad}; semáforo ${alerta.semaforo}`),
            crearCelda(formatearFecha(alerta.fecha_hora)),
            crearCelda(formatearHora(alerta.fecha_hora)),
            crearCelda(alerta.estado_evaluacion === "pendiente" ? "Pendiente" : "Revisada", `etiqueta-estado ${estado}`, `Estado de evaluación: ${etiquetas[alerta.estado_evaluacion]}`),
        );

        const accion = document.createElement("td");
        const boton = document.createElement("button");
        boton.type = "button";
        boton.className = "boton-revisar";
        boton.dataset.alerta = alerta.alerta_id;
        boton.textContent = alerta.estado_evaluacion === "pendiente" ? "Revisar" : "Ver detalle";
        accion.append(boton);
        fila.append(accion);
        filas.append(fila);
    });
    elementos.tabla.replaceChildren(filas);

    elementos.textoPaginacion.textContent = `Mostrando ${primero}–${final} de ${totalCoincidencias}`;
    elementos.numerosPagina.replaceChildren();
    const paginaInicial = Math.max(1, Math.min(paginaActual - 2, totalPaginas - 4));
    const paginaFinal = Math.min(totalPaginas, paginaInicial + 4);
    for (let numero = paginaInicial; numero <= paginaFinal; numero += 1) {
        const boton = document.createElement("button");
        boton.type = "button";
        boton.className = numero === paginaActual ? "activo" : "";
        boton.dataset.pagina = String(numero);
        boton.textContent = String(numero);
        if (numero === paginaActual) boton.setAttribute("aria-current", "page");
        elementos.numerosPagina.append(boton);
    }
    elementos.anterior.disabled = paginaActual <= 1;
    elementos.siguiente.disabled = paginaActual >= totalPaginas;
}

function completarDetalle(alerta) {
    document.querySelector("#tituloModal").textContent = codigoAlertaVisible(alerta.alerta_id);
    document.querySelector("#detalleBox").textContent = formatearBox(alerta.box);
    document.querySelector("#detalleTipo").textContent = formatearTipoRiesgo(alerta.tipo_riesgo);
    document.querySelector("#detalleNivel").textContent = etiquetaNivel(alerta);
    document.querySelector("#detalleFecha").textContent = `${formatearFecha(alerta.fecha_hora)} · ${formatearHora(alerta.fecha_hora)}`;
    document.querySelector("#detalleEstado").textContent = etiquetas[alerta.estado_evaluacion] || alerta.estado_evaluacion;
    document.querySelector("#detalleSesion").textContent = alerta.sesion_id || "—";

    const pendiente = alerta.estado_evaluacion === "pendiente";
    document.querySelector("#formularioEvaluacion").hidden = !pendiente;
    document.querySelector("#evaluacionRegistrada").hidden = pendiente;
    document.querySelectorAll('input[name="evaluacion"]').forEach((opcion) => {
        opcion.checked = false;
    });
    limpiarEstado(document.querySelector("#mensajeEvaluacion"));

    if (alerta.evaluacion) {
        const resultado = alerta.evaluacion.evaluacion;
        document.querySelector("#resultadoEvaluacion").textContent = etiquetas[resultado] || resultado;
        document.querySelector("#evaluadoPor").textContent = alerta.evaluacion.usuario;
        document.querySelector("#fechaEvaluacion").textContent = `${formatearFecha(alerta.evaluacion.fecha_hora)} · ${formatearHora(alerta.evaluacion.fecha_hora)}`;
    }
}

async function abrirDetalle(alertaId) {
    const idSolicitud = ++solicitudDetalle;
    elementos.modal.hidden = false;
    document.body.classList.add("modal-abierto");
    document.querySelector("#formularioEvaluacion").hidden = true;
    document.querySelector("#evaluacionRegistrada").hidden = true;
    mostrarCarga(elementos.estadoDetalle, "Cargando detalle…");
    elementos.modal.querySelector(".boton-cerrar").focus();

    try {
        const alerta = await apiGetDatos(`/api/v1/alerts/${encodeURIComponent(alertaId)}`);
        if (idSolicitud !== solicitudDetalle) return;
        alertaSeleccionada = alerta;
        completarDetalle(alerta);
        limpiarEstado(elementos.estadoDetalle);
    } catch (error) {
        if (idSolicitud !== solicitudDetalle) return;
        mostrarError(elementos.estadoDetalle, error, {
            reintentar: () => abrirDetalle(alertaId),
        });
    }
}

function cerrarDetalle() {
    solicitudDetalle += 1;
    elementos.modal.hidden = true;
    document.body.classList.remove("modal-abierto");
    alertaSeleccionada = null;
}

async function guardarEvaluacion() {
    if (!alertaSeleccionada || alertaSeleccionada.estado_evaluacion !== "pendiente") return;

    const opcion = document.querySelector('input[name="evaluacion"]:checked');
    const mensaje = document.querySelector("#mensajeEvaluacion");
    if (!opcion) {
        mostrarEstado(mensaje, "error", "Selecciona una opción antes de guardar.");
        return;
    }

    const alertaId = alertaSeleccionada.alerta_id;
    establecerCargaBoton(elementos.guardar, true, "Guardando…");
    try {
        const response = await apiPost(
            `/api/v1/alerts/${encodeURIComponent(alertaId)}/evaluacion`,
            { evaluacion: opcion.value },
        );
        const evaluacion = await leerRespuesta(response);
        await Promise.all([
            cargarAlertas(offsetActual),
            cargarResumenAlertas(true),
            abrirDetalle(alertaId),
        ]);
        mostrarEstado(elementos.estadoDetalle, "exito", "Evaluación registrada.");
    } catch (error) {
        if (error instanceof ErrorSolicitud && error.estado === 409) {
            await abrirDetalle(alertaId);
            mostrarEstado(elementos.estadoDetalle, "error", "La alerta ya tiene una evaluación. Se actualizó el detalle.");
        } else {
            mostrarError(mensaje, error);
        }
    } finally {
        establecerCargaBoton(elementos.guardar, false);
    }
}

function aplicarFiltroInicial() {
    const parametros = new URLSearchParams(window.location.search);
    const revisadas = parametros.get("revisadas");
    const estado = parametros.get("estado_evaluacion");
    if (revisadas === "true") {
        elementos.estado.value = "__revisadas__";
    } else if (revisadas === "false") {
        elementos.estado.value = "pendiente";
    } else if (estado && [...elementos.estado.options].some((opcion) => opcion.value === estado)) {
        elementos.estado.value = estado;
    }
}

elementos.buscar.addEventListener("input", () => {
    clearTimeout(temporizadorBusqueda);
    temporizadorBusqueda = setTimeout(() => cargarAlertas(0), 300);
});

[elementos.box, elementos.estado, elementos.desde, elementos.hasta].forEach((control) => {
    control.addEventListener("change", () => cargarAlertas(0));
});

elementos.limpiar.addEventListener("click", () => {
    elementos.buscar.value = "";
    elementos.box.value = "";
    elementos.estado.value = "";
    elementos.desde.value = "";
    elementos.hasta.value = "";
    clearTimeout(temporizadorBusqueda);
    cargarAlertas(0);
});

elementos.actualizar.addEventListener("click", () => {
    cargarAlertas(offsetActual);
    cargarResumenAlertas(true);
});

elementos.anterior.addEventListener("click", () => cargarAlertas(Math.max(0, offsetActual - registrosPorPagina)));

elementos.siguiente.addEventListener("click", () => {
    if (offsetActual + registrosPorPagina < totalCoincidencias) {
        cargarAlertas(offsetActual + registrosPorPagina);
    }
});

elementos.numerosPagina.addEventListener("click", (evento) => {
    const boton = evento.target.closest("[data-pagina]");
    if (boton) {
        cargarAlertas((Number(boton.dataset.pagina) - 1) * registrosPorPagina);
    }
});

elementos.tabla.addEventListener("click", (evento) => {
    const boton = evento.target.closest("[data-alerta]");
    if (boton) {
        abrirDetalle(boton.dataset.alerta);
    }
});

elementos.guardar.addEventListener(
    "click",
    guardarEvaluacion
);

document
    .querySelectorAll("[data-cerrar-modal]")
    .forEach((elemento) => {
        elemento.addEventListener(
            "click",
            cerrarDetalle
        );
    });

document.addEventListener("keydown", (evento) => {
    if (
        evento.key === "Escape" &&
        !elementos.modal.hidden
    ) {
        cerrarDetalle();
    }
});

aplicarFiltroInicial();
cargarResumenAlertas();
cargarAlertas(0);
