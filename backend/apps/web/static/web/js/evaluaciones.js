const EVALUACIONES_POR_PAGINA = 10;
let offsetEvaluaciones = 0;
let cargandoEvaluaciones = false;
let solicitudDetalle = 0;

const elementos = {
    tabla: document.querySelector("#tablaEvaluaciones"),
    tituloEvaluaciones: document.querySelector("#tituloEvaluaciones"),
    resultadoTexto: document.querySelector("#resultadoEvaluaciones"),
    estadoVacio: document.querySelector("#estadoVacioEvaluaciones"),
    tablaContenedor: document.querySelector("#tablaEvaluacionesContenedor"),
    paginacion: document.querySelector("#paginacionEvaluaciones"),
    pagina: document.querySelector("#paginaEvaluaciones"),
    anterior: document.querySelector("#evaluacionesAnterior"),
    siguiente: document.querySelector("#evaluacionesSiguiente"),
    modal: document.querySelector("#modalDetalle"),
 
    tituloModal: document.querySelector("#tituloModal"),
 
    detalleBox: document.querySelector("#detalleBox"),
    detalleTipo: document.querySelector("#detalleTipo"),
    detalleNivel: document.querySelector("#detalleNivel"),
    detalleFecha: document.querySelector("#detalleFecha"),
    detalleEstado: document.querySelector("#detalleEstado"),
    resultadoEvaluacion: document.querySelector("#resultadoEvaluacion"),
    evaluadoPor: document.querySelector("#evaluadoPor"),
    fechaEvaluacion: document.querySelector("#fechaEvaluacion"),
};

function obtenerRegistroSistema(resultado) {
    const registros = {
        correcta: "Detección confirmada",
        falso_positivo: "Error del modelo",
        neutro: "Indeterminada",
    };

    return registros[resultado] || "Indeterminada";
}

function obtenerClaseEvaluacion(resultado) {
    const clases = {
        correcta: "correcta",
        falso_positivo: "falso-positivo",
        neutro: "neutro",
    };

    return clases[resultado] || "neutro";
}

function renderizarEvaluaciones(evaluaciones, total) {
    const ultimaVisible = offsetEvaluaciones + evaluaciones.length;
    elementos.resultadoTexto.textContent =
        total === 1
            ? "1 evaluación registrada"
            : `${total} evaluaciones registradas`;

    elementos.paginacion.hidden = total <= EVALUACIONES_POR_PAGINA;
    if (!elementos.paginacion.hidden) {
        const paginaActual = Math.floor(offsetEvaluaciones / EVALUACIONES_POR_PAGINA) + 1;
        const paginas = Math.ceil(total / EVALUACIONES_POR_PAGINA);
        elementos.resultadoTexto.textContent = `Mostrando ${offsetEvaluaciones + 1}–${ultimaVisible} de ${total} evaluaciones`;
        elementos.pagina.textContent = `Página ${paginaActual} de ${paginas}`;
        elementos.anterior.disabled = paginaActual === 1;
        elementos.siguiente.disabled = paginaActual === paginas;
    }

    if (evaluaciones.length === 0) {
        mostrarVacio(
            elementos.estadoVacio,
            "Todavía no existen alertas evaluadas."
        );

        elementos.tablaContenedor.hidden = true;
        elementos.tabla.innerHTML = "";
        return;
    }

    limpiarEstado(elementos.estadoVacio);
    elementos.tablaContenedor.hidden = false;

    const filas = evaluaciones.map((alerta) => {
        const resultado = obtenerResultado(alerta);
        const fila = document.createElement("tr");
        fila.setAttribute("role", "row");
        fila.innerHTML = `
            <td role="cell">
                <span class="etiqueta-campo-evaluacion" aria-hidden="true">Alerta</span>
                <strong></strong>
            </td>
            <td role="cell">
                <span class="etiqueta-campo-evaluacion" aria-hidden="true">Evaluación seleccionada</span>
                <span class="etiqueta-evaluacion ${obtenerClaseEvaluacion(resultado)}">
                    ${obtenerEtiquetaEvaluacion(resultado)}
                </span>
            </td>
            <td role="cell">
                <span class="etiqueta-campo-evaluacion" aria-hidden="true">Registro del sistema</span>
                <span class="registro-sistema">${obtenerRegistroSistema(resultado)}</span>
            </td>
            <td role="cell">
                <span class="etiqueta-campo-evaluacion" aria-hidden="true">Estado</span>
                <span class="etiqueta-estado estado-revisada">Revisada</span>
            </td>
            <td role="cell">
                <span class="etiqueta-campo-evaluacion" aria-hidden="true">Fecha de evaluación</span>
                <div class="fecha-evaluacion-tabla">
                    <span>${formatearFecha(alerta.evaluacion?.fecha_hora)}</span>
                    <small>${formatearHora(alerta.evaluacion?.fecha_hora)}</small>
                </div>
            </td>
            <td role="cell" class="celda-detalle-evaluacion">
                <button
                    type="button"
                    class="boton-detalle-evaluacion"
                    title="Ver detalle"
                >
                    <svg
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                        class="icono-detalle-evaluacion"
                    >
                        <path d="M9 6l6 6-6 6"></path>
                    </svg>
                </button>
            </td>
        `;
        const codigoAlerta = codigoAlertaVisible(alerta.alerta_id);
        fila.querySelector("strong").textContent = codigoAlerta;
        const boton = fila.querySelector(".boton-detalle-evaluacion");
        boton.dataset.alerta = alerta.alerta_id;
        boton.setAttribute("aria-label", `Ver detalle de ${codigoAlerta}`);
        boton.addEventListener("click", () => abrirDetalle(alerta.alerta_id, boton));
        return fila;
    });
    elementos.tabla.replaceChildren(...filas);
}

const focoModalDetalle = crearControlFocoModal(elementos.modal);

async function abrirDetalle(alertaId, origen) {
    const idSolicitud = ++solicitudDetalle;
    limpiarTranscripcion();
    elementos.tituloModal.textContent = "Detalle de alerta";
    elementos.modal.hidden = false;
    document.body.classList.add("modal-abierto");
    const estado = document.querySelector("#estadoDetalle");
    const bloques = elementos.modal.querySelectorAll(".detalle-grid, .evaluacion-registrada");
    bloques.forEach(bloque => { bloque.hidden = true; });
    mostrarCarga(estado, "Cargando detalle…");
    focoModalDetalle.abrir(elementos.modal.querySelector(".boton-cerrar"), origen);
    try {
        const alerta = await apiGetDatos(`/api/v1/alerts/${encodeURIComponent(alertaId)}`);
        if (idSolicitud !== solicitudDetalle) return;
        completarContenidoDetalle(alerta);

        bloques.forEach(bloque => { bloque.hidden = false; });
        limpiarEstado(estado);
    } catch (error) {
        if (idSolicitud !== solicitudDetalle) return;
        mostrarError(estado, error, { reintentar: () => abrirDetalle(alertaId) });
    }
}


function cerrarDetalle() {
    solicitudDetalle += 1;
    limpiarTranscripcion();
    elementos.modal.hidden = true;

    document.body.classList.remove(
        "modal-abierto"
    );
    focoModalDetalle.cerrar();
}


async function cargarEvaluaciones(offsetSolicitado = 0, moverFoco = false) {
    if (cargandoEvaluaciones) {
        return;
    }

    cargandoEvaluaciones = true;

    mostrarCarga(
        elementos.estadoVacio,
        "Cargando evaluaciones…"
    );

    elementos.resultadoTexto.textContent =
        "Consultando evaluaciones…";

    elementos.tablaContenedor.hidden = true;
    elementos.paginacion.hidden = true;

    elementos.tablaContenedor.setAttribute(
        "aria-busy",
        "true"
    );

    try {
        const filtros = new URLSearchParams({
            revisadas: "true",
            limit: String(EVALUACIONES_POR_PAGINA),
        });
        let offset = offsetSolicitado;
        let data;
        while (true) {
            filtros.set("offset", String(offset));
            data = await apiGetDatos(`/api/v1/alerts?${filtros}`);
            if (!Array.isArray(data?.items) || !Number.isInteger(data.total) || data.total < 0) {
                throw new ErrorSolicitud();
            }
            if (data.total === 0 || offset < data.total) {
                break;
            }
            offset = Math.floor((data.total - 1) / EVALUACIONES_POR_PAGINA) * EVALUACIONES_POR_PAGINA;
        }

        offsetEvaluaciones = data.total === 0 ? 0 : offset;
        renderizarEvaluaciones(data.items, data.total);
    } catch (error) {
        elementos.resultadoTexto.textContent =
            "No se pudieron consultar las evaluaciones.";

        mostrarError(
            elementos.estadoVacio,
            error,
            {
                mensajes: {
                    404: "No encontramos el registro de evaluaciones solicitado.",
                },

                reintentar: () => cargarEvaluaciones(offsetSolicitado, true),
            }
        );
    } finally {
        cargandoEvaluaciones = false;

        elementos.tablaContenedor.removeAttribute(
            "aria-busy"
        );
        if (moverFoco) {
            elementos.tituloEvaluaciones.focus();
        }
    }
}

elementos.anterior.addEventListener("click", () => {
    cargarEvaluaciones(offsetEvaluaciones - EVALUACIONES_POR_PAGINA, true);
});
elementos.siguiente.addEventListener("click", () => {
    cargarEvaluaciones(offsetEvaluaciones + EVALUACIONES_POR_PAGINA, true);
});

document
    .querySelectorAll("[data-cerrar-modal]")
    .forEach((elemento) => {
        elemento.addEventListener(
            "click",
            cerrarDetalle
        );
    });

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

cargarEvaluaciones();
