const etiquetasEvaluacion = {
    correcta: "Correcta",
    falso_positivo: "Falso positivo",
    neutro: "Neutro",
};


function formatearBox(box) {
    if (!box) {
        return "—";
    }

    const partes = box.split("-");
    const numero = partes[1];

    if (!numero) {
        return box;
    }

    return `Box ${String(numero).padStart(2, "0")}`;
}


function formatearTipoRiesgo(tipoRiesgo) {
    if (!tipoRiesgo) {
        return "—";
    }

    return tipoRiesgo
        .replaceAll("_", " ")
        .replace(
            /^./,
            (letra) => letra.toUpperCase()
        );
}


function formatearFecha(fecha) {
    if (!fecha) {
        return "—";
    }

    const fechaObjeto = new Date(fecha);

    if (Number.isNaN(fechaObjeto.getTime())) {
        return "—";
    }

    return new Intl.DateTimeFormat("es-CL", {
        timeZone: "America/Santiago",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    }).format(fechaObjeto);
}


function formatearHora(fecha) {
    if (!fecha) {
        return "—";
    }

    const fechaObjeto = new Date(fecha);

    if (Number.isNaN(fechaObjeto.getTime())) {
        return "—";
    }

    return new Intl.DateTimeFormat("es-CL", {
        timeZone: "America/Santiago",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    }).format(fechaObjeto);
}


function etiquetaNivel(alerta) {
    if (
        !alerta ||
        alerta.nivel_severidad === null ||
        alerta.nivel_severidad === undefined
    ) {
        return "—";
    }

    if (alerta.semaforo) {
        return `${alerta.nivel_severidad} · ${alerta.semaforo}`;
    }

    return String(alerta.nivel_severidad);
}


function obtenerResultado(alerta) {
    return (
        alerta?.evaluacion?.evaluacion ||
        alerta?.estado_evaluacion ||
        null
    );
}


function obtenerEtiquetaEvaluacion(resultado) {
    return etiquetasEvaluacion[resultado] || "—";
}