if (!verificarSesion()) {
    throw new Error("Sesión no válida");
}
let evaluaciones = [];
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

function renderizarEvaluaciones() {
    elementos.resultadoTexto.textContent =
        `${evaluaciones.length} evaluación` +
        `${evaluaciones.length === 1 ? "" : "es"} registrada` +
        `${evaluaciones.length === 1 ? "" : "s"}`;

    if (evaluaciones.length === 0) {
        elementos.estadoVacio.hidden = false;
        elementos.tablaContenedor.hidden = true;
        elementos.tabla.innerHTML = "";
        return;
    }

    elementos.estadoVacio.hidden = true;
    elementos.tablaContenedor.hidden = false;

    elementos.tabla.innerHTML = evaluaciones
        .map((alerta) => {
            const resultado = obtenerResultado(alerta);

            return `
                <tr>
                    <td>
                        <strong>${alerta.alerta_id}</strong>
                    </td>

                    <td>
                        <span class="etiqueta-evaluacion">
                            ${obtenerEtiquetaEvaluacion(resultado)}
                        </span>
                    </td>

                    <td>
                        <span class="registro-sistema">
                            ${obtenerRegistroSistema(resultado)}
                        </span>
                    </td>

                    <td>
                        <span class="etiqueta-estado">
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

    elementos.tituloModal.textContent = alerta.alerta_id;
    elementos.detalleBox.textContent = formatearBox(alerta.box);
    elementos.detalleTipo.textContent = formatearTipoRiesgo(
        alerta.tipo_riesgo
    );
    elementos.detalleNivel.textContent = etiquetaNivel(alerta);
    elementos.detalleFecha.textContent = formatearFecha(
        alerta.fecha_hora
    );
    elementos.detalleHora.textContent = formatearHora(
        alerta.fecha_hora
    );
    elementos.detalleEstado.textContent = "Revisada";
    elementos.resultadoEvaluacion.textContent =
        obtenerEtiquetaEvaluacion(resultado);

    elementos.evaluadoPor.textContent =
        alerta.evaluacion?.usuario || "No disponible";
    elementos.fechaEvaluacion.textContent =
        `${formatearFecha(alerta.evaluacion?.fecha_hora)} · ` +
        `${formatearHora(alerta.evaluacion?.fecha_hora)}`;

    elementos.modal.hidden = false;
    document.body.classList.add("modal-abierto");

    const botonCerrar = elementos.modal.querySelector(
        ".boton-cerrar"
    );

    if (botonCerrar) {
        botonCerrar.focus();
    }
}


function cerrarDetalle() {
    elementos.modal.hidden = true;
    document.body.classList.remove("modal-abierto");
}


async function cargarEvaluaciones() {
    elementos.resultadoTexto.textContent =
        "Cargando evaluaciones...";

    try {
        const response = await apiGet(
            "/api/v1/alerts?revisadas=true"
        );

        if (!response) {
            return;
        }

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data?.error?.message ||
                data?.message ||
                "No fue posible cargar las evaluaciones."
            );
        }

        evaluaciones = data.data?.items ?? [];
        renderizarEvaluaciones();
    } catch (error) {
        console.error(
            "Error al cargar evaluaciones:",
            error
        );

        evaluaciones = [];
        renderizarEvaluaciones();

        elementos.resultadoTexto.textContent =
            "No fue posible cargar las evaluaciones.";
    }
}
document.querySelectorAll("[data-cerrar-modal]").forEach(
    (elemento) => {
        elemento.addEventListener(
            "click",
            cerrarDetalle
        );
    }
);
document.addEventListener("keydown", (evento) => {
    if (
        evento.key === "Escape" &&
        !elementos.modal.hidden
    ) {
        cerrarDetalle();
    }
});
cargarEvaluaciones();