import { useEffect, useRef, useState } from "react";
import { Button, Icon, Skeleton, Status } from "../ui.jsx";

const periods = [
    { key: "daily", label: "Diario", unit: "Por hora · Santiago" },
    { key: "weekly", label: "Semanal", unit: "Por día" },
    { key: "monthly", label: "Mensual", unit: "Por mes" },
];
const rotationDelay = 12_000;
const number = new Intl.NumberFormat("es-CL");
const compactNumber = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 1 });
const skeletonHeights = [36, 60, 48, 78, 58, 91, 72];

function move(index, direction) {
    return (index + direction + periods.length) % periods.length;
}

function ChartPlot({ buckets, daily, total, loading, error, onRetry }) {
    const quarter = Math.max(1, ...buckets.map(bucket => bucket.total / 4));
    const magnitude = 10 ** Math.floor(Math.log10(quarter));
    const step = Math.ceil(quarter / magnitude) * magnitude;
    const ticks = [4, 3, 2, 1, 0].map(tick => tick * step);

    return (
        <div className="actividad-plot">
            <div className="actividad-escala" aria-hidden="true">
                {ticks.map(tick => <span key={tick}>{buckets.length ? compactNumber.format(tick) : ""}</span>)}
            </div>
            <div className="actividad-cuadricula" aria-hidden="true">
                {ticks.map(tick => <span key={tick} />)}
            </div>
            {loading ? (
                <div className="actividad-columnas" style={{ "--columnas": skeletonHeights.length }} aria-hidden="true">
                    {skeletonHeights.map(height => (
                        <div key={height} className="actividad-columna">
                            <span className="ui-skeleton ui-skeleton-bar" style={{ height: `${height}%` }} />
                        </div>
                    ))}
                </div>
            ) : buckets.length > 0 && (
                <>
                    <div className="actividad-columnas" style={{ "--columnas": buckets.length }} aria-hidden="true">
                        {buckets.map(({ name, total: count }) => (
                            <div key={name} className="actividad-columna" title={`${name} · ${number.format(count)} ${count === 1 ? "alerta" : "alertas"}`}>
                                {count > 0 && (
                                    <span className="actividad-barra" style={{ height: `${count / ticks[0] * 100}%` }}>
                                        {!daily && <span className="actividad-valor-barra">{compactNumber.format(count)}</span>}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                    <div className="actividad-etiquetas" style={{ "--columnas": buckets.length }} aria-hidden="true">
                        {buckets.map(({ name, label }, index) => (
                            <span key={name}>{daily ? index % 4 === 0 || index === 23 ? label.slice(0, 2) : "" : label}</span>
                        ))}
                    </div>
                </>
            )}
            {error && <Status type="error" className="actividad-mensaje" onRetry={onRetry}>No se pudieron cargar los datos del gráfico.</Status>}
            {total === 0 && <p className="actividad-mensaje" role="status">No se registraron alertas en este período.</p>}
        </div>
    );
}

export default function AlertActivityChart({ recent, monthly }) {
    const chart = useRef(null);
    const [active, setActive] = useState(0);
    const [playing, setPlaying] = useState(() => !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const [hovering, setHovering] = useState(false);
    const [focused, setFocused] = useState(false);
    const [detailsOpen, setDetailsOpen] = useState(false);
    const period = periods[active];
    const resource = period.key === "monthly" ? monthly : recent;
    const series = period.key === "monthly" ? resource.data : resource.data?.[period.key];
    const total = series?.buckets.reduce((sum, bucket) => sum + bucket.total, 0);
    const rotating = playing && !hovering && !focused && !detailsOpen && Boolean(series);

    useEffect(() => {
        if (!rotating) return;
        const timer = window.setTimeout(() => setActive(move(active, 1)), rotationDelay);
        return () => window.clearTimeout(timer);
    }, [active, rotating]);

    function select(index) {
        setActive(index);
        setPlaying(false);
    }

    function toggleRotation() {
        setDetailsOpen(false);
        setPlaying(current => !current);
    }

    function retry() {
        chart.current.focus({ preventScroll: true });
        resource.reload();
    }

    return (
        <article className="panel-grafico-dashboard" aria-labelledby="tituloGrafico" aria-roledescription="carrusel"
            onPointerEnter={event => { if (event.pointerType === "mouse") setHovering(true); }}
            onPointerLeave={() => setHovering(false)}
            onFocusCapture={() => setFocused(true)}
            onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
            <header className="cabecera-grafico-dashboard">
                <div className="actividad-titulo">
                    <span className="titulo-bloque-icono"><Icon name="bar_chart" /></span>
                    <div>
                        <h2 id="tituloGrafico">Actividad de alertas</h2>
                        <p aria-live={rotating ? "off" : "polite"} className="actividad-fecha">
                            {series?.range ?? (resource.loading ? "Cargando período…" : period.label)}
                        </p>
                    </div>
                </div>
                <Button iconOnly variant="ghost" aria-label={playing ? "Pausar rotación automática" : "Reanudar rotación automática"}
                    title={playing ? "Pausar rotación automática" : "Reanudar rotación automática"} onClick={toggleRotation}>
                    <Icon name={playing ? "pause" : "play"} />
                </Button>
            </header>
            <div className="actividad-controles">
                <div className="actividad-periodos" role="group" aria-label="Período del gráfico">
                    {periods.map(({ key, label }, index) => (
                        <Button key={key} variant="ghost" aria-pressed={active === index} aria-controls="graficoBarras" onClick={() => select(index)}>
                            {label}
                        </Button>
                    ))}
                </div>
                <div className="actividad-flechas" role="group" aria-label="Navegación del carrusel">
                    <Button iconOnly aria-label="Gráfico anterior" title="Gráfico anterior" onClick={() => select(move(active, -1))}>
                        <Icon name="chevron_left" />
                    </Button>
                    <Button iconOnly aria-label="Gráfico siguiente" title="Gráfico siguiente" onClick={() => select(move(active, 1))}>
                        <Icon name="chevron_right" />
                    </Button>
                </div>
            </div>
            <div id="graficoBarras" ref={chart} className="grafico-dashboard" role="group" tabIndex={-1}
                aria-label={`Gráfico ${period.label.toLowerCase()} de alertas`} aria-busy={resource.loading}>
                <div className="actividad-superficie">
                    <div className="actividad-resumen">
                        <div className="actividad-total">
                            <strong>{total === undefined ? resource.loading ? <Skeleton className="ui-skeleton-number" /> : "—" : number.format(total)}</strong>
                            <span>{total === 1 ? "alerta recibida" : "alertas recibidas"}</span>
                        </div>
                        <span className="actividad-unidad">{period.unit}</span>
                    </div>
                    <ChartPlot key={period.key} buckets={series?.buckets ?? []} daily={period.key === "daily"} total={total}
                        loading={resource.loading} error={resource.error} onRetry={retry} />
                </div>
                <div className="actividad-pie">
                    {series && (
                        <details className="actividad-datos" open={detailsOpen} onToggle={event => setDetailsOpen(event.currentTarget.open)}>
                            <summary>Ver datos <Icon name="chevron_down" /></summary>
                            <dl>
                                {series.buckets.map(({ name, total: count }) => (
                                    <div key={name}><dt>{name}</dt><dd>{number.format(count)}</dd></div>
                                ))}
                            </dl>
                        </details>
                    )}
                </div>
            </div>
        </article>
    );
}
