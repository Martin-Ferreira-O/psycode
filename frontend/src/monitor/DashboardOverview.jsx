import { useState } from "react";
import { apiGetDatos, ErrorSolicitud } from "../api.js";
import { Skeleton } from "../ui.jsx";
import { ALERTS_URL } from "./alerts.js";
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
                        <button
                            key={key}
                            type="button"
                            className={`resumen-alertas-${key}`}
                            data-active={activeStatus === key}
                            aria-pressed={selectedStatus === key}
                            {...interactions(key)}
                        >
                            <span className="resumen-alertas-muestra" aria-hidden="true" />
                            <span>{label}</span>
                            <strong>{numberFormatter.format(totals[key])}</strong>
                        </button>
                    ))}
                </div>
            )}
            {!totals && summary.error && (
                <p className="resumen-alertas-error" role="status">No se pudieron cargar los indicadores.</p>
            )}
        </div>
    );
}

async function getAlertCount(query, signal) {
    const params = new URLSearchParams(query);
    params.set("limit", "1");
    params.set("offset", "0");
    const data = await apiGetDatos(`${ALERTS_URL}?${params}`, { signal });
    if (!Number.isInteger(data?.total) || data.total < 0) throw new ErrorSolicitud();
    return data.total;
}

async function loadSummary(signal) {
    const [pendientes, revisadas] = await Promise.all([
        getAlertCount({ revisadas: "false" }, signal),
        getAlertCount({ revisadas: "true" }, signal),
    ]);
    return { pendientes, revisadas, total: pendientes + revisadas };
}

function getMonthlyPeriods() {
    const currentMonth = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Santiago",
        year: "numeric",
        month: "2-digit",
    }).formatToParts(new Date());
    const { year, month } = Object.fromEntries(currentMonth.map(({ type, value }) => [type, value]));
    const formatMonth = new Intl.DateTimeFormat("es-CL", { month: "short", timeZone: "UTC" });

    return Array.from({ length: 6 }, (_, index) => {
        const start = new Date(Date.UTC(Number(year), Number(month) - 6 + index, 1));
        const end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0));
        return {
            label: formatMonth.format(start).replace(".", "").replace(/^./, (letter) => letter.toUpperCase()),
            start: start.toISOString().slice(0, 10),
            end: end.toISOString().slice(0, 10),
        };
    });
}

function loadChart(signal) {
    return Promise.all(getMonthlyPeriods().map(async (period) => ({
        ...period,
        total: await getAlertCount({ fecha_desde: period.start, fecha_hasta: period.end }, signal),
    })));
}

export function useDashboardOverview() {
    const summary = useResource(loadSummary);
    const chart = useResource(loadChart);
    return {
        summary,
        chart,
        refresh() {
            summary.reload();
            chart.reload();
        },
    };
}

export default function DashboardOverview({ summary, chart }) {
    const maximum = Math.max(1, ...(chart.data ?? []).map(({ total }) => total));

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
            <article className="panel-grafico-dashboard">
                <header className="cabecera-grafico-dashboard">
                    <div>
                        <div className="titulo-grafico-con-ayuda">
                            <h2 id="tituloGrafico">Comportamiento mensual</h2>
                            <span className="ayuda-contextual" tabIndex={0} data-tooltip="Muestra cuántas alertas fueron registradas durante el período seleccionado." aria-label="Información sobre el gráfico">i</span>
                        </div>
                        <p>Cantidad de alertas registradas por período.</p>
                    </div>
                </header>
                <div id="graficoBarras" className="grafico-dashboard" aria-label="Gráfico de cantidad de alertas registradas" aria-busy={chart.loading}>
                    {chart.loading && [42, 66, 52, 79, 57, 71].map((height) => (
                        <div key={height} className="grupo-barra-dashboard" aria-hidden="true">
                            <div className="contenedor-barra-dashboard">
                                <span className="ui-skeleton ui-skeleton-bar" style={{ height: `${height}%` }} />
                            </div>
                            <Skeleton />
                        </div>
                    ))}
                    {chart.error && <div className="grafico-cargando" role="status">No se pudo cargar el gráfico.</div>}
                    {chart.data?.map(({ start, label, total }) => (
                        <div key={start} className="grupo-barra-dashboard" role="img" aria-label={`${label}: ${total} ${total === 1 ? "alerta" : "alertas"}`}>
                            <span className="valor-barra-dashboard">{total}</span>
                            <div className="contenedor-barra-dashboard">
                                <div
                                    className="barra-dashboard"
                                    style={{ height: `${total === 0 ? 4 : Math.max(12, Math.round(total / maximum * 100))}%` }}
                                    title={`${label}: ${total} ${total === 1 ? "alerta" : "alertas"}`}
                                />
                            </div>
                            <span className="etiqueta-barra-dashboard">{label}</span>
                        </div>
                    ))}
                </div>
            </article>
        </section>
    );
}
