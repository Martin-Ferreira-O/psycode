export const AUDIT_URL = "/api/v1/audit-events";
export const AUDIT_PAGE_SIZE = 20;

export const auditActions = {
    "alerts.register": ["Registro de alerta", "Registro de la generación de una nueva alerta en el sistema."],
    "alerts.evaluate": ["Evaluación", "Registro de una revisión realizada por un usuario sobre una alerta."],
    "notifications.send": ["Notificación", "Intento de envío a un destinatario mediante un canal configurado."],
    "notifications.result": ["Resumen de notificación", "Resultado general del proceso de notificación, incluidos sus envíos de respaldo."],
    "analysis.speechmatics": ["Speechmatics", "Evento técnico del proceso de transcripción de audio con Speechmatics."],
    "analysis.jev": ["JEV", "Evento técnico del análisis del contenido procesado por JEV."],
    "alerts.flow": ["Flujo de alerta", "Registro de una etapa del procesamiento de una alerta."],
    "storage.cleanup": ["Limpieza de almacenamiento", "Limpieza de material de procesamiento, espacio liberado y fallos."],
};

export const outcomes = {
    success: { text: "Exitoso", tone: "success", icon: "check" },
    failure: { text: "Fallido", tone: "danger", icon: "warning" },
    skipped: { text: "Omitido", tone: "warning", icon: "remove" },
};

export const auditErrorMessages = {
    400: "Revisa los filtros ingresados e intenta nuevamente.",
    401: "Tu sesión expiró. Inicia sesión nuevamente.",
    403: "La bitácora está disponible únicamente para administradores.",
    503: "La bitácora no está disponible temporalmente. Intenta nuevamente.",
};

const notificationOutcomes = {
    EXITO_TOTAL: "Éxito total",
    FALLO_PARCIAL: "Fallo parcial",
    FALLO_TOTAL: "Fallo total",
    SIN_DESTINATARIOS_VALIDOS: "Sin destinatarios válidos",
};
const notificationPhases = { principal: "Envío principal", respaldo: "Envío de respaldo", resumen: "Resumen" };
const notificationModes = { lista_distribucion: "Lista de distribución", supervisores_activos: "Supervisores activos" };
const notificationReasons = {
    FALLO_PARCIAL: "Fallo parcial del envío principal",
    FALLO_TOTAL: "Fallo total del envío principal",
    SIN_DESTINATARIOS_VALIDOS: "Sin destinatarios principales válidos",
};

export const defaultAuditFilters = { alert: "", action: "", outcome: "", order: "desc" };

export function toDateInput(date) {
    return date.toISOString().slice(0, 10);
}

export function fromDateInput(value) {
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(date.getTime()) ? null : date;
}

export function todayInChile() {
    const parts = new Intl.DateTimeFormat("es-CL", {
        timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date());
    const { year, month, day } = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    // UTC represents a calendar date so week navigation is independent of daylight saving time.
    return fromDateInput(`${year}-${month}-${day}`);
}

export function addDays(date, days) {
    const result = new Date(date);
    result.setUTCDate(result.getUTCDate() + days);
    return result;
}

export function weekOf(date) {
    const daysSinceMonday = (date.getUTCDay() + 6) % 7;
    const start = addDays(date, -daysSinceMonday);
    return { start, end: addDays(start, 6) };
}

export function auditQuery(date, filters) {
    const params = new URLSearchParams({
        semana_desde: toDateInput(weekOf(date).start),
        order: filters.order,
    });
    if (filters.alert.trim()) params.set("alerta_id", filters.alert.trim());
    if (filters.action) params.set("action", filters.action);
    if (filters.outcome) params.set("outcome", filters.outcome);
    return params.toString();
}

export function formatWeek(date) {
    const { start, end } = weekOf(date);
    const formatter = new Intl.DateTimeFormat("es-CL", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
    return `Semana del ${formatter.format(start)} al ${formatter.format(end)}`;
}

export function auditTime(value, options = {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
}) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", ...options }).format(date);
}

export function actionText(action) {
    return auditActions[action]?.[0] || action || "—";
}

export function outcomeText(event) {
    return notificationOutcomes[event.notification?.status] || outcomes[event.outcome]?.text || event.outcome || "—";
}

export function channelText(channel) {
    return { email: "Correo", teams: "Teams" }[channel] || "—";
}

export function actorText(event) {
    if (!event.actor_id) return "Sistema";
    return typeof event.actor === "string" && event.actor.trim() ? event.actor : `Usuario (${event.actor_id})`;
}

export function shortId(id) {
    return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

function deliveryCounts(successes, failures) {
    if (!Number.isFinite(successes) || !Number.isFinite(failures)) return "Conteos no registrados";
    return `${successes} ${successes === 1 ? "éxito" : "éxitos"} · ${failures} ${failures === 1 ? "fallo" : "fallos"}`;
}

export function notificationDetails(notification) {
    const details = [
        ["ID de notificación", notification.id],
        ["Modalidad principal", notificationModes[notification.mode] || "No registrada"],
        ["Etapa", notificationPhases[notification.phase] || "—"],
        ["Motivo", notificationReasons[notification.reason] || "No registrado"],
    ];
    if (notification.attempt !== undefined) details.push(["Número de intento", notification.attempt]);
    if (notification.phase === "resumen") {
        details.push(
            ["Envíos principales", deliveryCounts(notification.primary_successes, notification.primary_failures)],
            ["Envíos de respaldo", deliveryCounts(notification.backup_successes, notification.backup_failures)],
        );
    }
    return details;
}
