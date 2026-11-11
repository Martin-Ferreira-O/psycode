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
    formularioBusqueda: document.querySelector("#formularioBusquedaAlertas"),
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
    grafico: document.querySelector("#graficoBarras"),
    tituloGrafico: document.querySelector("#tituloGrafico"),
    botonesPeriodo: document.querySelectorAll(".boton-periodo-dashboard"),
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
let busquedaAplicada = "";
let alertaSeleccionada = null;
let periodoGrafico = "mes";
let solicitudGrafico = 0;

const evaluacionesEnCurso = new Set();
const evaluacionesConfirmadas = new Map();

const coloresGrafico = [
    "#4b86bd",
    "#5da77c",
    "#d5a04b",
    "#8b6fc2",
    "#c85f75",
    "#4aa3a2",
    "#607d9b",
];

function actualizarBotonEvaluacion() {
    establecerCargaBoton(elementos.guardar, false);

    elementos.guardar.disabled =
        !alertaSeleccionada ||
        alertaSeleccionada.estado_evaluacion !== "pendiente";

    if (
        alertaSeleccionada &&
        evaluacionesEnCurso.has(alertaSeleccionada.alerta_id)
    ) {
        establecerCargaBoton(
            elementos.guardar,
            true,
            "Guardando…"
        );
    }
}

async function cargarResumenAlertas(forzar = false) {
    if (solicitudResumen) {
        return solicitudResumen;
    }

    if (resumenCargado && !forzar) {
        return;
    }

    if (!resumenCargado) {
        elementos.total.textContent = "—";
        elementos.pendientes.textContent = "—";
        elementos.revisadas.textContent = "—";
    }

    solicitudResumen = (async () => {
        try {
            const [pendientes, revisadas] = await Promise.all([
                apiGetDatos(
                    "/api/v1/alerts?revisadas=false&limit=1&offset=0"
                ),
                apiGetDatos(
                    "/api/v1/alerts?revisadas=true&limit=1&offset=0"
                ),
            ]);

            if (
                !Number.isInteger(pendientes.total) ||
                !Number.isInteger(revisadas.total)
            ) {
                throw new ErrorSolicitud();
            }

            totalAlertas = pendientes.total + revisadas.total;

            elementos.pendientes.textContent =
                String(pendientes.total);

            elementos.revisadas.textContent =
                String(revisadas.total);

            elementos.total.textContent =
                String(totalAlertas);

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

function fechaApi(fecha) {
    const anio = fecha.getFullYear();
    const mes = String(fecha.getMonth() + 1).padStart(2, "0");
    const dia = String(fecha.getDate()).padStart(2, "0");

    return `${anio}-${mes}-${dia}`;
}

function copiarFecha(fecha) {
    return new Date(
        fecha.getFullYear(),
        fecha.getMonth(),
        fecha.getDate()
    );
}

function sumarDias(fecha, cantidad) {
    const resultado = copiarFecha(fecha);
    resultado.setDate(resultado.getDate() + cantidad);
    return resultado;
}

function etiquetaDia(fecha) {
    const texto = new Intl.DateTimeFormat(
        "es-CL",
        {
            weekday: "short",
        }
    ).format(fecha);

    return texto
        .replace(".", "")
        .replace(/^./, (letra) => letra.toUpperCase());
}



function construirPeriodosMes() {
    const hoy = new Date();
    const periodos = [];

    for (let indice = 5; indice >= 0; indice -= 1) {
        const fecha = new Date(
            hoy.getFullYear(),
            hoy.getMonth() - indice,
            1
        );

        const inicio = new Date(
            fecha.getFullYear(),
            fecha.getMonth(),
            1
        );

        const fin = new Date(
            fecha.getFullYear(),
            fecha.getMonth() + 1,
            0
        );

        const etiqueta = new Intl.DateTimeFormat(
            "es-CL",
            {
                month: "short",
            }
        )
            .format(fecha)
            .replace(".", "")
            .replace(/^./, (letra) => letra.toUpperCase());

        periodos.push({
            etiqueta,
            desde: fechaApi(inicio),
            hasta: fechaApi(fin),
        });
    }

    return periodos;
}


async function obtenerTotalPeriodo(periodo) {
    const parametros = new URLSearchParams({
        fecha_desde: periodo.desde,
        fecha_hasta: periodo.hasta,
        limit: "1",
        offset: "0",
    });

    const data = await apiGetDatos(
        `/api/v1/alerts?${parametros.toString()}`
    );

    if (!Number.isInteger(data?.total)) {
        throw new ErrorSolicitud();
    }

    return {
        ...periodo,
        total: data.total,
    };
}

function renderizarGrafico(datos) {
    elementos.grafico.replaceChildren();

    const maximo = Math.max(
        ...datos.map((item) => item.total),
        1
    );

    const fragmento = document.createDocumentFragment();

    datos.forEach(
        (item, indice) => {
            const grupo =
                document.createElement("div");

            grupo.className =
                "grupo-barra-dashboard";

            const valor =
                document.createElement("span");

            valor.className =
                "valor-barra-dashboard";

            valor.textContent =
                String(item.total);

            const contenedor =
                document.createElement("div");

            contenedor.className =
                "contenedor-barra-dashboard";

            const barra =
                document.createElement("div");

            barra.className =
                "barra-dashboard";

            const porcentaje =
                item.total === 0
                    ? 4
                    : Math.max(
                        12,
                        Math.round(
                            (item.total / maximo) * 100
                        )
                    );

            barra.style.height =
                `${porcentaje}%`;

            barra.style.background =
                coloresGrafico[
                    indice % coloresGrafico.length
                ];

            barra.title =
                `${item.etiqueta}: ${item.total} ` +
                `alerta${item.total === 1 ? "" : "s"}`;

            barra.setAttribute(
                "aria-label",
                barra.title
            );

            const etiqueta =
                document.createElement("span");

            etiqueta.className =
                "etiqueta-barra-dashboard";

            etiqueta.textContent =
                item.etiqueta;

            contenedor.append(barra);

            grupo.append(
                valor,
                contenedor,
                etiqueta
            );

            fragmento.append(grupo);
        }
    );

    elementos.grafico.append(fragmento);
}

function mostrarEstadoGrafico(texto) {
    elementos.grafico.innerHTML = "";

    const estado =
        document.createElement("div");

    estado.className =
        "grafico-cargando";

    estado.textContent = texto;

    elementos.grafico.append(estado);
}

async function cargarGraficoAlertas() {
    const idSolicitud = ++solicitudGrafico;

    mostrarEstadoGrafico(
        "Cargando gráfico..."
    );

    const periodos = construirPeriodosMes();

    elementos.tituloGrafico.textContent =
    "Comportamiento mensual";

    try {
        const datos = await Promise.all(
            periodos.map(obtenerTotalPeriodo)
        );

        if (idSolicitud !== solicitudGrafico) {
            return;
        }

        renderizarGrafico(datos);
    } catch (error) {
        if (idSolicitud !== solicitudGrafico) {
            return;
        }

        mostrarEstadoGrafico(
            "No se pudo cargar el gráfico."
        );
    }
}

function construirUrlAlertas(offsetSolicitado) {
    const parametros = new URLSearchParams({
        limit: String(registrosPorPagina),
        offset: String(offsetSolicitado),
    });

    const codigoUuid =
        Object.entries(codigosAlerta)
            .find(
                ([, codigo]) =>
                    codigo.toLowerCase() ===
                    busquedaAplicada.toLowerCase()
            )?.[0];

    const estado =
        elementos.estado.value;

    if (busquedaAplicada) {
        parametros.set(
            "q",
            codigoUuid || busquedaAplicada
        );
    }

    if (elementos.box.value) {
        parametros.set(
            "box",
            elementos.box.value
        );
    }

    if (estado === "__revisadas__") {
        parametros.set(
            "revisadas",
            "true"
        );
    } else if (estado) {
        parametros.set(
            "estado_evaluacion",
            estado
        );
    }

    if (elementos.desde.value) {
        parametros.set(
            "fecha_desde",
            elementos.desde.value
        );
    }

    if (elementos.hasta.value) {
        parametros.set(
            "fecha_hasta",
            elementos.hasta.value
        );
    }

    return `/api/v1/alerts?${parametros.toString()}`;
}

async function cargarAlertas(offsetSolicitado = 0) {
    const idSolicitud = ++solicitudLista;

    elementos.resultadoTexto.textContent =
        "Consultando alertas…";

    mostrarCarga(
        elementos.estadoVacio,
        "Cargando alertas…"
    );

    elementos.tablaContenedor.hidden = true;
    elementos.paginacion.hidden = true;

    try {
        const data = await apiGetDatos(
            construirUrlAlertas(offsetSolicitado)
        );

        if (
            !Array.isArray(data?.items) ||
            !Number.isInteger(data.total)
        ) {
            throw new ErrorSolicitud();
        }

        if (idSolicitud !== solicitudLista) {
            return;
        }

        alertas = data.items;
        totalCoincidencias = data.total;
        offsetActual = data.offset;

        paginaActual =
            Math.floor(
                offsetActual / registrosPorPagina
            ) + 1;

        renderizarTabla();
    } catch (error) {
        if (idSolicitud !== solicitudLista) {
            return;
        }

        elementos.resultadoTexto.textContent =
            "No se pudieron consultar las alertas.";

        elementos.tablaContenedor.hidden = true;
        elementos.paginacion.hidden = true;

        mostrarError(
            elementos.estadoVacio,
            error,
            {
                mensajes: {
                    404: "No encontramos las alertas solicitadas.",
                },
                reintentar: () =>
                    cargarAlertas(offsetSolicitado),
            }
        );
    }
}

function crearCelda(
    texto,
    clase = "",
    descripcion = ""
) {
    const celda =
        document.createElement("td");

    if (!clase) {
        celda.textContent =
            texto || "—";

        return celda;
    }

    const etiqueta =
        document.createElement("span");

    etiqueta.className = clase;
    etiqueta.textContent =
        texto || "—";

    if (descripcion) {
        etiqueta.title = descripcion;

        etiqueta.setAttribute(
            "aria-label",
            descripcion
        );
    }

    celda.append(etiqueta);

    return celda;
}

function renderizarTabla() {
    const totalPaginas =
        Math.ceil(
            totalCoincidencias /
            registrosPorPagina
        );

    const primero =
        totalCoincidencias === 0
            ? 0
            : offsetActual + 1;

    const final =
        Math.min(
            offsetActual + alertas.length,
            totalCoincidencias
        );

    elementos.resultadoTexto.textContent =
        `${totalCoincidencias} alerta` +
        `${totalCoincidencias === 1 ? "" : "s"} ` +
        `encontrada${totalCoincidencias === 1 ? "" : "s"}`;

    if (totalCoincidencias === 0) {
        const hayFiltros = Boolean(busquedaAplicada) || [
            elementos.box,
            elementos.estado,
            elementos.desde,
            elementos.hasta,
        ].some(
            (control) =>
                control.value.trim()
        );

        mostrarVacio(
            elementos.estadoVacio,
            hayFiltros
                ? "No hay alertas que coincidan con los filtros. Prueba con otros criterios."
                : "Todavía no hay alertas registradas."
        );
    } else {
        limpiarEstado(
            elementos.estadoVacio
        );
    }

    elementos.tablaContenedor.hidden =
        totalCoincidencias === 0;

    elementos.paginacion.hidden =
        totalCoincidencias === 0;

    const filas =
        document.createDocumentFragment();

    alertas.forEach(
        (alerta) => {
            const nivel =
                nivelPresentacion(alerta);

            const estado =
                alerta.estado_evaluacion === "pendiente"
                    ? "estado-pendiente"
                    : "estado-revisada";

            const fila =
                document.createElement("tr");

            fila.append(
                crearCelda(
                    codigoAlertaVisible(
                        alerta.alerta_id
                    ),
                    "identificador-alerta"
                ),
                crearCelda(
                    formatearBox(
                        alerta.box
                    )
                ),
                crearCelda(
                    formatearTipoRiesgo(
                        alerta.tipo_riesgo
                    ),
                    "etiqueta-tipo"
                ),
                crearCelda(
                    nivel.texto,
                    `etiqueta-nivel ${nivel.clase}`,
                    `Nivel: ${nivel.texto}`
                ),
                crearCelda(
                    formatearFecha(
                        alerta.fecha_hora
                    )
                ),
                crearCelda(
                    formatearHora(
                        alerta.fecha_hora
                    )
                ),
                crearCelda(
                    alerta.estado_evaluacion ===
                        "pendiente"
                        ? "Pendiente"
                        : "Revisada",
                    `etiqueta-estado ${estado}`,
                    "Estado de evaluación: " +
                        etiquetas[
                            alerta.estado_evaluacion
                        ]
                )
            );

            const accion =
                document.createElement("td");

            const boton =
                document.createElement("button");

            boton.type = "button";

            boton.className =
                "boton-revisar";

            boton.dataset.alerta =
                alerta.alerta_id;

            boton.textContent =
                alerta.estado_evaluacion ===
                    "pendiente"
                    ? "Revisar"
                    : "Ver detalle";

            accion.append(boton);
            fila.append(accion);
            filas.append(fila);
        }
    );

    elementos.tabla.replaceChildren(filas);

    elementos.textoPaginacion.textContent =
        `Mostrando ${primero}–${final} de ${totalCoincidencias}`;

    elementos.numerosPagina.replaceChildren();

    const paginaInicial =
        Math.max(
            1,
            Math.min(
                paginaActual - 2,
                totalPaginas - 4
            )
        );

    const paginaFinal =
        Math.min(
            totalPaginas,
            paginaInicial + 4
        );

    for (
        let numero = paginaInicial;
        numero <= paginaFinal;
        numero += 1
    ) {
        const boton =
            document.createElement("button");

        boton.type = "button";

        boton.className =
            numero === paginaActual
                ? "activo"
                : "";

        boton.dataset.pagina =
            String(numero);

        boton.textContent =
            String(numero);

        if (numero === paginaActual) {
            boton.setAttribute(
                "aria-current",
                "page"
            );
        }

        elementos.numerosPagina.append(
            boton
        );
    }

    elementos.anterior.disabled =
        paginaActual <= 1;

    elementos.siguiente.disabled =
        paginaActual >= totalPaginas;
}

function completarDetalle(alerta) {
    completarContenidoDetalle(alerta);

    const pendiente =
        alerta.estado_evaluacion ===
        "pendiente";

    document.querySelector(
        "#formularioEvaluacion"
    ).hidden = !pendiente;

    document.querySelector(
        "#evaluacionRegistrada"
    ).hidden = pendiente;

    document
        .querySelectorAll(
            'input[name="evaluacion"]'
        )
        .forEach(
            (opcion) => {
                opcion.checked = false;
            }
        );

    limpiarEstado(
        document.querySelector(
            "#mensajeEvaluacion"
        )
    );
}

const focoModalDetalle = crearControlFocoModal(elementos.modal);

async function abrirDetalle(alertaId, origen) {
    const idSolicitud =
        ++solicitudDetalle;

    limpiarTranscripcion();

    elementos.modal
        .querySelectorAll(".detalle-grid")
        .forEach(
            (bloque) => {
                bloque.hidden = true;
            }
        );

    document.querySelector(
        "#tituloModal"
    ).textContent = "Detalle de alerta";

    const evaluacionAnterior =
        evaluacionesConfirmadas.get(
            alertaId
        );

    alertaSeleccionada = null;

    actualizarBotonEvaluacion();

    elementos.modal.hidden = false;

    document.body.classList.add(
        "modal-abierto"
    );

    document.querySelector(
        "#formularioEvaluacion"
    ).hidden = true;

    document.querySelector(
        "#evaluacionRegistrada"
    ).hidden = true;

    mostrarCarga(
        elementos.estadoDetalle,
        "Cargando detalle…"
    );

    focoModalDetalle.abrir(elementos.modal.querySelector(".boton-cerrar"), origen);

    try {
        let alerta =
            await apiGetDatos(
                `/api/v1/alerts/${encodeURIComponent(alertaId)}`
            );

        if (
            idSolicitud !== solicitudDetalle
        ) {
            return;
        }

        const confirmada =
            evaluacionesConfirmadas.get(
                alertaId
            );

        if (
            confirmada &&
            confirmada !== evaluacionAnterior
        ) {
            alerta = {
                ...alerta,
                evaluacion: confirmada,
                estado_evaluacion:
                    confirmada.estado_evaluacion,
            };
        }

        alertaSeleccionada = alerta;

        completarDetalle(alerta);

        actualizarBotonEvaluacion();

        limpiarEstado(
            elementos.estadoDetalle
        );
    } catch (error) {
        if (
            idSolicitud !== solicitudDetalle
        ) {
            return;
        }

        mostrarError(
            elementos.estadoDetalle,
            error,
            {
                reintentar: () =>
                    abrirDetalle(alertaId),
            }
        );
    }
}

function cerrarDetalle() {
    solicitudDetalle += 1;

    limpiarTranscripcion();

    elementos.modal.hidden = true;

    document.body.classList.remove(
        "modal-abierto"
    );

    alertaSeleccionada = null;

    actualizarBotonEvaluacion();
    focoModalDetalle.cerrar(elementos.buscar);
}

function aplicarEvaluacion(
    alerta,
    evaluacion
) {
    if (
        evaluacion?.alerta_id !==
            alerta.alerta_id ||
        ![
            "correcta",
            "falso_positivo",
            "neutro",
        ].includes(evaluacion.evaluacion) ||
        evaluacion.estado_evaluacion !==
            evaluacion.evaluacion ||
        typeof evaluacion.usuario !==
            "string" ||
        !evaluacion.fecha_hora
    ) {
        throw new ErrorSolicitud();
    }

    evaluacionesConfirmadas.set(
        alerta.alerta_id,
        evaluacion
    );

    const actualizada = {
        ...alerta,
        evaluacion,
        estado_evaluacion:
            evaluacion.estado_evaluacion,
    };

    alertas = alertas.map(
        (item) =>
            item.alerta_id ===
            alerta.alerta_id
                ? {
                    ...item,
                    ...actualizada,
                }
                : item
    );

    const boton = [
        ...elementos.tabla.querySelectorAll(
            "button[data-alerta]"
        ),
    ].find(
        (item) =>
            item.dataset.alerta ===
            alerta.alerta_id
    );

    if (boton) {
        const fila =
            boton.closest("tr");

        fila.children[6].replaceWith(
            crearCelda(
                "Revisada",
                "etiqueta-estado estado-revisada",
                "Estado de evaluación: " +
                    etiquetas[
                        actualizada.estado_evaluacion
                    ]
            )
        );

        boton.textContent =
            "Ver detalle";
    }

    return actualizada;
}

async function guardarEvaluacion() {
    if (
        !alertaSeleccionada ||
        alertaSeleccionada.estado_evaluacion !==
            "pendiente"
    ) {
        return;
    }

    const alerta =
        alertaSeleccionada;

    const alertaId =
        alerta.alerta_id;

    if (
        evaluacionesEnCurso.has(
            alertaId
        )
    ) {
        return;
    }

    const opcion =
        document.querySelector(
            'input[name="evaluacion"]:checked'
        );

    const mensaje =
        document.querySelector(
            "#mensajeEvaluacion"
        );

    if (!opcion) {
        mostrarEstado(
            mensaje,
            "error",
            "Selecciona una opción antes de guardar."
        );

        return;
    }

    const modalVigente = () =>
        !elementos.modal.hidden &&
        alertaSeleccionada?.alerta_id ===
            alertaId;

    evaluacionesEnCurso.add(
        alertaId
    );

    limpiarEstado(mensaje);

    actualizarBotonEvaluacion();

    try {
        const evaluacion =
            await solicitarJson(
                "/api/v1/alerts/" +
                    encodeURIComponent(
                        alertaId
                    ) +
                    "/evaluacion",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body: JSON.stringify({
                        evaluacion:
                            opcion.value,
                    }),
                },
                apiRequest
            );

        const actualizada =
            aplicarEvaluacion(
                alerta,
                evaluacion
            );

        if (modalVigente()) {
            alertaSeleccionada =
                actualizada;

            completarDetalle(
                actualizada
            );

            mostrarEstado(
                elementos.estadoDetalle,
                "exito",
                "Evaluación registrada."
            );
        }

        void cargarResumenAlertas(true);
        void cargarGraficoAlertas();
    } catch (error) {
        if (
            error instanceof ErrorSolicitud &&
            error.estado === 409
        ) {
            if (modalVigente()) {
                document.querySelector(
                    "#formularioEvaluacion"
                ).hidden = true;

                alertaSeleccionada = {
                    ...alerta,
                    estado_evaluacion:
                        "registrada",
                };
            }

            try {
                const evaluacion =
                    await apiGetDatos(
                        "/api/v1/alerts/" +
                            encodeURIComponent(
                                alertaId
                            ) +
                            "/evaluacion"
                    );

                const actualizada =
                    aplicarEvaluacion(
                        alerta,
                        evaluacion
                    );

                if (modalVigente()) {
                    alertaSeleccionada =
                        actualizada;

                    completarDetalle(
                        actualizada
                    );

                    mostrarEstado(
                        elementos.estadoDetalle,
                        "error",
                        "La alerta ya tiene una evaluación. Se actualizó el detalle."
                    );
                }

                void cargarResumenAlertas(
                    true
                );

                void cargarGraficoAlertas();
            } catch (consultaError) {
                if (modalVigente()) {
                    mostrarError(
                        elementos.estadoDetalle,
                        consultaError,
                        {
                            mensajes: {
                                404: "No encontramos la evaluación registrada.",
                            },
                            reintentar: () =>
                                abrirDetalle(
                                    alertaId
                                ),
                        }
                    );
                }
            }
        } else if (modalVigente()) {
            mostrarError(
                mensaje,
                error,
                {
                    mensajes: {
                        400: "El identificador de alerta o la evaluación no son válidos.",
                        404: "La alerta ya no existe.",
                    },
                }
            );
        }
    } finally {
        evaluacionesEnCurso.delete(
            alertaId
        );

        actualizarBotonEvaluacion();
    }
}

function aplicarFiltroInicial() {
    const parametros =
        new URLSearchParams(
            window.location.search
        );

    const revisadas =
        parametros.get("revisadas");

    const estado =
        parametros.get(
            "estado_evaluacion"
        );

    if (revisadas === "true") {
        elementos.estado.value =
            "__revisadas__";
    } else if (
        revisadas === "false"
    ) {
        elementos.estado.value =
            "pendiente";
    } else if (
        estado &&
        [
            ...elementos.estado.options,
        ].some(
            (opcion) =>
                opcion.value === estado
        )
    ) {
        elementos.estado.value =
            estado;
    }
}

elementos.formularioBusqueda.addEventListener("submit", (evento) => {
    evento.preventDefault();
    busquedaAplicada = elementos.buscar.value.trim();
    cargarAlertas(0);
});

[
    elementos.box,
    elementos.estado,
    elementos.desde,
    elementos.hasta,
].forEach(
    (control) => {
        control.addEventListener(
            "change",
            () =>
                cargarAlertas(0)
        );
    }
);

elementos.limpiar.addEventListener(
    "click",
    () => {
        elementos.buscar.value = "";
        busquedaAplicada = "";
        elementos.box.value = "";
        elementos.estado.value = "";
        elementos.desde.value = "";
        elementos.hasta.value = "";

        cargarAlertas(0);
    }
);

elementos.actualizar.addEventListener(
    "click",
    () => {
        cargarAlertas(
            offsetActual
        );

        cargarResumenAlertas(
            true
        );

        cargarGraficoAlertas();
    }
);

elementos.anterior.addEventListener(
    "click",
    () =>
        cargarAlertas(
            Math.max(
                0,
                offsetActual -
                    registrosPorPagina
            )
        )
);

elementos.siguiente.addEventListener(
    "click",
    () => {
        if (
            offsetActual +
                registrosPorPagina <
            totalCoincidencias
        ) {
            cargarAlertas(
                offsetActual +
                    registrosPorPagina
            );
        }
    }
);

elementos.numerosPagina.addEventListener(
    "click",
    (evento) => {
        const boton =
            evento.target.closest(
                "[data-pagina]"
            );

        if (boton) {
            cargarAlertas(
                (
                    Number(
                        boton.dataset.pagina
                    ) - 1
                ) *
                    registrosPorPagina
            );
        }
    }
);

elementos.tabla.addEventListener(
    "click",
    (evento) => {
        const boton =
            evento.target.closest(
                "[data-alerta]"
            );

        if (boton) {
            abrirDetalle(boton.dataset.alerta, boton);
        }
    }
);

elementos.guardar.addEventListener(
    "click",
    guardarEvaluacion
);

elementos.botonesPeriodo.forEach(
    (boton) => {
        boton.addEventListener(
            "click",
            () => {
                cambiarPeriodoGrafico(
                    boton.dataset.periodo
                );
            }
        );
    }
);

document
    .querySelectorAll(
        "[data-cerrar-modal]"
    )
    .forEach(
        (elemento) => {
            elemento.addEventListener(
                "click",
                cerrarDetalle
            );
        }
    );

document.addEventListener(
    "keydown",
    (evento) => {
        if (
            evento.key === "Escape" &&
            !elementos.modal.hidden
        ) {
            cerrarDetalle();
        }
    }
);

aplicarFiltroInicial();
cargarResumenAlertas();
cargarGraficoAlertas();
cargarAlertas(0);
