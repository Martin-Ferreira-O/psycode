if (!verificarSesion()) {
    throw new Error("Sesión no válida");
}

let evaluaciones = [];
let cargandoEvaluaciones = false;

const elementos = {
    tabla: document.querySelector("#tablaEvaluaciones"),
    resultadoTexto: document.querySelector("#resultadoEvaluaciones"),
    estadoVacio: document.querySelector("#estadoVacioEvaluaciones"),
    tablaContenedor: document.querySelector("#tablaEvaluacionesContenedor"),
    modal: document.querySelector("#modalDetalle"),
 
    tituloModal: document.querySelector("#tituloModal"),
 
    detalleBox: document.querySelector("#detalleBox"),
    detalleTipo: document.querySelector("#detalleTipo"),
    detalleNivel: document.querySelector("#detalleNivel"),
    detalleFecha: document.querySelector("#detalleFecha"),
    detalleHora: document.querySelector("#detalleHora"),
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

function renderizarEvaluaciones() {
    elementos.resultadoTexto.textContent =
        evaluaciones.length === 1
            ? "1 evaluación registrada"
            : `${evaluaciones.length} evaluaciones registradas`;

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

    elementos.tabla.innerHTML = evaluaciones
        .map((alerta) => {
            const resultado = obtenerResultado(alerta);

            return `
                <tr>
                    <td>
                        <strong>
                            ${codigoAlertaVisible(alerta.alerta_id)}
                        </strong>
                    </td>

                    <td>
                        <span class="etiqueta-evaluacion ${obtenerClaseEvaluacion(resultado)}">
                            ${obtenerEtiquetaEvaluacion(resultado)}
                        </span>
                    </td>

                    <td>
                        <span class="registro-sistema">
                            ${obtenerRegistroSistema(resultado)}
                        </span>
                    </td>

                    <td>
                        <span class="etiqueta-estado estado-revisada">
                            Revisada
                        </span>
                    </td>

                    <td>
                        <div class="fecha-evaluacion-tabla">
                            <span>
                                ${formatearFecha(alerta.evaluacion?.fecha_hora)}
                            </span>
                            
                            <small>
                            
                            ${formatearHora(alerta.evaluacion?.fecha_hora)}
                            </small>
                        </div>
                    </td>

                    <td>
                        <button
                            type="button"
                            class="boton-ver-detalle boton-revisar"
                            data-alerta="${alerta.alerta_id}"
                        >
                            Ver detalle
                        </button>
                    </td>
                </tr>
            `;
        })
        .join("");

    document.querySelectorAll(".boton-ver-detalle").forEach((boton) => {
        boton.addEventListener("click", () => {
            abrirDetalle(boton.dataset.alerta);
        });
    });
}

function abrirDetalle(alertaId) {
    const alerta = evaluaciones.find(
        (item) => item.alerta_id === alertaId
    );

    if (!alerta) {
        return;
    }

    const resultado = obtenerResultado(alerta);

    elementos.tituloModal.textContent =
        codigoAlertaVisible(alerta.alerta_id);

    elementos.detalleBox.textContent =
        formatearBox(alerta.box);

    elementos.detalleTipo.textContent =
        formatearTipoRiesgo(alerta.tipo_riesgo);

    elementos.detalleNivel.textContent =
        etiquetaNivel(alerta);

    elementos.detalleFecha.textContent =
        formatearFecha(alerta.fecha_hora);

    elementos.detalleHora.textContent =
        formatearHora(alerta.fecha_hora);

    elementos.detalleEstado.textContent =
        "Revisada";

    elementos.resultadoEvaluacion.textContent =
        obtenerEtiquetaEvaluacion(resultado);

    elementos.evaluadoPor.textContent =
        alerta.evaluacion?.usuario || "No disponible";

    elementos.fechaEvaluacion.textContent =
        `${formatearFecha(alerta.evaluacion?.fecha_hora)} · ` +
        `${formatearHora(alerta.evaluacion?.fecha_hora)}`;

    elementos.modal.hidden = false;

    document.body.classList.add(
        "modal-abierto"
    );

    const botonCerrar = elementos.modal.querySelector(
        ".boton-cerrar"
    );

    if (botonCerrar) {
        botonCerrar.focus();
    }
}


function cerrarDetalle() {
    elementos.modal.hidden = true;

    document.body.classList.remove(
        "modal-abierto"
    );
}


async function cargarEvaluaciones() {
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

    elementos.tablaContenedor.setAttribute(
        "aria-busy",
        "true"
    );

    try {
        const data = await apiGetDatos(
            "/api/v1/alerts?revisadas=true"
        );

        if (!Array.isArray(data?.items)) {
            throw new ErrorSolicitud();
        }

        evaluaciones = data.items;

        renderizarEvaluaciones();
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

                reintentar: cargarEvaluaciones,
            }
        );
    } finally {
        cargandoEvaluaciones = false;

        elementos.tablaContenedor.removeAttribute(
            "aria-busy"
        );
    }
}

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
