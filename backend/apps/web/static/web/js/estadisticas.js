const datos = {
    semana: [
        { etiqueta: "Lun", total: 3 },
        { etiqueta: "Mar", total: 5 },
        { etiqueta: "Mié", total: 4 },
        { etiqueta: "Jue", total: 7 },
        { etiqueta: "Vie", total: 5 },
        { etiqueta: "Sáb", total: 2 },
        { etiqueta: "Dom", total: 1 },
    ],

    mes: [
        { etiqueta: "Sem 1", total: 15 },
        { etiqueta: "Sem 2", total: 22 },
        { etiqueta: "Sem 3", total: 18 },
        { etiqueta: "Sem 4", total: 27 },
    ],
};

const registros = [
    {
        id: "ALT-2026-084",
        tipo: "Riesgo suicida",
        fecha: "08 sep 2026",
        hora: "14:37",
        estado: "Pendiente",
    },
    {
        id: "ALT-2026-083",
        tipo: "Vulneración de derechos",
        fecha: "08 sep 2026",
        hora: "13:12",
        estado: "Pendiente",
    },
    {
        id: "ALT-2026-082",
        tipo: "Riesgo suicida",
        fecha: "08 sep 2026",
        hora: "11:48",
        estado: "Revisada",
    },
    {
        id: "ALT-2026-081",
        tipo: "Vulneración de derechos",
        fecha: "08 sep 2026",
        hora: "10:25",
        estado: "Revisada",
    },
];

let periodoActual = "semana";

const grafico = document.querySelector("#graficoBarras");
const registroHistorico = document.querySelector("#registroHistorico");
const tituloGrafico = document.querySelector("#tituloGrafico");
const botonDescargar = document.querySelector("#botonDescargar");
const botonesPeriodo = document.querySelectorAll(".boton-periodo");

function dibujarGrafico() {
    const valores = datos[periodoActual];
    const maximo = Math.max(...valores.map((item) => item.total));

    grafico.innerHTML = valores
        .map((item) => {
            const altura = (item.total / maximo) * 215;

            return `
                <div class="grupo-barra">
                    <span class="valor-barra">${item.total}</span>
                    <div
                        class="barra"
                        style="height: ${altura}px"
                        title="${item.etiqueta}: ${item.total} alertas"
                    ></div>
                    <span class="etiqueta-barra">${item.etiqueta}</span>
                </div>
            `;
        })
        .join("");
}

function mostrarRegistros() {
    registroHistorico.innerHTML = registros
        .map((alerta) => {
            const claseEstado =
                alerta.estado === "Revisada" ? "estado revisada" : "estado";

            return `
                <article class="registro">
                    <div class="registro-contenido">
                        <span class="registro-icono">!</span>

                        <div>
                            <span class="registro-id">${alerta.id}</span>
                            <span class="registro-tipo">${alerta.tipo}</span>
                            <span class="registro-fecha">
                                ${alerta.fecha} · ${alerta.hora}
                            </span>
                        </div>
                    </div>

                    <span class="${claseEstado}">${alerta.estado}</span>
                </article>
            `;
        })
        .join("");
}

function cambiarPeriodo(nuevoPeriodo) {
    periodoActual = nuevoPeriodo;

    botonesPeriodo.forEach((boton) => {
        boton.classList.toggle(
            "activo",
            boton.dataset.periodo === periodoActual
        );
    });

    tituloGrafico.textContent =
        periodoActual === "semana"
            ? "Comportamiento semanal"
            : "Comportamiento mensual";

    botonDescargar.textContent =
        periodoActual === "semana"
            ? " Obtener registro de semana"
            : " Obtener registro de mes";

    dibujarGrafico();
}

function descargarRegistro() {
    const encabezado = "ID,Tipo,Fecha,Hora,Estado";

    const filas = registros.map((alerta) =>
        [
            alerta.id,
            alerta.tipo,
            alerta.fecha,
            alerta.hora,
            alerta.estado,
        ].join(",")
    );

    const contenido = [encabezado, ...filas].join("\n");
    const archivo = new Blob(["\uFEFF" + contenido], {
        type: "text/csv;charset=utf-8",
    });

    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(archivo);
    enlace.download = `registro-alertas-${periodoActual}.csv`;
    enlace.click();

    URL.revokeObjectURL(enlace.href);
}

botonesPeriodo.forEach((boton) => {
    boton.addEventListener("click", () => {
        cambiarPeriodo(boton.dataset.periodo);
    });
});

botonDescargar.addEventListener("click", descargarRegistro);

mostrarRegistros();
dibujarGrafico();
