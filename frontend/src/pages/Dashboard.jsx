import { useEffect, useRef, useState } from "react";
import { codigoAlertaVisible, codigosAlerta, formatearBox, formatearFecha, formatearHora, formatearTipoRiesgo, obtenerEtiquetaEvaluacion } from "../format.js";
import { PageHeader } from "../layout.jsx";
import { Badge, Button, DataTable, Icon, SkeletonRows, Status } from "../ui.jsx";
import AlertDetail, { SeverityBadge } from "../monitor/AlertDetail.jsx";
import DashboardOverview, { useDashboardOverview } from "../monitor/DashboardOverview.jsx";
import ExcelDownload from "../monitor/ExcelDownload.jsx";
import { ALERTS_URL, ALERT_PAGE_SIZE, evaluationChoices, saveEvaluation, withEvaluation } from "../monitor/alerts.js";
import { usePage } from "../monitor/resources.js";

const REVIEWED = "__revisadas__";
const reviewFilters = [
    { value: "", label: "Todas" },
    { value: "pendiente", label: "Pendientes" },
    { value: REVIEWED, label: "Revisadas" },
];
const outcomes = Object.keys(evaluationChoices);
const emptyFilters = { q: "", box: "", state: "", from: "", to: "" };
const alertColumns = [
    { key: "risk", label: "Alerta" },
    { key: "level", label: "Prioridad" },
    { key: "location", label: "Ubicación" },
    { key: "date", label: "Fecha y hora" },
    { key: "status", label: "Estado" },
    { key: "action", label: "Acción" },
];
const reviewTones = { pendiente: "warning", correcta: "success", falso_positivo: "info" };

function initialFilters() {
    const params = new URLSearchParams(window.location.search);
    const reviewed = params.get("revisadas");
    const state = params.get("estado_evaluacion");
    if (reviewed === "true") return { ...emptyFilters, state: REVIEWED };
    if (reviewed === "false" || state === "pendiente") return { ...emptyFilters, state: "pendiente" };
    return {
        ...emptyFilters,
        state: outcomes.includes(state) || state === REVIEWED ? state : "",
    };
}

function alertQuery(filters) {
    const params = new URLSearchParams();
    if (filters.q) {
        const match = Object.entries(codigosAlerta).find(([, code]) => code.toLowerCase() === filters.q.toLowerCase());
        params.set("q", match?.[0] ?? filters.q);
    }
    if (filters.box) params.set("box", filters.box);
    if (filters.state === REVIEWED) params.set("revisadas", "true");
    else if (filters.state) params.set("estado_evaluacion", filters.state);
    if (filters.from) params.set("fecha_desde", filters.from);
    if (filters.to) params.set("fecha_hasta", filters.to);
    return params.toString();
}

function DashboardFilters({ filters, onFilter, onClear, searchRef }) {
    const [search, setSearch] = useState("");
    const outcome = outcomes.includes(filters.state) ? filters.state : "";
    const extraCount = [filters.from, filters.to, outcome].filter(Boolean).length;
    const [expanded, setExpanded] = useState(Boolean(extraCount));
    const canClear = search || Object.values(filters).some(Boolean);

    return (
        <div className="dashboard-filters">
            <div className="dashboard-status-filter" role="group" aria-label="Filtrar por estado de revisión">
                {reviewFilters.map(({ value, label }) => (
                    <Button key={value} aria-pressed={(outcome ? REVIEWED : filters.state) === value}
                        onClick={() => {
                            if (value !== filters.state) onFilter("state", value);
                        }}>
                        {label}
                    </Button>
                ))}
            </div>
            <div className="dashboard-filter-bar">
                <form id="formularioBusquedaAlertas" className="campo dashboard-search" role="search" aria-label="Buscar alertas" onSubmit={(event) => {
                    event.preventDefault();
                    onFilter("q", search.trim());
                }}>
                    <label htmlFor="buscar">Buscar alerta</label>
                    <div className="dashboard-search-field">
                        <input type="search" id="buscar" ref={searchRef} placeholder="Código, box o tipo de riesgo" value={search} onChange={(event) => setSearch(event.target.value)} />
                        <Button variant="primary" type="submit">Buscar</Button>
                    </div>
                </form>
                <div className="campo">
                    <label htmlFor="filtroBox">Box</label>
                    <select id="filtroBox" value={filters.box} onChange={(event) => onFilter("box", event.target.value)}>
                        <option value="">Todos</option>
                        {[3, 4, 5, 6, 7].map((box) => <option key={box} value={`box-${box}`}>Box 0{box}</option>)}
                    </select>
                </div>
                <Button className="dashboard-more-filters" aria-expanded={expanded} aria-controls="filtrosAdicionales"
                    onClick={() => setExpanded(!expanded)}>
                    <Icon name="filter" />
                    Más filtros{extraCount ? ` (${extraCount})` : ""}
                </Button>
            </div>
            <div id="filtrosAdicionales" className="dashboard-extra-filters" hidden={!expanded}>
                <div className="campo">
                    <label htmlFor="fechaDesde">Desde</label>
                    <input type="date" id="fechaDesde" value={filters.from} onChange={(event) => onFilter("from", event.target.value)} />
                </div>
                <div className="campo">
                    <label htmlFor="fechaHasta">Hasta</label>
                    <input type="date" id="fechaHasta" value={filters.to} onChange={(event) => onFilter("to", event.target.value)} />
                </div>
                <div className="campo">
                    <label htmlFor="filtroEstado">Resultado de la revisión</label>
                    <select id="filtroEstado" value={outcome} onChange={(event) => onFilter("state", event.target.value || REVIEWED)}>
                        <option value="">Todos</option>
                        {outcomes.map((value) => <option key={value} value={value}>{obtenerEtiquetaEvaluacion(value)}</option>)}
                    </select>
                </div>
            </div>
            {canClear && (
                <Button id="limpiarFiltros" variant="ghost" className="dashboard-clear-filters" onClick={() => {
                    setSearch("");
                    onClear();
                    searchRef.current?.focus();
                }}>Limpiar filtros</Button>
            )}
        </div>
    );
}

function DashboardAlertTable({ items, onOpen, loading }) {
    return (
        <DataTable className="dashboard-alert-table" wrapperClassName="dashboard-table-wrap" wrapperId="tablaContenedor"
            label="Resultados del historial" aria-label="Alertas registradas" role="table">
            <thead role="rowgroup">
                <tr role="row">
                    {alertColumns.map(({ key, label }) => (
                        <th key={key} data-column={key} scope="col" role="columnheader">{label}</th>
                    ))}
                </tr>
            </thead>
            <tbody id="tablaAlertas" role="rowgroup">
                {loading ? <SkeletonRows columns={alertColumns.length} /> : items.map((alert) => {
                    const id = alert.alerta_id;
                    const code = codigoAlertaVisible(id);
                    const risk = formatearTipoRiesgo(alert.tipo_riesgo);
                    const box = formatearBox(alert.box);
                    const date = formatearFecha(alert.fecha_hora);
                    const state = alert.estado_evaluacion;
                    const pending = state === "pendiente";
                    const outcome = obtenerEtiquetaEvaluacion(state);
                    const status = pending ? "Pendiente" : outcome === "—" ? "Revisada" : outcome;
                    return (
                        <tr key={id} role="row">
                            <td role="cell" data-column="risk">
                                <div className="dashboard-risk">
                                    <strong>{risk === "—" ? "Tipo no disponible" : risk}</strong>
                                    {alert.es_prueba && <Badge>Prueba</Badge>}
                                </div>
                            </td>
                            <td role="cell" data-column="level"><SeverityBadge alert={alert} /></td>
                            <td role="cell" data-column="location">{box === "—" ? "Sin ubicación" : box}</td>
                            <td role="cell" data-column="date">
                                {date === "—" ? "Fecha no disponible" : (
                                    <time dateTime={alert.fecha_hora} className="monitor-cell-stack">
                                        <span>{date}</span>
                                        <small>{formatearHora(alert.fecha_hora)}</small>
                                    </time>
                                )}
                            </td>
                            <td role="cell" data-column="status">
                                <Badge className="dashboard-review-status" tone={reviewTones[state]}>{status}</Badge>
                            </td>
                            <td role="cell" data-column="action">
                                <Button className="dashboard-alert-action" data-pending={pending || undefined}
                                    aria-label={`${pending ? "Revisar" : "Ver detalle de"} alerta ${code}`}
                                    data-alerta={id} onClick={(event) => onOpen(id, event.currentTarget)}>
                                    {pending ? "Revisar" : "Ver detalle"}
                                    <Icon name="chevron_right" />
                                </Button>
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </DataTable>
    );
}

function DashboardPagination({ data, onMove }) {
    const { offset, total, items } = data;
    const page = Math.floor(offset / ALERT_PAGE_SIZE) + 1;
    const pages = Math.ceil(total / ALERT_PAGE_SIZE);
    const first = Math.max(1, Math.min(page - 2, pages - 4));
    const visiblePages = Array.from({ length: Math.min(5, pages) }, (_, index) => first + index);

    return (
        <nav id="paginacion" className="monitor-pagination" aria-label="Paginación de alertas">
            <span id="textoPaginacion">Mostrando {offset + 1}–{Math.min(offset + items.length, total)} de {total}</span>
            <div className="monitor-pagination-buttons">
                <Button id="paginaAnterior" variant="secondary" disabled={page === 1} onClick={() => onMove(offset - ALERT_PAGE_SIZE)}>Anterior</Button>
                <div id="numerosPagina" className="monitor-pagination-buttons">
                    {visiblePages.map((number) => (
                        <Button
                            key={number}
                            variant={number === page ? "primary" : "secondary"}
                            aria-current={number === page ? "page" : undefined}
                            aria-label={`Página ${number}`}
                            data-pagina={number}
                            onClick={() => onMove((number - 1) * ALERT_PAGE_SIZE)}
                        >{number}</Button>
                    ))}
                </div>
                <Button id="paginaSiguiente" variant="secondary" disabled={page === pages} onClick={() => onMove(offset + ALERT_PAGE_SIZE)}>Siguiente</Button>
            </div>
        </nav>
    );
}

export default function Dashboard() {
    const [filters, setFilters] = useState(initialFilters);
    const [offset, setOffset] = useState(0);
    const [selected, setSelected] = useState(null);
    const [reviews, setReviews] = useState(() => new Map());
    const [saving, setSaving] = useState(() => new Set());
    const inFlight = useRef(new Set());
    const trigger = useRef(null);
    const searchRef = useRef(null);
    const titleRef = useRef(null);
    const historyRef = useRef(null);
    const shouldFocus = useRef(false);
    const query = alertQuery(filters);
    const list = usePage(ALERTS_URL, query, offset, ALERT_PAGE_SIZE);
    const overview = useDashboardOverview();
    const total = list.data?.total ?? 0;

    useEffect(() => {
        if (!list.loading && shouldFocus.current) {
            shouldFocus.current = false;
            titleRef.current?.focus();
        }
    }, [list.loading]);

    useEffect(() => {
        if (window.location.hash === "#historial-alertas") historyRef.current?.scrollIntoView();
    }, []);

    function applyFilters(nextFilters) {
        setFilters(nextFilters);
        setOffset(0);
        list.reload();
    }

    function movePage(newOffset) {
        shouldFocus.current = true;
        setOffset(newOffset);
        list.reload();
    }

    function openDetail(id, source) {
        trigger.current = source;
        setSelected(id);
    }

    function closeDetail() {
        setSelected(null);
        if (!trigger.current?.isConnected) {
            requestAnimationFrame(() => searchRef.current?.focus());
        }
    }

    async function evaluateAlert(id, option) {
        if (inFlight.current.has(id)) return;
        inFlight.current.add(id);
        setSaving(new Set(inFlight.current));
        try {
            const result = await saveEvaluation(id, option);
            setReviews((previous) => new Map(previous).set(id, result.evaluation));
            list.reload();
            overview.refresh();
            return result;
        } finally {
            inFlight.current.delete(id);
            setSaving(new Set(inFlight.current));
        }
    }

    return (
        <>
            <PageHeader title="Dashboard de alertas" description="Resumen general de alertas y actividad registrada." />
            <DashboardOverview summary={overview.summary} chart={overview.chart} />
            <section id="historial-alertas" ref={historyRef} className="panel-alertas dashboard-history" aria-labelledby="tituloAlertas">
                <div className="dashboard-controls">
                    <header className="dashboard-history-header">
                        <h2 id="tituloAlertas" ref={titleRef} tabIndex={-1}>Historial de alertas</h2>
                        <div className="dashboard-actions">
                            <Button id="botonActualizar" disabled={list.loading} onClick={() => {
                                list.reload();
                                overview.refresh();
                            }}>
                                <Icon name="refresh" />
                                Actualizar
                            </Button>
                            <ExcelDownload id="descargarExcelDashboard"
                                url={`${ALERTS_URL}/export${query ? `?${query}` : ""}`} fallbackFilename="dashboard_alertas.xlsx" />
                        </div>
                    </header>
                    <DashboardFilters filters={filters} searchRef={searchRef}
                        onFilter={(field, value) => applyFilters({ ...filters, [field]: value })} onClear={() => applyFilters(emptyFilters)} />
                </div>
                <p id="resultadoTexto" className="dashboard-result-count" role="status">
                    {list.loading ? "Cargando alertas…" : total > 0 ? `${total} ${total === 1 ? "alerta encontrada" : "alertas encontradas"}` : ""}
                </p>
                <div className="dashboard-results" aria-busy={list.loading}>
                    {list.error && <Status id="estadoVacio" type="error" error={list.error} messages={{ 404: "No encontramos las alertas solicitadas." }} onRetry={list.reload} />}
                    {list.data && !list.data.items.length && (
                        <Status id="estadoVacio" type="vacio">{query ? "No hay alertas que coincidan con los filtros." : "Todavía no hay alertas registradas."}</Status>
                    )}
                    {(list.loading || Boolean(list.data?.items.length)) && (
                        <DashboardAlertTable loading={list.loading} items={list.data?.items.map((alert) => withEvaluation(alert, reviews.get(alert.alerta_id)))}
                            onOpen={openDetail} />
                    )}
                    {total > ALERT_PAGE_SIZE && <DashboardPagination data={list.data} onMove={movePage} />}
                </div>
            </section>
            {selected && (
                <AlertDetail
                    key={selected}
                    id={selected}
                    onClose={closeDetail}
                    returnFocusRef={trigger}
                    evaluation={reviews.get(selected)}
                    saving={saving.has(selected)}
                    onEvaluate={evaluateAlert}
                />
            )}
        </>
    );
}
