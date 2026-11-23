import { ErrorSolicitud, apiGetDatos, apiRequest, solicitarJson } from "../api.js";

export const ALERTS_URL = "/api/v1/alerts";
export const ALERT_PAGE_SIZE = 10;

export async function getAlertCount(query, signal) {
    const params = new URLSearchParams(query);
    params.set("limit", "1");
    params.set("offset", "0");
    const data = await apiGetDatos(`${ALERTS_URL}?${params}`, { cache: "no-store", signal });
    if (!Number.isInteger(data?.total) || data.total < 0) throw new ErrorSolicitud();
    return data.total;
}

export const evaluationChoices = {
    correcta: "La detección corresponde a una alerta real.",
    falso_positivo: "La detección corresponde a un error del modelo.",
    neutro: "No es posible confirmar la detección.",
};

const levels = {
    BAJO: { number: 1, text: "Bajo", tone: "success" },
    MEDIO: { number: 2, text: "Medio", tone: "warning" },
    ALTO: { number: 3, text: "Alto", tone: "danger" },
};

export function alertLevel(alert) {
    const value = String(alert?.nivel_severidad ?? "").trim().toUpperCase();
    const severity = { 1: "BAJO", 2: "MEDIO", 3: "ALTO" }[value] ?? value;
    const indicator = String(alert?.semaforo ?? "").trim().toUpperCase();
    return levels[severity] || levels[indicator] || { text: "Sin nivel", tone: "neutral" };
}

export function alertUrl(id) {
    return `${ALERTS_URL}/${encodeURIComponent(id)}`;
}

export async function saveEvaluation(id, option) {
    const url = `${alertUrl(id)}/evaluacion`;
    try {
        const evaluation = await solicitarJson(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ evaluacion: option }),
        }, apiRequest);
        return { evaluation: validateEvaluation(id, evaluation), conflict: false };
    } catch (error) {
        if (error.estado !== 409) throw error;
        try {
            const evaluation = await apiGetDatos(url);
            return { evaluation: validateEvaluation(id, evaluation), conflict: true };
        } catch (lookupError) {
            // The server confirmed that the alert has already been reviewed.
            lookupError.evaluationConflict = true;
            throw lookupError;
        }
    }
}

function validateEvaluation(id, evaluation) {
    if (
        evaluation?.alerta_id !== id ||
        !Object.hasOwn(evaluationChoices, evaluation.evaluacion) ||
        evaluation.estado_evaluacion !== evaluation.evaluacion ||
        typeof evaluation.usuario !== "string" ||
        !evaluation.fecha_hora
    ) {
        throw new ErrorSolicitud();
    }
    return evaluation;
}

export function withEvaluation(alert, evaluation) {
    return evaluation
        ? { ...alert, evaluacion: evaluation, estado_evaluacion: evaluation.estado_evaluacion }
        : alert;
}
