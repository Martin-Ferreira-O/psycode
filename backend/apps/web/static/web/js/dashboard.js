if (!verificarSesion()) {
    throw new Error("Sesión no válida");
}

const resultadosEvaluacion = [
    "correcta",
    "falso_positivo",
    "neutro",
];

const etiquetas = {
    riesgo_suicida: "Riesgo suicida",
    vulneracion_derechos: "Vulneración de derechos",
    pendiente: "Pendiente",
    correcta: "Correcta",
    falso_positivo: "Falso positivo",
    neutro: "Neutro",
};

const alertas = Array.from({ length: 20}, (_, indice) => {
    const numero = 84 - indice;
    const pendiente = indice < 2;
    const resultado = pendiente
        ? null
        : resultadosEvaluacion[
            (indice - 2) % resultadosEvaluacion.length
        ];

    const dia = 8 - Math.floor(indice / 5);
    const hora = 17 - (indice % 6);
    const minutos = String((indice * 7) % 60).padStart(2, "0");

    return {
        alerta_id: `ALT-2026-${String(numero).padStart(3, "0")}`,
        box: `box-${(indice % 5) + 1}`,
        tipo_riesgo:
            indice % 2 === 0
                ? "riesgo_suicida"
                : "vulneracion_derechos",
        nivel_severidad: [3, 2, 1][indice % 3],
        fecha_hora:
            `2026-09-${String(dia).padStart(2, "0")}` +
            `T${String(hora).padStart(2, "0")}:${minutos}:00Z`,
        estado_evaluacion: pendiente ? "pendiente" : resultado,
        sesion_id:
            `SES-2026-${String(350 + indice).padStart(3, "0")}`,
        evaluacion: pendiente
            ? null
            : {
                resultado,
                usuario: "psicologo",
                fecha_hora: "2026-09-12T15:10:00Z",
            },
    };
});

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
    guardar: document.querySelector("#guardarEvaluacion"),
};

let paginaActual = 1;
const registrosPorPagina = 10;
let alertaSeleccionada = null;

function formatearBox(box) {
    const numero = box.split("-")[1];
    return `Box ${String(numero).padStart(2, "0")}`;
}

function formatearFecha(fecha) {
    return new Intl.DateTimeFormat("es-CL", {
        dateStyle: "medium",
        timeZone: "America/Santiago",
    }).format(new Date(fecha));
}

function formatearHora(fecha) {
    return new Intl.DateTimeFormat("es-CL", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "America/Santiago",
    }).format(new Date(fecha));
}

function etiquetaNivel(nivel) {
    return {
        1: "Baja",
        2: "Media",
        3: "Alta",
    }[nivel];
}

function actualizarTarjetas() {
    const pendientes = alertas.filter(
        (alerta) => alerta.estado_evaluacion === "pendiente"
    ).length;

    elementos.total.textContent = alertas.length;
    elementos.pendientes.textContent = pendientes;
    elementos.revisadas.textContent =
        alertas.length - pendientes;
}

function obtenerAlertasFiltradas() {
    const busqueda =
        elementos.buscar.value.trim().toLowerCase();

    return alertas.filter((alerta) => {
        const texto = [
            alerta.alerta_id,
            alerta.box,
            etiquetas[alerta.tipo_riesgo],
        ]
            .join(" ")
            .toLowerCase();

        const fecha = alerta.fecha_hora.slice(0, 10);

        return (
            (!busqueda || texto.includes(busqueda)) &&
            (!elementos.box.value ||
                alerta.box === elementos.box.value) &&
            (!elementos.estado.value ||
                alerta.estado_evaluacion ===
                    elementos.estado.value) &&
            (!elementos.desde.value ||
                fecha >= elementos.desde.value) &&
            (!elementos.hasta.value ||
                fecha <= elementos.hasta.value)
        );
    });
}

function renderizarTabla() {
    const filtradas = obtenerAlertasFiltradas();
    const totalPaginas = Math.max(
        1,
        Math.ceil(
            filtradas.length / registrosPorPagina
        )
    );

    if (paginaActual > totalPaginas) {
        paginaActual = totalPaginas;
    }

    const inicio =
        (paginaActual - 1) * registrosPorPagina;

    const alertasPagina = filtradas.slice(
        inicio,
        inicio + registrosPorPagina
    );

    elementos.resultadoTexto.textContent =
        `${filtradas.length} alerta` +
        `${filtradas.length === 1 ? "" : "s"} encontrada` +
        `${filtradas.length === 1 ? "" : "s"}`;

    if (filtradas.length === 0) {
        const hayFiltros = [elementos.buscar, elementos.box, elementos.estado,
            elementos.desde, elementos.hasta].some(control => control.value.trim());
        mostrarVacio(elementos.estadoVacio, hayFiltros
            ? "No hay alertas que coincidan con los filtros. Prueba con otros criterios."
            : "Todavía no hay alertas registradas.");
    } else {
        limpiarEstado(elementos.estadoVacio);
    }
    elementos.tablaContenedor.hidden =
        filtradas.length === 0;
    elementos.paginacion.hidden =
        filtradas.length === 0;

    elementos.tabla.innerHTML = alertasPagina
        .map(
            (alerta) => `
                <tr>
                    <td>
                        <strong>${alerta.alerta_id}</strong>
                    </td>

                    <td>${formatearBox(alerta.box)}</td>

                    <td>
                        ${etiquetas[alerta.tipo_riesgo]}
                    </td>

                    <td>
                        <span class="etiqueta-nivel">
                            ${etiquetaNivel(
                                alerta.nivel_severidad
                            )}
                        </span>
                    </td>

                    <td>
                        ${formatearFecha(alerta.fecha_hora)}
                    </td>

                    <td>
                        ${formatearHora(alerta.fecha_hora)}
                    </td>

                    <td>
                        <span class="etiqueta-estado">
                            ${
                                etiquetas[
                                    alerta.estado_evaluacion
                                ]
                            }
                        </span>
                    </td>

                    <td>
                        <button
                            type="button"
                            class="boton-revisar"
                            data-alerta="${alerta.alerta_id}"
                        >
                            ${
                                alerta.estado_evaluacion ===
                                "pendiente"
                                    ? "Revisar"
                                    : "Ver detalle"
                            }
                        </button>
                    </td>
                </tr>
            `
        )
        .join("");

    const final = Math.min(
        inicio + registrosPorPagina,
        filtradas.length
    );

    elementos.textoPaginacion.textContent =
        `Mostrando ${inicio + 1}–${final} ` +
        `de ${filtradas.length}`;

    elementos.numerosPagina.innerHTML = Array.from(
        { length: totalPaginas },
        (_, indice) => {
            const numeroPagina = indice + 1;

            return `
                <button
                    type="button"
                    class="${
                        numeroPagina === paginaActual
                            ? "activo"
                            : ""
                    }"
                    data-pagina="${numeroPagina}"
                >
                    ${numeroPagina}
                </button>
            `;
        }
    ).join("");

    elementos.anterior.disabled =
        paginaActual === 1;
    elementos.siguiente.disabled =
        paginaActual === totalPaginas;

    document
        .querySelectorAll("[data-alerta]")
        .forEach((boton) => {
            boton.addEventListener("click", () => {
                abrirDetalle(
                    boton.dataset.alerta
                );
            });
        });

    document
        .querySelectorAll("[data-pagina]")
        .forEach((boton) => {
            boton.addEventListener("click", () => {
                paginaActual = Number(
                    boton.dataset.pagina
                );

                renderizarTabla();
            });
        });
}

function completarDetalle(alerta) {
    document.querySelector(
        "#tituloModal"
    ).textContent = alerta.alerta_id;

    document.querySelector(
        "#detalleBox"
    ).textContent = formatearBox(alerta.box);

    document.querySelector(
        "#detalleTipo"
    ).textContent =
        etiquetas[alerta.tipo_riesgo];

    document.querySelector(
        "#detalleNivel"
    ).textContent =
        etiquetaNivel(alerta.nivel_severidad);

    document.querySelector(
        "#detalleFecha"
    ).textContent =
        `${formatearFecha(alerta.fecha_hora)} · ` +
        `${formatearHora(alerta.fecha_hora)}`;

    document.querySelector(
        "#detalleEstado"
    ).textContent =
        etiquetas[alerta.estado_evaluacion];

    document.querySelector(
        "#detalleSesion"
    ).textContent = alerta.sesion_id;

    const formulario = document.querySelector(
        "#formularioEvaluacion"
    );

    const registrada = document.querySelector(
        "#evaluacionRegistrada"
    );

    const pendiente =
        alerta.estado_evaluacion === "pendiente";

    formulario.hidden = !pendiente;
    registrada.hidden = pendiente;

    document
        .querySelectorAll(
            'input[name="evaluacion"]'
        )
        .forEach((opcion) => {
            opcion.checked = false;
        });

    const mensaje = document.querySelector(
        "#mensajeEvaluacion"
    );

    limpiarEstado(mensaje);

    if (alerta.evaluacion) {
        document.querySelector(
            "#resultadoEvaluacion"
        ).textContent =
            etiquetas[
                alerta.evaluacion.resultado
            ];

        document.querySelector(
            "#evaluadoPor"
        ).textContent =
            alerta.evaluacion.usuario;

        document.querySelector(
            "#fechaEvaluacion"
        ).textContent =
            `${formatearFecha(
                alerta.evaluacion.fecha_hora
            )} · ${formatearHora(
                alerta.evaluacion.fecha_hora
            )}`;
    }
}

function abrirDetalle(alertaId) {
    alertaSeleccionada = alertas.find(
        (alerta) => alerta.alerta_id === alertaId
    );

    if (!alertaSeleccionada) {
        return;
    }

    completarDetalle(alertaSeleccionada);
    elementos.modal.hidden = false;
    document.body.classList.add("modal-abierto");

    elementos.modal
        .querySelector(".boton-cerrar")
        .focus();
}

function cerrarDetalle() {
    elementos.modal.hidden = true;
    document.body.classList.remove("modal-abierto");
    alertaSeleccionada = null;
}

function guardarEvaluacion() {
    if (
        !alertaSeleccionada ||
        alertaSeleccionada.estado_evaluacion !==
            "pendiente"
    ) {
        return;
    }

    const opcionSeleccionada =
        document.querySelector(
            'input[name="evaluacion"]:checked'
        );

    const mensaje = document.querySelector(
        "#mensajeEvaluacion"
    );

    if (!opcionSeleccionada) {
        mostrarEstado(mensaje, "error", "Selecciona una opción antes de guardar.");

        return;
    }

    alertaSeleccionada.estado_evaluacion =
        opcionSeleccionada.value;

    alertaSeleccionada.evaluacion = {
        resultado: opcionSeleccionada.value,
        usuario: "autonoma",
        fecha_hora: new Date().toISOString(),
    };

    actualizarTarjetas();
    renderizarTabla();
    completarDetalle(alertaSeleccionada);
}

[
    elementos.buscar,
    elementos.box,
    elementos.estado,
    elementos.desde,
    elementos.hasta,
].forEach((control) => {
    control.addEventListener("input", () => {
        paginaActual = 1;
        renderizarTabla();
    });
});

elementos.limpiar.addEventListener("click", () => {
    elementos.buscar.value = "";
    elementos.box.value = "";
    elementos.estado.value = "";
    elementos.desde.value = "";
    elementos.hasta.value = "";
    paginaActual = 1;

    renderizarTabla();
});

elementos.actualizar.addEventListener(
    "click",
    renderizarTabla
);

elementos.anterior.addEventListener("click", () => {
    if (paginaActual > 1) {
        paginaActual -= 1;
        renderizarTabla();
    }
});

elementos.siguiente.addEventListener("click", () => {
    const totalPaginas = Math.ceil(
        obtenerAlertasFiltradas().length /
            registrosPorPagina
    );

    if (paginaActual < totalPaginas) {
        paginaActual += 1;
        renderizarTabla();
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

actualizarTarjetas();
renderizarTabla();
