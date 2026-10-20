const URL_BITACORA = "/api/v1/audit-events";
const LIMITE_PAGINA = 20;
const LIMITE_DESCARGA = 100;

const ACCIONES_TECNICAS = [
    "analysis.speechmatics",
    "analysis.jev",
    "alerts.flow"
];

const elementosBitacora = {
    periodoActual: document.querySelector("#periodoActual"),
    semanaAnterior: document.querySelector("#semanaAnterior"),
    semanaSiguiente: document.querySelector("#semanaSiguiente"),
    fechaReferencia: document.querySelector("#fechaReferencia"),

    totalEventos: document.querySelector("#totalEventos"),
    totalAlertas: document.querySelector("#totalAlertas"),
    totalDespachos: document.querySelector("#totalDespachos"),
    totalEvaluaciones: document.querySelector("#totalEvaluaciones"),
    totalTecnicos: document.querySelector("#totalTecnicos"),

    tarjetasResumen: document.querySelectorAll("[data-resumen]"),

    recargar: document.querySelector("#recargarBitacora"),
    formulario: document.querySelector("#formFiltros"),
    filtroAlerta: document.querySelector("#filtroAlerta"),
    filtroAccion: document.querySelector("#filtroAccion"),
    filtroResultado: document.querySelector("#filtroResultado"),
    filtroOrden: document.querySelector("#filtroOrden"),
    limpiarFiltros: document.querySelector("#limpiarFiltros"),

    estadoCarga: document.querySelector("#estadoCarga"),
    estadoError: document.querySelector("#estadoError"),
    mensajeError: document.querySelector("#mensajeError"),
    reintentar: document.querySelector("#reintentarBitacora"),
    estadoVacio: document.querySelector("#estadoVacio"),

    contenedorTabla: document.querySelector("#contenedorTabla"),
    tabla: document.querySelector("#tablaEventos"),

    paginacion: document.querySelector("#paginacionBitacora"),
    textoPaginacion: document.querySelector("#textoPaginacion"),
    paginaAnterior: document.querySelector("#paginaAnterior"),
    paginaSiguiente: document.querySelector("#paginaSiguiente"),

    detalleFondo: document.querySelector("#detalleFondo"),
    panelDetalle: document.querySelector("#panelDetalle"),
    cerrarDetalle: document.querySelector("#cerrarDetalle"),

    detalleFecha: document.querySelector("#detalleFecha"),
    detalleAccion: document.querySelector("#detalleAccion"),
    detalleResultado: document.querySelector("#detalleResultado"),
    detalleActor: document.querySelector("#detalleActor"),
    detalleAlerta: document.querySelector("#detalleAlerta"),
    detalleSesion: document.querySelector("#detalleSesion"),
    detalleSecuencia: document.querySelector("#detalleSecuencia"),
    detalleCanal: document.querySelector("#detalleCanal"),
    detalleError: document.querySelector("#detalleError"),
    detalleDuracion: document.querySelector("#detalleDuracion"),

    verEventosAlerta: document.querySelector("#verEventosAlerta")
};

let fechaReferencia = new Date();
let offsetActual = 0;
let totalActual = 0;
let resumenActivo = "todos";
let eventoSeleccionado = null;
let focoAnterior = null;
let numeroCarga = 0;

function mostrar(elemento) {
    if (elemento) elemento.hidden = false;
}

function ocultar(elemento) {
    if (elemento) elemento.hidden = true;
}

function limpiarElemento(elemento) {
    if (!elemento) return;

    while (elemento.firstChild) {
        elemento.removeChild(elemento.firstChild);
    }
}

function rellenarNumero(numero) {
    return String(numero).padStart(2, "0");
}

function formatearFechaInput(fecha) {
    return [
        fecha.getFullYear(),
        rellenarNumero(fecha.getMonth() + 1),
        rellenarNumero(fecha.getDate())
    ].join("-");
}

function fechaDesdeInput(valor) {
    if (!valor) return null;

    const partes = valor.split("-").map(Number);

    if (partes.length !== 3 || partes.some(Number.isNaN)) {
        return null;
    }

    return new Date(
        partes[0],
        partes[1] - 1,
        partes[2],
        12,
        0,
        0,
        0
    );
}

function obtenerSemana(fecha) {
    const referencia = new Date(fecha);
    referencia.setHours(12, 0, 0, 0);

    const diaSemana = referencia.getDay();
    const diferenciaLunes = (diaSemana + 6) % 7;

    const inicio = new Date(referencia);
    inicio.setDate(referencia.getDate() - diferenciaLunes);
    inicio.setHours(0, 0, 0, 0);

    const fin = new Date(inicio);
    fin.setDate(inicio.getDate() + 7);
    fin.setMilliseconds(-1);

    return { inicio, fin };
}

function textoFechaPeriodo(fecha) {
    return new Intl.DateTimeFormat("es-CL", {
        day: "numeric",
        month: "short",
        year: "numeric"
    }).format(fecha);
}

function actualizarPeriodoVisible() {
    const { inicio, fin } = obtenerSemana(fechaReferencia);

    elementosBitacora.periodoActual.textContent =
        `Semana del ${textoFechaPeriodo(inicio)} al ${textoFechaPeriodo(fin)}`;

    elementosBitacora.fechaReferencia.value =
        formatearFechaInput(fechaReferencia);
}

function formatearFechaEvento(valor) {
    if (!valor) return "—";

    const fecha = new Date(valor);

    if (Number.isNaN(fecha.getTime())) {
        return "—";
    }

    return new Intl.DateTimeFormat("es-CL", {
        timeZone: "America/Santiago",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    }).format(fecha);
}

function textoAccion(accion) {
    const etiquetas = {
        "alerts.register": "Registro de alerta",
        "alerts.evaluate": "Evaluación",
        "notifications.send": "Notificación",
        "analysis.speechmatics": "Speechmatics",
        "analysis.jev": "JEV",
        "alerts.flow": "Flujo de alerta"
    };

    return etiquetas[accion] || accion || "—";
}

function textoResultado(resultado) {
    const etiquetas = {
        success: "Exitoso",
        failure: "Fallido",
        skipped: "Omitido"
    };

    return etiquetas[resultado] || resultado || "—";
}

function claseResultado(resultado) {
    const clases = {
        success: "exitoso",
        failure: "fallido",
        skipped: "omitido"
    };

    return clases[resultado] || "";
}

function textoCanal(canal) {
    if (canal === "email") return "Correo";
    if (canal === "teams") return "Teams";
    return "—";
}

function textoActor(evento) {if (!evento?.actor_id) return "Sistema";return "Usuario";}

function mensajeSegunEstado(estado) {
    if (estado === 400) {return "Revisa los filtros ingresados e intenta nuevamente.";}

    if (estado === 401) {return "Tu sesión expiró. Inicia sesión nuevamente.";}

    if (estado === 403) {return "La bitácora está disponible únicamente para administradores.";}

    if (estado === 503) {return "La bitácora no está disponible temporalmente. Intenta nuevamente.";}

    if (estado >= 500) {return "El servidor no pudo completar la solicitud. Intenta nuevamente.";}

    return "No fue posible recuperar los eventos de la bitácora.";
}

async function leerRespuestaBitacora(response) {
    if (!response) return null;
    let cuerpo = null;
    try {
        cuerpo = await response.json();
    } catch {
        cuerpo = null;
    }

    if (!response.ok) {
        const error = new Error(
            cuerpo?.error?.message ||
            "No se pudo completar la solicitud."
        );
        error.estado = response.status;
        error.codigo = cuerpo?.error?.code || null;
        error.detalles = cuerpo?.error?.details || null;

        throw error;
    }

    if (cuerpo?.success !== true) {
        const error = new Error("Respuesta inválida del servidor.");
        error.estado = response.status;
        throw error;
    }

    return cuerpo.data;
}

function parametrosPeriodo() {
    const { inicio, fin } = obtenerSemana(fechaReferencia);
    const parametros = new URLSearchParams();
    parametros.set("fecha_desde", inicio.toISOString());
    parametros.set("fecha_hasta", fin.toISOString());
    return parametros;
}

function agregarFiltrosTabla(parametros) {
    const alerta = elementosBitacora.filtroAlerta.value.trim();
    const accion = elementosBitacora.filtroAccion.value;
    const resultado = elementosBitacora.filtroResultado.value;
    const orden = elementosBitacora.filtroOrden.value || "desc";

    if (alerta) parametros.set("alerta_id", alerta);
    if (accion) parametros.set("action", accion);
    if (resultado) parametros.set("outcome", resultado);

    parametros.set("order", orden);

    return parametros;
}

async function consultarBitacora(parametros) {
    const response = await apiRequest(
        `${URL_BITACORA}?${parametros.toString()}`,
        { method: "GET" }
    );

    return leerRespuestaBitacora(response);
}

async function consultarTotal(accion = null) {
    const parametros = parametrosPeriodo();

    if (accion) {
        parametros.set("action", accion);
    }

    parametros.set("limit", "1");
    parametros.set("offset", "0");

    const datos = await consultarBitacora(parametros);
    if (!datos) return null;
    return Number(datos.total) || 0;
}

async function obtenerResumenPeriodo() {
    const resultados = await Promise.all([
        consultarTotal(),
        consultarTotal("alerts.register"),
        consultarTotal("notifications.send"),
        consultarTotal("alerts.evaluate"),
        consultarTotal("analysis.speechmatics"),
        consultarTotal("analysis.jev"),
        consultarTotal("alerts.flow")
    ]);

    if (resultados.some((resultado) => resultado === null)) {
        return null;
    }

    return {
        todos: resultados[0],
        alertas: resultados[1],
        despachos: resultados[2],
        evaluaciones: resultados[3],
        tecnicos: resultados[4] + resultados[5] + resultados[6]
    };
}

function renderizarResumen(resumen) {
    if (!resumen) return;

    elementosBitacora.totalEventos.textContent = resumen.todos;
    elementosBitacora.totalAlertas.textContent = resumen.alertas;
    elementosBitacora.totalDespachos.textContent = resumen.despachos;
    elementosBitacora.totalEvaluaciones.textContent = resumen.evaluaciones;
    elementosBitacora.totalTecnicos.textContent = resumen.tecnicos;
}

async function obtenerPaginaNormal() {
    const parametros = parametrosPeriodo();
    agregarFiltrosTabla(parametros);
    parametros.set("limit", String(LIMITE_PAGINA));
    parametros.set("offset", String(offsetActual));

    return consultarBitacora(parametros);
}

async function descargarEventosAccion(accion) {
    const eventos = [];
    let offset = 0;
    let total = 0;

    do {
        const parametros = parametrosPeriodo();

        const alerta = elementosBitacora.filtroAlerta.value.trim();
        const resultado = elementosBitacora.filtroResultado.value;
        const orden = elementosBitacora.filtroOrden.value || "desc";

        if (alerta) parametros.set("alerta_id", alerta);
        if (resultado) parametros.set("outcome", resultado);

        parametros.set("action", accion);
        parametros.set("order", orden);
        parametros.set("limit", String(LIMITE_DESCARGA));
        parametros.set("offset", String(offset));

        const datos = await consultarBitacora(parametros);

        if (!datos) return null;

        const items = Array.isArray(datos.items)
            ? datos.items
            : [];

        total = Number(datos.total) || 0;

        eventos.push(...items);

        if (!items.length) break;

        offset += items.length;
    } while (offset < total);

    return eventos;
}

function compararEventos(a, b, orden) {
    const tiempoA = new Date(a.timestamp).getTime();
    const tiempoB = new Date(b.timestamp).getTime();

    if (tiempoA !== tiempoB) {
        return orden === "asc"
            ? tiempoA - tiempoB
            : tiempoB - tiempoA;
    }

    const idA = String(a.event_id || "");
    const idB = String(b.event_id || "");

    return orden === "asc"
        ? idA.localeCompare(idB)
        : idB.localeCompare(idA);
}

async function obtenerPaginaTecnica() {
    const resultados = await Promise.all(
        ACCIONES_TECNICAS.map(descargarEventosAccion)
    );

    if (resultados.some((resultado) => resultado === null)) {
        return null;
    }

    const orden = elementosBitacora.filtroOrden.value || "desc";

    const eventos = resultados
        .flat()
        .sort((a, b) => compararEventos(a, b, orden));

    return {
        items: eventos.slice(
            offsetActual,
            offsetActual + LIMITE_PAGINA
        ),
        total: eventos.length,
        limit: LIMITE_PAGINA,
        offset: offsetActual
    };
}

async function obtenerEventosActuales() {
    if (resumenActivo === "tecnicos") {
        return obtenerPaginaTecnica();
    }

    return obtenerPaginaNormal();
}

function mostrarCarga() {
    mostrar(elementosBitacora.estadoCarga);

    ocultar(elementosBitacora.estadoError);
    ocultar(elementosBitacora.estadoVacio);
    ocultar(elementosBitacora.contenedorTabla);
    ocultar(elementosBitacora.paginacion);
}

function mostrarError(mensaje) {
    ocultar(elementosBitacora.estadoCarga);
    ocultar(elementosBitacora.estadoVacio);
    ocultar(elementosBitacora.contenedorTabla);
    ocultar(elementosBitacora.paginacion);

    elementosBitacora.mensajeError.textContent = mensaje;

    mostrar(elementosBitacora.estadoError);
}

function mostrarVacio() {
    ocultar(elementosBitacora.estadoCarga);
    ocultar(elementosBitacora.estadoError);
    ocultar(elementosBitacora.contenedorTabla);
    ocultar(elementosBitacora.paginacion);

    mostrar(elementosBitacora.estadoVacio);
}

function mostrarTabla() {
    ocultar(elementosBitacora.estadoCarga);
    ocultar(elementosBitacora.estadoError);
    ocultar(elementosBitacora.estadoVacio);

    mostrar(elementosBitacora.contenedorTabla);
    mostrar(elementosBitacora.paginacion);
}

function crearCelda(texto = "") {
    const celda = document.createElement("td");
    celda.textContent = texto;
    return celda;
}

function crearCeldaFecha(evento) {
    const celda = document.createElement("td");
    celda.className = "celda-fecha";
    celda.textContent = formatearFechaEvento(evento.timestamp);
    return celda;
}

function crearCeldaAccion(evento) {
    const celda = document.createElement("td");
    const etiqueta = document.createElement("span");

    etiqueta.className = "etiqueta-evento";
    etiqueta.textContent = textoAccion(evento.action);
    celda.appendChild(etiqueta);
    return celda;
}

function crearCeldaResultado(evento) {
    const celda = document.createElement("td");
    const etiqueta = document.createElement("span");

    etiqueta.className =
        `etiqueta-resultado ${claseResultado(evento.outcome)}`;

    etiqueta.textContent = textoResultado(evento.outcome);

    celda.appendChild(etiqueta);
    return celda;
}

function crearCeldaAlerta(evento) {
    const celda = document.createElement("td");
    celda.className = "celda-alerta";

    if (!evento.alerta_id) {
        celda.textContent = "—";
        return celda;
    }
    const identificador = document.createElement("span");

    identificador.className = "id-recortado";
    identificador.textContent = evento.alerta_id;
    identificador.title = evento.alerta_id;
    celda.appendChild(identificador);
    return celda;
}

function crearCeldaCanal(evento) {
    const celda = document.createElement("td");

    if (!evento.channel) {
        celda.textContent = "—";
        return celda;
    }

    const etiqueta = document.createElement("span");
    etiqueta.className = "etiqueta-canal";
    etiqueta.textContent = textoCanal(evento.channel);
    celda.appendChild(etiqueta);
    return celda;
}

function crearCeldaDetalle(evento) {
    const celda = document.createElement("td");
    const boton = document.createElement("button");

    boton.type = "button";
    boton.className = "boton-detalle-evento";
    boton.textContent = "Ver detalle";
    boton.setAttribute(
        "aria-label",
        `Ver detalle del evento ${textoAccion(evento.action)}`
    );

    boton.addEventListener("click", () => {
        abrirDetalle(evento, boton);
    });

    celda.appendChild(boton);
    return celda;
}

function renderizarEventos(eventos) {
    limpiarElemento(elementosBitacora.tabla);

    for (const evento of eventos) {
        const fila = document.createElement("tr");

        fila.appendChild(crearCeldaFecha(evento));
        fila.appendChild(crearCeldaAccion(evento));
        fila.appendChild(crearCeldaResultado(evento));
        fila.appendChild(crearCelda(textoActor(evento)));
        fila.appendChild(crearCeldaAlerta(evento));
        fila.appendChild(crearCeldaCanal(evento));
        fila.appendChild(crearCeldaDetalle(evento));

        elementosBitacora.tabla.appendChild(fila);
    }
}

function actualizarPaginacion(total) {
    totalActual = total;
    if (!total) {
        elementosBitacora.textoPaginacion.textContent = "0 eventos";
        elementosBitacora.paginaAnterior.disabled = true;
        elementosBitacora.paginaSiguiente.disabled = true;
        return;
    }

    const inicio = offsetActual + 1;
    const fin = Math.min(
        offsetActual + LIMITE_PAGINA,
        total
    );

    elementosBitacora.textoPaginacion.textContent =
        `${inicio}-${fin} de ${total} eventos`;

    elementosBitacora.paginaAnterior.disabled =
        offsetActual <= 0;

    elementosBitacora.paginaSiguiente.disabled =
        offsetActual + LIMITE_PAGINA >= total;
}

function actualizarTarjetasActivas() {
    elementosBitacora.tarjetasResumen.forEach((tarjeta) => {
        tarjeta.classList.toggle(
            "activa",
            tarjeta.dataset.resumen === resumenActivo
        );
    });
}

function resumenDesdeAccion(accion) {
    if (accion === "alerts.register") return "alertas";
    if (accion === "notifications.send") return "despachos";
    if (accion === "alerts.evaluate") return "evaluaciones";
    return "todos";
}

async function cargarBitacora() {
    const carga = ++numeroCarga;

    mostrarCarga();
    actualizarPeriodoVisible();
    actualizarTarjetasActivas();

    try {
        const [resumen, datos] = await Promise.all([
            obtenerResumenPeriodo(),
            obtenerEventosActuales()
        ]);

        if (carga !== numeroCarga) return;
        if (!resumen || !datos) return;

        renderizarResumen(resumen);

        const eventos = Array.isArray(datos.items)
            ? datos.items
            : [];

        const total = Number(datos.total) || 0;

        if (
            total > 0 &&
            offsetActual >= total
        ) {
            offsetActual = Math.max(
                0,
                Math.floor((total - 1) / LIMITE_PAGINA) *
                    LIMITE_PAGINA
            );

            await cargarBitacora();
            return;
        }

        actualizarPaginacion(total);

        if (!eventos.length) {
            limpiarElemento(elementosBitacora.tabla);
            mostrarVacio();
            return;
        }

        renderizarEventos(eventos);
        mostrarTabla();
    } catch (error) {
        if (carga !== numeroCarga) return;
        console.error("ERROR BITACORA:", error);
        mostrarError(mensajeSegunEstado(error?.estado));
    }
}

function seleccionarResumen(tipo) {resumenActivo = tipo; offsetActual = 0;

    if (tipo === "todos") {elementosBitacora.filtroAccion.value = "";}

    if (tipo === "alertas") {
        elementosBitacora.filtroAccion.value ="alerts.register";}

    if (tipo === "despachos") {
        elementosBitacora.filtroAccion.value ="notifications.send";}

    if (tipo === "evaluaciones") {elementosBitacora.filtroAccion.value ="alerts.evaluate";}

    if (tipo === "tecnicos") {elementosBitacora.filtroAccion.value = "";}

    cargarBitacora();
}

function cambiarSemana(cantidad) {
    const nuevaFecha = new Date(fechaReferencia);

    nuevaFecha.setDate(
        nuevaFecha.getDate() + cantidad * 7
    );

    fechaReferencia = nuevaFecha;
    offsetActual = 0;

    cargarBitacora();
}

function manejarCambioFecha() {
    const nuevaFecha = fechaDesdeInput(
        elementosBitacora.fechaReferencia.value
    );

    if (!nuevaFecha) return;

    fechaReferencia = nuevaFecha;
    offsetActual = 0;

    cargarBitacora();
}

function aplicarFiltros(evento) {
    evento.preventDefault();

    resumenActivo = resumenDesdeAccion(
        elementosBitacora.filtroAccion.value
    );

    offsetActual = 0;

    cargarBitacora();
}

function limpiarFiltros() {
    elementosBitacora.filtroAlerta.value = "";
    elementosBitacora.filtroAccion.value = "";
    elementosBitacora.filtroResultado.value = "";
    elementosBitacora.filtroOrden.value = "desc";

    resumenActivo = "todos";
    offsetActual = 0;

    cargarBitacora();
}

function irPaginaAnterior() {
    if (offsetActual <= 0) return;

    offsetActual = Math.max(
        0,
        offsetActual - LIMITE_PAGINA
    );

    cargarBitacora();
}

function irPaginaSiguiente() {
    if (
        offsetActual + LIMITE_PAGINA >=
        totalActual
    ) {
        return;
    }
    offsetActual += LIMITE_PAGINA;
    cargarBitacora();
}

function abrirDetalle(evento, elementoOrigen) {
    eventoSeleccionado = evento;
    focoAnterior = elementoOrigen || document.activeElement;

    elementosBitacora.detalleFecha.textContent =
        formatearFechaEvento(evento.timestamp);

    elementosBitacora.detalleAccion.textContent =
        textoAccion(evento.action);

    elementosBitacora.detalleResultado.textContent =
        textoResultado(evento.outcome);

    elementosBitacora.detalleActor.textContent =
        evento.actor_id
            ? `Usuario · ${evento.actor_id}`
            : "Sistema";

    elementosBitacora.detalleAlerta.textContent =
        evento.alerta_id || "—";

    elementosBitacora.detalleSesion.textContent =
        evento.sesion_id || "—";

    elementosBitacora.detalleSecuencia.textContent =
        evento.sequence ?? "—";

    elementosBitacora.detalleCanal.textContent =
        textoCanal(evento.channel);

    elementosBitacora.detalleError.textContent =
        evento.error_code || "—";

    elementosBitacora.detalleDuracion.textContent =
        evento.duration_ms === null ||
        evento.duration_ms === undefined
            ? "—"
            : `${evento.duration_ms} ms`;

    elementosBitacora.verEventosAlerta.hidden =
        !evento.alerta_id;

    mostrar(elementosBitacora.detalleFondo);

    document.body.style.overflow = "hidden";

    setTimeout(() => {elementosBitacora.cerrarDetalle.focus();}, 0);
}

function cerrarDetalle() {
    ocultar(elementosBitacora.detalleFondo);

    document.body.style.overflow = "";

    eventoSeleccionado = null;

    if (focoAnterior) {focoAnterior.focus();}
}

function consultarEventosAlerta() {
    if (!eventoSeleccionado?.alerta_id) return;

    elementosBitacora.filtroAlerta.value =
        eventoSeleccionado.alerta_id;

    elementosBitacora.filtroAccion.value = "";
    resumenActivo = "todos";
    offsetActual = 0;
    cerrarDetalle();
    cargarBitacora();
}

function manejarEscape(evento) {
    if (evento.key !== "Escape") return;

    if (
        elementosBitacora.detalleFondo &&
        !elementosBitacora.detalleFondo.hidden
    ) {cerrarDetalle();}
}

elementosBitacora.semanaAnterior?.addEventListener(
    "click",
    () => cambiarSemana(-1)
);

elementosBitacora.semanaSiguiente?.addEventListener("click",
    () => cambiarSemana(1)
);

elementosBitacora.fechaReferencia?.addEventListener("change",manejarCambioFecha);

elementosBitacora.recargar?.addEventListener("click",cargarBitacora);

elementosBitacora.reintentar?.addEventListener("click",cargarBitacora);

elementosBitacora.formulario?.addEventListener("submit",aplicarFiltros);

elementosBitacora.limpiarFiltros?.addEventListener("click",limpiarFiltros);

elementosBitacora.paginaAnterior?.addEventListener("click",irPaginaAnterior);

elementosBitacora.paginaSiguiente?.addEventListener("click",irPaginaSiguiente);

elementosBitacora.cerrarDetalle?.addEventListener("click",cerrarDetalle);

elementosBitacora.verEventosAlerta?.addEventListener("click",consultarEventosAlerta);

elementosBitacora.detalleFondo?.addEventListener(
    "click",
    (evento) => {
        if (evento.target === elementosBitacora.detalleFondo) {
            cerrarDetalle();
        }
    }
);

elementosBitacora.tarjetasResumen.forEach((tarjeta) => {
    tarjeta.addEventListener("click", () => {
        seleccionarResumen(
            tarjeta.dataset.resumen || "todos"
        );
    });
});
document.addEventListener("keydown",manejarEscape);
fechaReferencia = new Date();
elementosBitacora.filtroOrden.value = "desc";

actualizarPeriodoVisible();
cargarBitacora();