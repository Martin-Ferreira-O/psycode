const etiquetasEvaluacion = {
    correcta: "Correcta",
    falso_positivo: "Falso positivo",
    neutro: "Neutro",
};

const codigosAlerta = {
    "11111111-1111-4111-8111-111111111111": "ALT-2026-080",
    "11111111-1111-4111-8111-111111111112": "ALT-2026-081",
    "11111111-1111-4111-8111-111111111113": "ALT-2026-082",
    "11111111-1111-4111-8111-111111111114": "ALT-2026-083",
    "11111111-1111-4111-8111-111111111115": "ALT-2026-084",
    "44444444-4444-4444-8444-444444444444": "ALT-2026-085",
    "66666666-6666-4666-8666-666666666666": "ALT-2026-086",
};

const etiquetasTipoRiesgo = {
    riesgo_suicida: "Riesgo suicida",
    sin_ideacion_identificable: "Riesgo suicida",
    deseo_pasivo_de_muerte: "Riesgo suicida",
    ideacion_activa: "Riesgo suicida",
    consideracion_de_metodo: "Riesgo suicida",
    conducta_suicida: "Riesgo suicida",
    vulneracion_derechos: "Vulneración de derechos",
};

const etiquetasSemaforo = {
    NULO: "Nulo",
    BAJO: "Bajo",
    MEDIO: "Media",
    ALTO: "Alta",
};

const mesesCortos = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function codigoAlertaVisible(alertaId) {
    return codigosAlerta[alertaId] || alertaId;
}

function formatearBox(box) {
    if (!box) return "—";
    const numero = box.split("-")[1];
    return numero ? `Box ${String(numero).padStart(2, "0")}` : box;
}

function formatearTipoRiesgo(tipoRiesgo) {
    if (!tipoRiesgo) return "—";
    return etiquetasTipoRiesgo[tipoRiesgo] || tipoRiesgo
        .replaceAll("_", " ")
        .replace(/^./, (letra) => letra.toUpperCase());
}

function formatearFecha(fecha) {
    if (!fecha) return "—";
    const fechaObjeto = new Date(fecha);
    if (Number.isNaN(fechaObjeto.getTime())) return "—";
    return new Intl.DateTimeFormat("es-CL", {
        timeZone: "America/Santiago",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    }).format(fechaObjeto);
}

function formatearFechaBreve(fecha) {
    if (!fecha) return "—";
    const partes = new Intl.DateTimeFormat("es-CL", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        timeZone: "America/Santiago",
    }).formatToParts(new Date(fecha));
    const dia = partes.find((parte) => parte.type === "day")?.value;
    const mes = Number(partes.find((parte) => parte.type === "month")?.value);
    const anio = partes.find((parte) => parte.type === "year")?.value;
    return `${dia} ${mesesCortos[mes - 1]} ${anio}`;
}

function formatearHora(fecha) {
    if (!fecha) return "—";
    const fechaObjeto = new Date(fecha);
    if (Number.isNaN(fechaObjeto.getTime())) return "—";
    return new Intl.DateTimeFormat("es-CL", {
        timeZone: "America/Santiago",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    }).format(fechaObjeto);
}

function etiquetaNivel(alerta) {
    if (!alerta || alerta.nivel_severidad === null || alerta.nivel_severidad === undefined) {
        return "—";
    }
    return alerta.semaforo
        ? `${alerta.nivel_severidad} · ${alerta.semaforo}`
        : String(alerta.nivel_severidad);
}

function nivelVisual(alerta) {
    return etiquetasSemaforo[alerta?.semaforo] || "—";
}

function obtenerResultado(alerta) {
    return alerta?.evaluacion?.evaluacion || alerta?.estado_evaluacion || null;
}

function obtenerEtiquetaEvaluacion(resultado) {
    return etiquetasEvaluacion[resultado] || "—";
}
