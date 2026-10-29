function nivelPresentacion(alerta) {
    const niveles = {
        BAJO: { numero: 1, texto: "Bajo", clase: "nivel-bajo" },
        MEDIO: { numero: 2, texto: "Medio", clase: "nivel-medio" },
        ALTO: { numero: 3, texto: "Alto", clase: "nivel-alto" },
    };
    const valor = alerta?.nivel_severidad;
    const numero = typeof valor === "number" ? valor
        : typeof valor === "string" && /^[123]$/.test(valor.trim()) ? Number(valor.trim()) : null;
    const codigo = { 1: "BAJO", 2: "MEDIO", 3: "ALTO" }[numero];
    if (codigo) return niveles[codigo];
    const nombre = typeof valor === "string" ? valor.trim().toUpperCase() : "";
    const semaforo = typeof alerta?.semaforo === "string" ? alerta.semaforo.trim().toUpperCase() : "";
    if (Object.hasOwn(niveles, nombre)) return niveles[nombre];
    if (Object.hasOwn(niveles, semaforo)) return niveles[semaforo];
    return { numero: null, texto: "Sin nivel", clase: "nivel-desconocido" };
}

function mostrarNivel(elemento, alerta) {
    const nivel = nivelPresentacion(alerta);
    elemento.textContent = nivel.texto;
    elemento.className = `etiqueta-nivel ${nivel.clase}`;
    elemento.setAttribute("aria-label", nivel.numero ? `Nivel ${nivel.numero}: ${nivel.texto}` : nivel.texto);
}

function mostrarTranscripcion(alerta) {
    const contenido = typeof alerta?.descripcion === "string" ? alerta.descripcion : "";
    document.querySelector("#detalleTranscripcion").textContent = contenido.trim()
        ? contenido
        : "Esta alerta no tiene un fragmento de transcripción disponible.";
    document.querySelector("#seccionTranscripcion").hidden = false;
}

function limpiarTranscripcion() {
    document.querySelector("#detalleTranscripcion").textContent = "";
    document.querySelector("#seccionTranscripcion").hidden = true;
}

function completarContenidoDetalle(alerta) {
    const modal = document.querySelector("#modalDetalle");

    modal
        .querySelectorAll(".detalle-grid")
        .forEach((bloque) => {
            bloque.hidden = false;
        });

    document.querySelector("#tituloModal").textContent =
        codigoAlertaVisible(alerta.alerta_id);

    document.querySelector("#detalleBox").textContent =
        formatearBox(alerta.box);

    document.querySelector("#detalleTipo").textContent =
        formatearTipoRiesgo(alerta.tipo_riesgo);

    mostrarNivel(
        document.querySelector("#detalleNivel"),
        alerta
    );

    document.querySelector("#detalleFecha").textContent =
        alerta.fecha_hora
            ? `${formatearFecha(alerta.fecha_hora)} · ${formatearHora(alerta.fecha_hora)}`
            : "No disponible";

    document.querySelector("#detalleEstado").textContent =
        alerta.estado_evaluacion === "pendiente"
            ? "Pendiente"
            : obtenerEtiquetaEvaluacion(
                  alerta.estado_evaluacion
              );

    document.querySelector("#detalleSesion").textContent =
        alerta.sesion_id || "—";

    mostrarTranscripcion(alerta);

    const evaluacion = alerta.evaluacion;

    const resultado =
        evaluacion?.evaluacion ??
        evaluacion?.resultado ??
        alerta.estado_evaluacion;

    document.querySelector(
        "#resultadoEvaluacion"
    ).textContent =
        resultado
            ? obtenerEtiquetaEvaluacion(resultado)
            : "No disponible";

    document.querySelector(
        "#evaluadoPor"
    ).textContent =
        evaluacion?.usuario || "No disponible";

    document.querySelector(
        "#fechaEvaluacion"
    ).textContent =
        evaluacion?.fecha_hora
            ? `${formatearFecha(evaluacion.fecha_hora)} · ${formatearHora(evaluacion.fecha_hora)}`
            : "No disponible";
}
