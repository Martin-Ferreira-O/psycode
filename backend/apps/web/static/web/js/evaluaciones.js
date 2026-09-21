const evaluaciones = [
    {
        alerta_id: "ALT-2026-084",
        box: "box-1",
        tipo_riesgo: "riesgo_suicida",
        nivel_severidad: 3,
        fecha_hora: "2026-09-08T14:37:00",

        evaluacion: {
            resultado: "correcta",
            usuario: "autonoma",
            fecha_hora: "2026-09-20T22:35:00",
        },
    },
    {
        alerta_id: "ALT-2026-083",
        box: "box-2",
        tipo_riesgo: "vulneracion_derechos",
        nivel_severidad: 2,
        fecha_hora: "2026-09-08T13:12:00",

        evaluacion: {
            resultado: "falso_positivo",
            usuario: "autonoma",
            fecha_hora: "2026-09-08T13:20:00",
        },
    },
    {
        alerta_id: "ALT-2026-082",
        box: "box-3",
        tipo_riesgo: "riesgo_suicida",
        nivel_severidad: 1,
        fecha_hora: "2026-09-08T11:48:00",

        evaluacion: {
            resultado: "neutro",
            usuario: "autonoma",
            fecha_hora: "2026-09-08T12:00:00",
        },
    },
    {
        alerta_id: "ALT-2026-081",
        box: "box-4",
        tipo_riesgo: "vulneracion_derechos",
        nivel_severidad: 3,
        fecha_hora: "2026-09-08T10:25:00",

        evaluacion: {
            resultado: "correcta",
            usuario: "autonoma",
            fecha_hora: "2026-09-08T10:40:00",
        },
    },
    {
        alerta_id: "ALT-2026-080",
        box: "box-5",
        tipo_riesgo: "riesgo_suicida",
        nivel_severidad: 2,
        fecha_hora: "2026-09-08T09:16:00",

        evaluacion: {
            resultado: "correcta",
            usuario: "autonoma",
            fecha_hora: "2026-09-08T09:30:00",
        },
    },
];

const etiquetas = {
    riesgo_suicida: "Riesgo suicida",
    vulneracion_derechos: "Vulneración de derechos",

    correcta: "Correcta",
    falso_positivo: "Falso positivo",
    neutro: "Neutro",
};

const elementos = {
    tabla: document.querySelector("#tablaEvaluaciones"),

    resultadoTexto: document.querySelector(
        "#resultadoEvaluaciones"
    ),

    estadoVacio: document.querySelector(
        "#estadoVacioEvaluaciones"
    ),

    tablaContenedor: document.querySelector(
        "#tablaEvaluacionesContenedor"
    ),

    modal: document.querySelector("#modalDetalle"),

    tituloModal: document.querySelector("#tituloModal"),

    detalleBox: document.querySelector("#detalleBox"),
    detalleTipo: document.querySelector("#detalleTipo"),
    detalleNivel: document.querySelector("#detalleNivel"),
    detalleFecha: document.querySelector("#detalleFecha"),
    detalleHora: document.querySelector("#detalleHora"),
    detalleEstado: document.querySelector("#detalleEstado"),

    resultadoEvaluacion: document.querySelector(
        "#resultadoEvaluacion"
    ),

    evaluadoPor: document.querySelector("#evaluadoPor"),

    fechaEvaluacion: document.querySelector(
        "#fechaEvaluacion"
    ),
};

function formatearBox(box) {
    if (!box) {
        return "—";
    }

    const numero = box.split("-")[1];

    return `Box ${String(numero).padStart(2, "0")}`;
}


function etiquetaNivel(nivel) {
    return {
        1: "Baja",
        2: "Media",
        3: "Alta",
    }[nivel] || "—";
}


function formatearFecha(fecha) {
    if (!fecha) {
        return "—";
    }

    return new Intl.DateTimeFormat("es-CL", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    }).format(new Date(fecha));
}


function formatearHora(fecha) {
    if (!fecha) {
        return "—";
    }

    return new Intl.DateTimeFormat("es-CL", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    }).format(new Date(fecha));
}

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
        return;
    }

    elementos.estadoVacio.hidden = true;
    elementos.tablaContenedor.hidden = false;


    elementos.tabla.innerHTML = evaluaciones
        .map((alerta) => {

            const resultado = alerta.evaluacion.resultado;

            return `
                <tr>

                    <td>
                        <strong>
                            ${alerta.alerta_id}
                        </strong>
                    </td>

                    <td>
                        <span class="etiqueta-evaluacion">
                            ${etiquetas[resultado]}
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
                                ${formatearFecha(
                                    alerta.evaluacion.fecha_hora
                                )}
                            </span>

                            <small>
                                ${formatearHora(
                                    alerta.evaluacion.fecha_hora
                                )}
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

    document
        .querySelectorAll(".boton-ver-detalle")
        .forEach((boton) => {

            boton.addEventListener("click", () => {

                abrirDetalle(
                    boton.dataset.alerta
                );

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

    elementos.tituloModal.textContent =
        alerta.alerta_id;

    elementos.detalleBox.textContent =
        formatearBox(alerta.box);


    elementos.detalleTipo.textContent =
        etiquetas[alerta.tipo_riesgo] || "—";


    elementos.detalleNivel.textContent =
        etiquetaNivel(alerta.nivel_severidad);


    elementos.detalleFecha.textContent =
        formatearFecha(alerta.fecha_hora);


    elementos.detalleHora.textContent =
        formatearHora(alerta.fecha_hora);


    elementos.detalleEstado.textContent =
        "Revisada";
    
    elementos.resultadoEvaluacion.textContent =
        etiquetas[alerta.evaluacion.resultado] || "—";


    elementos.evaluadoPor.textContent =
        alerta.evaluacion.usuario || "—";


    elementos.fechaEvaluacion.textContent =
        `${formatearFecha(
            alerta.evaluacion.fecha_hora
        )} · ${formatearHora(
            alerta.evaluacion.fecha_hora
        )}`;

    elementos.modal.hidden = false;

    document.body.classList.add(
        "modal-abierto"
    );


    const botonCerrar =
        elementos.modal.querySelector(
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

renderizarEvaluaciones();