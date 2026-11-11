import { apiGetDatos, ErrorSolicitud } from "../api.js";
import { ALERTS_URL } from "./alerts.js";
import { useResource } from "./resources.js";

const numberFormatter = new Intl.NumberFormat("es-CL");
const cardTypes = [
    { key: "total", label: "Alertas registradas", description: "Total acumulado", tooltip: "Cantidad total de alertas registradas en el sistema." },
    { key: "pendientes", label: "Pendientes", description: "Por revisar", tooltip: "Alertas que aún requieren revisión o evaluación." },
    { key: "revisadas", label: "Revisadas", description: "Evaluadas", tooltip: "Alertas que ya fueron revisadas por un profesional." },
];

function IndicatorIcon({ kind }) {
    return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
            {kind === "total" ? <path d="M12 3 2.8 19h18.4L12 3Zm0 6v4m0 3.5h.01" /> : (
                <>
                    <circle cx="12" cy="12" r="9" />
                    {kind === "pendientes" ? <path d="M12 7v5l3 2" /> : <path d="m8 12 2.5 2.5L16 9" />}
                </>
            )}
        </svg>
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
    const totals = summary.data ?? summary.previousData;
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
                    <span className="ayuda-contextual" tabIndex={0} data-tooltip="Estos indicadores muestran el total de alertas registradas, pendientes y revisadas." aria-label="Información sobre los indicadores principales">i</span>
                </div>
                <div className="tarjetas-resumen" aria-busy={summary.loading}>
                    {cardTypes.map(({ key, label, description, tooltip }) => (
                        <article key={key} className={`tarjeta-resumen tarjeta-${key}`} data-tooltip={tooltip}>
                            <div className={`tarjeta-icono tarjeta-icono-${key}`}><IndicatorIcon kind={key} /></div>
                            <div className="tarjeta-resumen-datos">
                                <span className="resumen-etiqueta">{label}</span>
                                <strong id={`total${key === "total" ? "Alertas" : key[0].toUpperCase() + key.slice(1)}`} className="resumen-numero">
                                    {totals ? numberFormatter.format(totals[key]) : "—"}
                                </strong>
                                <span className="resumen-descripcion">{description}</span>
                            </div>
                        </article>
                    ))}
                </div>
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
                    {chart.loading && <div className="grafico-cargando" role="status">Cargando gráfico…</div>}
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
