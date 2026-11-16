import { useEffect, useEffectEvent, useState } from "react";
import { apiGetDatos, ErrorSolicitud } from "../api.js";
import { ALERTS_URL } from "./alerts.js";

const checkInterval = 15_000;
const refreshDelay = 1_500;

function latestRecord(data) {
    const alert = data?.items?.[0];
    const timestamp = Date.parse(alert?.fecha_hora);
    if (!Number.isInteger(data?.total) || data.total < 0 || !Array.isArray(data.items)
        || (data.total > 0 && (typeof alert?.alerta_id !== "string" || !Number.isFinite(timestamp)))) {
        throw new ErrorSolicitud();
    }
    return { total: data.total, id: alert?.alerta_id, timestamp };
}

function hasNewRecord(previous, current) {
    // Un registro histórico puede entrar tras ser evaluado sin cambiar la primera fila.
    if (current.total > previous.total) return true;
    // El servidor ordena por detección descendente e identificador ascendente.
    return current.id !== previous.id && (current.timestamp > previous.timestamp
        || (current.timestamp === previous.timestamp && current.id < previous.id));
}

export function useEvaluationUpdates({ enabled, paused, refresh }) {
    const [notice, setNotice] = useState(null);
    const [checkFailed, setCheckFailed] = useState(false);
    const canCheck = useEffectEvent(() => !paused && !document.hidden);
    const refreshList = useEffectEvent(() => refresh());

    useEffect(() => {
        if (!enabled) return;
        let previous = null;
        let controller;
        let announcement;
        let noticeId = 0;

        async function check() {
            if (controller || announcement || !canCheck()) return;
            controller = new AbortController();
            const { signal } = controller;
            const deadline = window.setTimeout(() => controller.abort(), 8_000);
            try {
                const data = await apiGetDatos(`${ALERTS_URL}?registro_evaluaciones=true&limit=1`, {
                    cache: "no-store", signal,
                });
                if (signal.aborted || !canCheck()) return;
                const current = latestRecord(data);
                setCheckFailed(false);
                if (previous && hasNewRecord(previous, current)) {
                    setNotice({ id: ++noticeId, pending: true });
                    announcement = window.setTimeout(() => {
                        announcement = undefined;
                        refreshList();
                        setNotice(current => current && { ...current, pending: false });
                    }, refreshDelay);
                }
                previous = current;
            } catch {
                if (controller && canCheck()) setCheckFailed(true);
            } finally {
                window.clearTimeout(deadline);
                controller = undefined;
            }
        }

        const interval = window.setInterval(check, checkInterval);
        document.addEventListener("visibilitychange", check);
        void check();
        return () => {
            window.clearInterval(interval);
            window.clearTimeout(announcement);
            controller?.abort();
            controller = undefined;
            document.removeEventListener("visibilitychange", check);
        };
    }, [enabled]);

    return { notice, checkFailed, dismissNotice: () => setNotice(null) };
}
