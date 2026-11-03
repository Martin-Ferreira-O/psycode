const URL_BITACORA = "/api/v1/audit-events";
const URL_EXPORTAR_BITACORA = "/api/v1/audit-events/export";
const LIMITE_PAGINA = 20;
const LIMITE_DESCARGA = 100;

const ACCIONES_TECNICAS = [
    "analysis.speechmatics",
    "analysis.jev",
    "alerts.flow"
];

const DESCRIPCIONES_EVENTO = {
    "": "Consulta registros, evaluaciones, notificaciones y procesos técnicos del período.",
    "alerts.register": "Registro de la generación de una nueva alerta en el sistema.",
    "alerts.evaluate": "Registro de una revisión realizada por un usuario sobre una alerta.",
    "notifications.send": "Intento de envío a un destinatario mediante un canal configurado.",
    "notifications.result": "Resultado general del proceso de notificación, incluidos sus envíos de respaldo.",
    "analysis.speechmatics": "Evento técnico del proceso de transcripción de audio con Speechmatics.",
    "analysis.jev": "Evento técnico del análisis del contenido procesado por JEV.",
    "alerts.flow": "Registro de una etapa del procesamiento de una alerta."
};

const elementosBitacora = {
    periodoActual: document.querySelector("#periodoActual"),
    semanaAnterior: document.querySelector("#semanaAnterior"),
    semanaSiguiente: document.querySelector("#semanaSiguiente"),
    fechaReferencia: document.querySelector("#fechaReferencia"),
    recargar: document.querySelector("#recargarBitacora"),
    descargarExcel: document.querySelector("#descargarExcelBitacora"),
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
    detalleContingencia: document.querySelector("#detalleContingencia"),
    detalleNotificacion: document.querySelector("#detalleNotificacion"),

    verEventosAlerta: document.querySelector("#verEventosAlerta")
};

let fechaReferencia = new Date();
let offsetActual = 0;
let totalActual = 0;
let eventoSeleccionado = null;
let focoAnterior = null;
let numeroCarga = 0;

const porId = (id) => document.getElementById(id);
function icono(nombre) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("aria-hidden", "true");
    const uso = document.createElementNS(svg.namespaceURI, "use");
    uso.setAttribute("href", `#i-${nombre}`);
    svg.append(uso);
    return svg;
}
function nodo(etiqueta, clase, texto) {
    const elemento = document.createElement(etiqueta);
    if (clase) elemento.className = clase;
    if (texto !== undefined) elemento.textContent = texto;
    return elemento;
}
function abreviarId(id) { return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id; }
function horaChile(fecha, opciones) {
    return new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", ...opciones }).format(fecha);
}

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
        "notifications.result": "Resumen de notificación",
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

function textoActor(evento) {
    if (!evento?.actor_id) {
        return "Sistema";
    }

    const actor = evento.actor;

    if (typeof actor === "string" && actor.trim() && actor !== "Usuario") {
        return actor;
    }

    return `Usuario (${evento.actor_id})`;
}

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
    const celda = nodo("td", "celda-fecha");
    const fecha = new Date(evento.timestamp);
    if (!evento.timestamp || Number.isNaN(fecha.getTime())) { celda.textContent = "Fecha no registrada"; return celda; }
    const tiempo = nodo("time");
    tiempo.dateTime = evento.timestamp;
    tiempo.append(nodo("strong", "", horaChile(fecha, {day: "2-digit", month: "short"})),
        nodo("span", "celda-secundaria", horaChile(fecha, {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false})));
    tiempo.title = formatearFechaEvento(evento.timestamp);
    tiempo.setAttribute("aria-label", tiempo.title);
    celda.append(tiempo);
    return celda;
}
function crearCeldaAccion(evento) {
    const celda = nodo("td");
    const etiqueta = nodo("span", "etiqueta-evento", textoAccion(evento.action));
    etiqueta.title = textoAccion(evento.action);
    celda.append(etiqueta);
    const fase = {principal: "Principal", respaldo: "Respaldo", resumen: "Resumen de envíos"}[evento.notification?.phase];
    const contexto = [evento.channel ? textoCanal(evento.channel) : null, fase].filter(Boolean);
    if (contexto.length) celda.append(nodo("span", "celda-secundaria etiqueta-canal", contexto.join(" · ")));
    return celda;
}

function textoResultadoEvento(evento) {
    const estados = {
        EXITO_TOTAL: "Éxito total", FALLO_PARCIAL: "Fallo parcial",
        FALLO_TOTAL: "Fallo total", SIN_DESTINATARIOS_VALIDOS: "Sin destinatarios válidos"
    };
    return estados[evento.notification?.status] || textoResultado(evento.outcome);
}

function crearCeldaResultado(evento) {
    const celda = document.createElement("td");
    const etiqueta = document.createElement("span");

    etiqueta.className =
        `etiqueta-resultado ${claseResultado(evento.outcome)}`;

    etiqueta.title = textoResultadoEvento(evento);
    etiqueta.append(icono(evento.outcome === "failure" ? "warning" : evento.outcome === "success" ? "check" : "minus"),
        nodo("span", "", etiqueta.title));
    celda.setAttribute("aria-label", etiqueta.title);

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
    identificador.textContent = abreviarId(evento.alerta_id);
    identificador.setAttribute("aria-label", `ID de alerta ${evento.alerta_id}. Valor completo disponible en el detalle.`);
    identificador.title = evento.alerta_id;
    celda.appendChild(identificador);
    return celda;
}

function crearCeldaDetalle(evento) {
    const celda = document.createElement("td");
    const boton = document.createElement("button");

    boton.type = "button";
    boton.className = "boton-detalle-evento";
    boton.append(icono("arrow"));
    boton.setAttribute(
        "aria-label",
        `Ver detalle: ${textoAccion(evento.action)}, ${formatearFechaEvento(evento.timestamp)}`
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
        fila.dataset.resultado = evento.outcome;

        fila.appendChild(crearCeldaFecha(evento));
        fila.appendChild(crearCeldaAccion(evento));
        fila.appendChild(crearCeldaResultado(evento));
        const actor = crearCelda(textoActor(evento));
        if (evento.actor_id && textoActor(evento) === `Usuario (${evento.actor_id})`) {
            actor.textContent = `Usuario (${abreviarId(evento.actor_id)})`;
            actor.title = textoActor(evento);
            actor.setAttribute("aria-label", textoActor(evento));
        }
        fila.appendChild(actor);
        fila.appendChild(crearCeldaAlerta(evento));
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

async function cargarBitacora() {
    const carga = ++numeroCarga;

    mostrarCarga();
    actualizarPeriodoVisible();
    try {const datos = await obtenerEventosActuales();

        if (carga !== numeroCarga) return;
        if (!datos) return;

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

    offsetActual = 0;

    cargarBitacora();
}

function limpiarFiltros() {
    elementosBitacora.filtroAlerta.value = "";
    elementosBitacora.filtroAccion.value = "";
    elementosBitacora.filtroResultado.value = "";
    elementosBitacora.filtroOrden.value = "desc";


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
    porId("detalleId").textContent = evento.event_id || "No registrado";
    porId("detalleAccionTecnica").textContent = evento.action || "No registrada";
    porId("explicacionEvento").textContent = `${DESCRIPCIONES_EVENTO[evento.action] || "Evento registrado en el sistema."} Resultado de ejecución: ${textoResultadoEvento(evento).toLowerCase()}.`;
    porId("detalleResultado").className = `etiqueta-resultado ${claseResultado(evento.outcome)}`;
    porId("copiarAlerta").hidden = !evento.alerta_id;
    porId("copiarEvento").hidden = !evento.event_id;
    porId("alcanceRelacion").hidden = !evento.alerta_id;
    porId("seccionNotificacion").hidden = !evento.notification;
    porId("estadoCopia").textContent = "";
    focoAnterior = elementoOrigen || document.activeElement;

    elementosBitacora.detalleFecha.textContent =
        formatearFechaEvento(evento.timestamp);

    elementosBitacora.detalleAccion.textContent =
        textoAccion(evento.action);

    elementosBitacora.detalleResultado.textContent =
        textoResultadoEvento(evento);

    const actor = textoActor(evento);
    const actorNoDisponible = actor === `Usuario (${evento.actor_id})`;

    elementosBitacora.detalleActor.textContent =
        evento.actor_id && !actorNoDisponible
            ? `${actor} · ${evento.actor_id}`
            : actor;

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

    elementosBitacora.detalleContingencia.textContent = evento.contingencia === true
        ? "Sí" : evento.contingencia === false ? "No" : "No registrado";
    mostrarDetalleNotificacion(evento.notification);

    elementosBitacora.verEventosAlerta.hidden =
        !evento.alerta_id;

    mostrar(elementosBitacora.detalleFondo);

    document.body.style.overflow = "hidden";
    porId("aplicacionBitacora").inert = true;

    elementosBitacora.panelDetalle.scrollTop = 0;
    elementosBitacora.cerrarDetalle.focus();
}

function mostrarDetalleNotificacion(notificacion) {
    const contenedor = elementosBitacora.detalleNotificacion;
    limpiarElemento(contenedor);
    contenedor.hidden = !notificacion;
    if (!notificacion) return;
    const modos = { lista_distribucion: "Lista de distribución", supervisores_activos: "Supervisores activos" };
    const fases = { principal: "Envío principal", respaldo: "Envío de respaldo", resumen: "Resumen" };
    const motivos = {
        FALLO_PARCIAL: "Fallo parcial del envío principal",
        FALLO_TOTAL: "Fallo total del envío principal",
        SIN_DESTINATARIOS_VALIDOS: "Sin destinatarios principales válidos"
    };
    const datos = [
        ["ID de notificación", notificacion.id],
        ["Modalidad principal", modos[notificacion.mode] || "No registrada"],
        ["Etapa", fases[notificacion.phase] || "—"],
        ["Motivo", motivos[notificacion.reason] || "No registrado"]
    ];
    if (notificacion.attempt !== undefined) datos.push(["Número de intento", notificacion.attempt]);
    if (notificacion.phase === "resumen") {
        const conteos = (exitos, fallos) => Number.isFinite(exitos) && Number.isFinite(fallos) ? `${exitos} ${exitos === 1 ? "éxito" : "éxitos"} · ${fallos} ${fallos === 1 ? "fallo" : "fallos"}` : "Conteos no registrados";
        datos.push(["Envíos principales", conteos(notificacion.primary_successes, notificacion.primary_failures)]);
        datos.push(["Envíos de respaldo", conteos(notificacion.backup_successes, notificacion.backup_failures)]);
    }
    for (const [etiqueta, valor] of datos) {
        const dato = document.createElement("div");
        dato.className = etiqueta === "ID de notificación" ? "dato-detalle dato-completo" : "dato-detalle";
        const nombre = document.createElement("span");
        nombre.textContent = etiqueta;
        const contenido = document.createElement("strong");
        contenido.textContent = valor ?? "No registrado";
        dato.append(nombre, contenido);
        contenedor.appendChild(dato);
    }
}

function cerrarDetalle() {
    ocultar(elementosBitacora.detalleFondo);

    document.body.style.overflow = "";
    porId("aplicacionBitacora").inert = false;

    eventoSeleccionado = null;

    if (focoAnterior?.isConnected) {focoAnterior.focus();}
}

function consultarEventosAlerta() {
    if (!eventoSeleccionado?.alerta_id) return;

    elementosBitacora.filtroAlerta.value =
        eventoSeleccionado.alerta_id;

    elementosBitacora.filtroAccion.value = "";
    elementosBitacora.filtroResultado.value = "";
    offsetActual = 0;
    cerrarDetalle();
    cargarBitacora();
    elementosBitacora.filtroAlerta.focus();
}

function manejarEscape(evento) {
    if (evento.key !== "Escape") return;

    if (
        elementosBitacora.detalleFondo &&
        !elementosBitacora.detalleFondo.hidden
    ) {cerrarDetalle();}
}

async function descargarExcelBitacora() {
    const boton = elementosBitacora.descargarExcel;

    try {
        if (boton) {
            boton.disabled = true;
            boton.querySelector("span").textContent = "Descargando...";
        }

        const response = await apiGet(URL_EXPORTAR_BITACORA);

        if (!response) return;

        if (!response.ok) {
            throw new Error("No fue posible generar el archivo Excel.");
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        const disposition = response.headers.get("Content-Disposition");
        const coincidencia = disposition?.match(/filename="([^"]+)"/);

        const nombreArchivo = coincidencia?.[1]
            || "bitacora_eventos.xlsx";

        const enlace = document.createElement("a");
        enlace.href = url;
        enlace.download = nombreArchivo;

        document.body.appendChild(enlace);
        enlace.click();
        enlace.remove();

        URL.revokeObjectURL(url);
    } catch (error) {
        alert(
            error.message
            || "No fue posible descargar la bitácora."
        );
    } finally {
        if (boton) {
            boton.disabled = false;
            boton.querySelector("span").textContent = "Descargar Excel";
        }
    }
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
elementosBitacora.descargarExcel?.addEventListener(
    "click",
    descargarExcelBitacora
);

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
document.addEventListener("keydown",manejarEscape);
async function copiarIdentificador(clave, boton) {
    const valor = eventoSeleccionado?.[clave];
    if (!valor) return;
    try {
        await navigator.clipboard.writeText(valor);
        boton.replaceChildren(icono("check"));
        porId("estadoCopia").textContent = "Identificador copiado.";
        setTimeout(() => boton.replaceChildren(icono("copy")), 1800);
    } catch {
        porId("estadoCopia").textContent = "No se pudo copiar. Selecciona el identificador completo para copiarlo manualmente.";
        const rango = document.createRange();
        rango.selectNodeContents(porId(clave === "alerta_id" ? "detalleAlerta" : "detalleId"));
        const seleccion = window.getSelection(); seleccion.removeAllRanges(); seleccion.addRange(rango);
    }
}
porId("copiarAlerta").addEventListener("click", e => copiarIdentificador("alerta_id", e.currentTarget));
porId("copiarEvento").addEventListener("click", e => copiarIdentificador("event_id", e.currentTarget));
document.addEventListener("keydown", e => {
    if (elementosBitacora.detalleFondo.hidden || e.key !== "Tab") return;
    const controles = [...elementosBitacora.panelDetalle.querySelectorAll("button, summary, [tabindex='0']")].filter(el => el.getClientRects().length && !el.disabled);
    const primero = controles[0], ultimo = controles.at(-1);
    if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
});
fechaReferencia = new Date();
elementosBitacora.filtroOrden.value = "desc";

actualizarPeriodoVisible();
cargarBitacora();
