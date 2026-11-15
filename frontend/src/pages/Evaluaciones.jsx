import { useEffect, useRef, useState } from "react";
import { formatearBox, formatearFecha, formatearHora, formatearTipoRiesgo, obtenerEtiquetaEvaluacion, obtenerResultado } from "../format.js";
import { PageHeader } from "../layout.jsx";
import { Badge, Button, DataTable, Icon, Skeleton, SkeletonRows, Status } from "../ui.jsx";
import AlertDetail from "../monitor/AlertDetail.jsx";
import { ALERTS_URL, ALERT_PAGE_SIZE, saveEvaluation } from "../monitor/alerts.js";
import { usePage } from "../monitor/resources.js";

const viewKey = "evaluaciones.vista";
const views = [
    { value: "cards", label: "Tarjetas", icon: "view_grid" },
    { value: "table", label: "Tabla", icon: "view_table" },
];
const resultTones = { correcta: "success", falso_positivo: "danger", neutro: "neutral" };

function initialView() {
    try {
        const saved = localStorage.getItem(viewKey);
        if (views.some(({ value }) => value === saved)) return saved;
    } catch {
        // Los controles siguen disponibles si el navegador bloquea el almacenamiento.
    }
    return window.matchMedia("(max-width: 600px)").matches ? "cards" : "table";
}

function describeEvaluation(alert) {
    const result = obtenerResultado(alert);
    const pending = alert.estado_evaluacion === "pendiente";
    const reviewedAt = alert.evaluacion?.fecha_hora;
    const knownResult = Object.hasOwn(resultTones, result);
    return {
        id: alert.alerta_id,
        risk: alert.tipo_riesgo ? formatearTipoRiesgo(alert.tipo_riesgo) : "Alerta",
        box: alert.box ? formatearBox(alert.box) : null,
        test: alert.es_prueba,
        result: pending ? "Pendiente" : knownResult ? obtenerEtiquetaEvaluacion(result) : "Revisada",
        tone: pending ? "warning" : knownResult ? resultTones[result] : "neutral",
        action: pending ? "Evaluar" : "Ver detalle",
        dateLabel: reviewedAt ? "Evaluación" : "Detección",
        date: reviewedAt || alert.fecha_hora,
    };
}

function EvaluationDate({ record }) {
    return (
        <div className="evaluation-date">
            <small>{record.dateLabel}</small>
            {record.date ? (
                <time dateTime={record.date}>{formatearFecha(record.date)} · {formatearHora(record.date)}</time>
            ) : <span>Fecha no disponible</span>}
        </div>
    );
}

function EvaluationAction({ record, onOpen }) {
    const subject = [record.risk, record.box].filter(Boolean).join(", ");
    return (
        <Button data-alerta={record.id} aria-label={`${record.action}: ${subject}`}
            onClick={event => onOpen(record.id, event.currentTarget)}>
            {record.action}<Icon name="chevron_right" />
        </Button>
    );
}

function EvaluationTable({ records, loading, onOpen }) {
    return (
        <DataTable stickyActions className="evaluation-table" label="Evaluaciones y alertas de prueba" wrapperId="tablaEvaluacionesContenedor">
            <thead>
                <tr>
                    <th scope="col">Alerta</th>
                    <th scope="col">Resultado</th>
                    <th scope="col">Fecha</th>
                    <th scope="col">Acción</th>
                </tr>
            </thead>
            <tbody id="tablaEvaluaciones">
                {loading ? <SkeletonRows columns={4} /> : records.map(record => (
                    <tr key={record.id}>
                        <td>
                            <div className="evaluation-identity">
                                <strong>{record.risk}</strong>
                                {(record.box || record.test) && <div className="evaluation-context">
                                    {record.box && <span>{record.box}</span>}
                                    {record.test && <Badge tone="info">Alerta de prueba</Badge>}
                                </div>}
                            </div>
                        </td>
                        <td><Badge tone={record.tone}>{record.result}</Badge></td>
                        <td><EvaluationDate record={record} /></td>
                        <td><EvaluationAction record={record} onOpen={onOpen} /></td>
                    </tr>
                ))}
            </tbody>
        </DataTable>
    );
}

function EvaluationCards({ records, loading, onOpen }) {
    if (loading) {
        return (
            <div className="evaluation-grid" aria-hidden="true">
                {Array.from({ length: 4 }, (_, index) => (
                    <div className="evaluation-card" key={index}>
                        <Skeleton className="ui-skeleton-count" />
                        <Skeleton className="ui-skeleton-number" />
                        <Skeleton className="ui-skeleton-count" />
                        <div className="evaluation-card-footer"><Skeleton className="ui-skeleton-count" /></div>
                    </div>
                ))}
            </div>
        );
    }
    return (
        <ul className="evaluation-grid" role="list" aria-label="Evaluaciones y alertas de prueba">
            {records.map(record => (
                <li key={record.id}>
                    <article className="evaluation-card">
                        <header className="evaluation-card-header">
                            <div className="evaluation-identity">
                                <h3>{record.risk}</h3>
                                {record.box && <span>{record.box}</span>}
                            </div>
                            {record.test && <Badge tone="info">Alerta de prueba</Badge>}
                        </header>
                        <Badge tone={record.tone}>{record.result}</Badge>
                        <footer className="evaluation-card-footer">
                            <EvaluationDate record={record} />
                            <EvaluationAction record={record} onOpen={onOpen} />
                        </footer>
                    </article>
                </li>
            ))}
        </ul>
    );
}

export default function Evaluaciones() {
    const [view, setView] = useState(initialView);
    const [offset, setOffset] = useState(0);
    const [selected, setSelected] = useState(null);
    const [evaluation, setEvaluation] = useState(null);
    const [saving, setSaving] = useState(false);
    const inFlight = useRef(false);
    const titleRef = useRef(null);
    const detailTrigger = useRef(null);
    const shouldFocus = useRef(false);
    const { data, loading, error, reload } = usePage(ALERTS_URL, "registro_evaluaciones=true", offset, ALERT_PAGE_SIZE);

    useEffect(() => {
        if (!loading && shouldFocus.current) {
            shouldFocus.current = false;
            titleRef.current?.focus();
        }
    }, [loading]);

    const total = data?.total ?? 0;
    const pageOffset = data?.offset ?? offset;
    const pages = Math.ceil(total / ALERT_PAGE_SIZE);
    const page = Math.floor(pageOffset / ALERT_PAGE_SIZE) + 1;
    const summary = loading ? <Skeleton className="ui-skeleton-count" />
        : error ? "No se pudieron consultar las evaluaciones."
        : pages > 1 ? `Mostrando ${pageOffset + 1}–${pageOffset + data.items.length} de ${total} registros`
        : total === 1 ? "1 registro" : `${total} registros`;
    const records = data?.items.map(describeEvaluation) ?? [];
    const EvaluationView = view === "cards" ? EvaluationCards : EvaluationTable;

    function chooseView(nextView) {
        setView(nextView);
        try {
            localStorage.setItem(viewKey, nextView);
        } catch {
            // El cambio de vista no depende de guardar la preferencia.
        }
    }

    function openDetail(id, trigger) {
        detailTrigger.current = trigger;
        setEvaluation(null);
        setSelected(id);
    }

    function movePage(newOffset) {
        shouldFocus.current = true;
        setOffset(newOffset);
    }

    function retry() {
        shouldFocus.current = true;
        reload();
    }

    async function evaluateTest(id, option) {
        if (inFlight.current) return;
        inFlight.current = true;
        setSaving(true);
        try {
            const result = await saveEvaluation(id, option);
            setEvaluation(result.evaluation);
            reload();
            return result;
        } finally {
            inFlight.current = false;
            setSaving(false);
        }
    }

    function closeDetail() {
        setSelected(null);
        if (!detailTrigger.current?.isConnected) {
            requestAnimationFrame(() => titleRef.current?.focus());
        }
    }

    return (
        <>
            <PageHeader title="Registro de evaluaciones" />
            <section className="panel-alertas panel-evaluaciones" aria-labelledby="tituloEvaluaciones" aria-busy={loading}>
                <div className="panel-cabecera">
                    <div>
                        <h2 id="tituloEvaluaciones" ref={titleRef} tabIndex={-1}>Evaluaciones y alertas de prueba</h2>
                        <p id="resultadoEvaluaciones" role="status">{summary}</p>
                    </div>
                    <div className="evaluation-toolbar">
                        <div className="evaluation-view-toggle" role="group" aria-label="Formato del registro">
                            {views.map(({ value, label, icon }) => (
                                <Button key={value} variant="ghost" aria-pressed={view === value} onClick={() => chooseView(value)}>
                                    <Icon name={icon} />{label}
                                </Button>
                            ))}
                        </div>
                        <Button onClick={reload} busy={loading} busyLabel="Actualizando…"><Icon name="refresh" />Actualizar</Button>
                    </div>
                </div>
                {error && <Status id="estadoVacioEvaluaciones" type="error" error={error} messages={{ 404: "No encontramos el registro de evaluaciones solicitado." }} onRetry={retry} />}
                {data && data.items.length === 0 && <Status id="estadoVacioEvaluaciones" type="vacio">Todavía no existen evaluaciones ni alertas de prueba.</Status>}
                {(loading || records.length > 0) && <EvaluationView records={records} loading={loading} onOpen={openDetail} />}
                {pages > 1 && (
                    <nav id="paginacionEvaluaciones" className="monitor-pagination" aria-label="Paginación de evaluaciones">
                        <span id="paginaEvaluaciones">Página {page} de {pages}</span>
                        <div className="monitor-pagination-buttons">
                            <Button id="evaluacionesAnterior" variant="secondary" disabled={page === 1} onClick={() => movePage(pageOffset - ALERT_PAGE_SIZE)}>Anterior</Button>
                            <Button id="evaluacionesSiguiente" variant="secondary" disabled={page === pages} onClick={() => movePage(pageOffset + ALERT_PAGE_SIZE)}>Siguiente</Button>
                        </div>
                    </nav>
                )}
            </section>
            {selected && <AlertDetail key={selected} id={selected} onClose={closeDetail} returnFocusRef={detailTrigger}
                evaluation={evaluation?.alerta_id === selected ? evaluation : null} saving={saving} onEvaluate={evaluateTest} />}
        </>
    );
}
