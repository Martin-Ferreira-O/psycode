import { useState } from "react";
import { Button, Skeleton } from "../ui.jsx";
import AlertActivityChart from "./AlertActivityChart.jsx";
import { loadMonthlyActivity, loadRecentActivity } from "./alertActivity.js";
import { getAlertCount } from "./alerts.js";
import { useResource } from "./resources.js";

const numberFormatter = new Intl.NumberFormat("es-CL");
const alertStatuses = [
    { key: "pendientes", label: "Pendientes" },
    { key: "revisadas", label: "Evaluadas" },
];

function AlertStatusChart({ summary }) {
    const totals = summary.data ?? summary.previousData;
    const [selectedStatus, setSelectedStatus] = useState(null);
    const [hoveredStatus, setHoveredStatus] = useState(null);
    const activeStatus = hoveredStatus ?? selectedStatus;
    const activeLabel = alertStatuses.find(({ key }) => key === activeStatus)?.label ?? "Total de alertas";
    const evaluatedShare = totals?.total ? totals.revisadas / totals.total * 100 : 0;

    function interactions(key) {
        return {
            onPointerEnter(event) {
                if (event.pointerType !== "touch") setHoveredStatus(key);
            },
            onPointerLeave() {
                setHoveredStatus(null);
            },
            onClick() {
                setSelectedStatus(current => current === key ? null : key);
            },
        };
    }

    return (
        <div className="resumen-alertas" aria-busy={summary.loading} onKeyDown={(event) => {
            if (event.key === "Escape") {
                setHoveredStatus(null);
                setSelectedStatus(null);
            }
        }}>
            <div className="resumen-alertas-anillo">
                <svg viewBox="0 0 120 120" aria-hidden="true">
                    <circle className="resumen-alertas-fondo" cx="60" cy="60" r="49" />
                    <g transform="rotate(-90 60 60)">
                        {alertStatuses.map(({ key }) => {
                            const count = totals?.[key];
                            if (!count) return null;
                            const share = count / totals.total * 100;

                            return (
                                <circle
                                    key={key}
                                    className={`resumen-alertas-segmento resumen-alertas-${key}`}
                                    data-active={activeStatus === key}
                                    cx="60"
                                    cy="60"
                                    r="49"
                                    pathLength="100"
                                    strokeDasharray={share < 100 ? `${share} ${100 - share}` : undefined}
                                    strokeDashoffset={key === "pendientes" ? -evaluatedShare : 0}
                                    {...interactions(key)}
                                />
                            );
                        })}
                    </g>
                </svg>
                <div className="resumen-alertas-centro" aria-live="polite" aria-atomic="true">
                    <strong>
                        {totals ? numberFormatter.format(totals[activeStatus ?? "total"]) : summary.loading ? (
                            <Skeleton className="ui-skeleton-number" />
                        ) : "—"}
                    </strong>
                    <span>{activeLabel}</span>
                </div>
            </div>
            {totals && (
                <div className="resumen-alertas-leyenda" role="group" aria-label="Estados de las alertas">
                    {alertStatuses.map(({ key, label }) => (
                        <Button
                            key={key}
                            className={`resumen-alertas-${key}`}
                            data-active={activeStatus === key}
                            aria-pressed={selectedStatus === key}
                            {...interactions(key)}
                        >
                            <span className="resumen-alertas-muestra" aria-hidden="true" />
                            <span>{label}</span>
                            <strong>{numberFormatter.format(totals[key])}</strong>
                        </Button>
                    ))}
                </div>
            )}
            {!totals && summary.error && (
                <p className="resumen-alertas-error" role="status">No se pudieron cargar los indicadores.</p>
            )}
        </div>
    );
}

async function loadSummary(signal) {
    const [pendientes, revisadas] = await Promise.all([
        getAlertCount({ revisadas: "false" }, signal),
        getAlertCount({ revisadas: "true" }, signal),
    ]);
    return { pendientes, revisadas, total: pendientes + revisadas };
}

export function useDashboardOverview() {
    const summary = useResource(loadSummary);
    const recent = useResource(loadRecentActivity);
    const monthly = useResource(loadMonthlyActivity);
    return {
        summary,
        recent,
        monthly,
        refresh() {
            summary.reload();
            recent.reload();
            monthly.reload();
        },
    };
}

export default function DashboardOverview({ summary, recent, monthly }) {
    return (
        <section className="resumen-dashboard">
            <div className="panel-indicadores">
                <div className="titulo-bloque">
                    <div>
                        <span className="titulo-bloque-icono" aria-hidden="true">
                            <svg viewBox="0 0 24 24"><path d="M4 19V9m6 10V5m6 14v-7m6 7V3" /></svg>
                        </span>
                        <div>
                            <h2>Indicadores principales</h2>
                            <p>Resumen del estado actual de las alertas.</p>
                        </div>
                    </div>
                    <span className="ayuda-contextual" tabIndex={0} data-tooltip="Selecciona un segmento o usa la leyenda para consultar el conteo por estado." aria-label="Información sobre los indicadores principales">i</span>
                </div>
                <AlertStatusChart summary={summary} />
            </div>
            <AlertActivityChart recent={recent} monthly={monthly} />
        </section>
    );
}
