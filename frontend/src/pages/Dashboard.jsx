import { useEffect, useRef, useState } from "react";
import { codigoAlertaVisible, codigosAlerta, formatearBox, formatearFecha, formatearHora, formatearTipoRiesgo, obtenerEtiquetaEvaluacion } from "../format.js";
import { PageHeader } from "../layout.jsx";
import { Badge, Button, DataTable, Skeleton, SkeletonRows, Status } from "../ui.jsx";
import AlertDetail, { DetailButton, SeverityBadge } from "../monitor/AlertDetail.jsx";
import DashboardOverview, { useDashboardOverview } from "../monitor/DashboardOverview.jsx";
import ExcelDownload from "../monitor/ExcelDownload.jsx";
import { ALERTS_URL, ALERT_PAGE_SIZE, saveEvaluation, withEvaluation } from "../monitor/alerts.js";
import { usePage } from "../monitor/resources.js";

const states = {
    "": "Todos",
    pendiente: "Pendiente",
    __revisadas__: "Revisadas",
    correcta: "Correcta",
    falso_positivo: "Falso positivo",
    neutro: "Neutro",
};
const emptyFilters = { q: "", box: "", state: "", from: "", to: "" };

function initialFilters() {
    const params = new URLSearchParams(window.location.search);
    const reviewed = params.get("revisadas");
    const state = params.get("estado_evaluacion");
    return {
        ...emptyFilters,
        state: reviewed === "true" ? "__revisadas__" : reviewed === "false" ? "pendiente" : Object.hasOwn(states, state) ? state : "",
    };
}

function alertQuery(filters) {
    const params = new URLSearchParams();
    if (filters.q) {
        const match = Object.entries(codigosAlerta).find(([, code]) => code.toLowerCase() === filters.q.toLowerCase());
        params.set("q", match?.[0] ?? filters.q);
    }
    if (filters.box) params.set("box", filters.box);
    if (filters.state === "__revisadas__") params.set("revisadas", "true");
    else if (filters.state) params.set("estado_evaluacion", filters.state);
    if (filters.from) params.set("fecha_desde", filters.from);
    if (filters.to) params.set("fecha_hasta", filters.to);
    return params.toString();
}

function DashboardFilters({ filters, onFilter, onClear, searchRef }) {
    const [search, setSearch] = useState("");
    return (
        <div className="panel-filtros">
            <form id="formularioBusquedaAlertas" className="campo campo-busqueda" role="search" aria-label="Buscar alertas" onSubmit={(event) => {
                event.preventDefault();
                onFilter("q", search.trim());
            }}>
                <label htmlFor="buscar">Buscar</label>
                <div className="entrada-busqueda-alertas">
                    <input type="search" id="buscar" ref={searchRef} placeholder="ID, box o tipo de riesgo" value={search} onChange={(event) => setSearch(event.target.value)} />
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
            <div className="campo">
                <label htmlFor="filtroEstado">Estado</label>
                <select id="filtroEstado" value={filters.state} onChange={(event) => onFilter("state", event.target.value)}>
                    {Object.entries(states).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
            </div>
            <div className="campo">
                <label htmlFor="fechaDesde">Desde</label>
                <input type="date" id="fechaDesde" value={filters.from} onChange={(event) => onFilter("from", event.target.value)} />
            </div>
            <div className="campo">
                <label htmlFor="fechaHasta">Hasta</label>
                <input type="date" id="fechaHasta" value={filters.to} onChange={(event) => onFilter("to", event.target.value)} />
            </div>
            <Button id="limpiarFiltros" variant="secondary" className="dashboard-clear-filters" onClick={() => {
                setSearch("");
                onClear();
            }}>Limpiar</Button>
        </div>
    );
}

function DashboardAlertTable({ items, onOpen, loading }) {
    return (
        <DataTable stickyActions className="monitor-table monitor-table-alerts" wrapperId="tablaContenedor" label="Alertas registradas">
            <thead>
                <tr>
                    {["Alerta", "Box", "Tipo", "Nivel", "Fecha", "Hora", "Estado", "Acción"].map((header) => (
                        <th key={header} scope="col">{header}</th>
                    ))}
                </tr>
            </thead>
            <tbody id="tablaAlertas">
                {loading ? <SkeletonRows columns={8} /> : items.map((alert) => {
                    const id = alert.alerta_id;
                    const code = codigoAlertaVisible(id);
                    const pending = alert.estado_evaluacion === "pendiente";
                    return (
                        <tr key={id}>
                            <td><strong className="monitor-id">{code}</strong></td>
                            <td>{formatearBox(alert.box)}</td>
                            <td>{formatearTipoRiesgo(alert.tipo_riesgo)}</td>
                            <td><SeverityBadge alert={alert} /></td>
                            <td>{formatearFecha(alert.fecha_hora)}</td>
                            <td>{formatearHora(alert.fecha_hora)}</td>
                            <td>
                                <Badge tone={pending ? "warning" : "success"} title={`Estado de evaluación: ${pending ? "Pendiente" : obtenerEtiquetaEvaluacion(alert.estado_evaluacion)}`}>
                                    {pending ? "Pendiente" : "Revisada"}
                                </Badge>
                            </td>
                            <td>
                                {pending ? (
                                    <Button variant="secondary" aria-label={`Revisar alerta ${code}`} data-alerta={id} onClick={(event) => onOpen(id, event.currentTarget)}>Revisar</Button>
                                ) : (
                                    <DetailButton icon="arrow_forward" label={`Ver detalle de alerta ${code}`} data-alerta={id} onClick={(event) => onOpen(id, event.currentTarget)} />
                                )}
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
            <section id="historial-alertas" ref={historyRef} className="seccion-historial">
                <header className="cabecera-historial">
                    <h2>Historial de alertas</h2>
                    <div className="acciones-dashboard">
                        <Button variant="primary" id="botonActualizar" onClick={() => {
                            list.reload();
                            overview.refresh();
                        }}>Actualizar</Button>
                        <ExcelDownload id="descargarExcelDashboard" url={`${ALERTS_URL}/export${query ? `?${query}` : ""}`} fallbackFilename="dashboard_alertas.xlsx" />
                    </div>
                </header>
                <DashboardFilters filters={filters} searchRef={searchRef} onFilter={(field, value) => applyFilters({ ...filters, [field]: value })} onClear={() => applyFilters(emptyFilters)} />
                <section className="panel-alertas" aria-busy={list.loading}>
                    <div className="panel-cabecera">
                        <div>
                            <h2 id="tituloAlertas" ref={titleRef} tabIndex={-1}>Alertas registradas</h2>
                            <p id="resultadoTexto" role="status">{list.loading ? <Skeleton className="ui-skeleton-count" />
                                : list.error ? "No se pudieron consultar las alertas."
                                : `${total} ${total === 1 ? "alerta encontrada" : "alertas encontradas"}`}</p>
                        </div>
                    </div>
                    <>
                        {list.error && <Status id="estadoVacio" type="error" error={list.error} messages={{ 404: "No encontramos las alertas solicitadas." }} onRetry={list.reload} />}
                        {list.data && !list.data.items.length && (
                            <Status id="estadoVacio" type="vacio">{query ? "No hay alertas que coincidan con los filtros. Prueba con otros criterios." : "Todavía no hay alertas registradas."}</Status>
                        )}
                    </>
                    {(list.loading || Boolean(list.data?.items.length)) && (
                        <DashboardAlertTable loading={list.loading}
                            items={list.data?.items.map((alert) => withEvaluation(alert, reviews.get(alert.alerta_id)))} onOpen={openDetail} />
                    )}
                    {Boolean(list.data?.items.length) && <DashboardPagination data={list.data} onMove={movePage} />}
                </section>
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
