import { useRef, useState } from "react";
import { PageHeader } from "../layout.jsx";
import { Button, DataTable, Icon, SkeletonRows, Status } from "../ui.jsx";
import { DetailButton } from "../monitor/AlertDetail.jsx";
import AuditDetail, { AuditOutcome } from "../monitor/AuditDetail.jsx";
import ExcelDownload from "../monitor/ExcelDownload.jsx";
import { usePage } from "../monitor/resources.js";
import {
    AUDIT_URL, AUDIT_PAGE_SIZE, actionText, actorText, addDays, auditActions, auditErrorMessages,
    auditQuery, auditTime, channelText, defaultAuditFilters, formatWeek, fromDateInput, outcomes,
    shortId, toDateInput, todayInChile,
} from "../monitor/audit.js";

function AuditPeriod({ date, onDateChange }) {
    return (
        <section className="barra-periodo" aria-label="Selección de periodo">
            <strong id="periodoActual">{formatWeek(date)}</strong>
            <div className="periodo-controles">
                <Button id="semanaAnterior" variant="secondary" aria-label="Ver semana anterior" onClick={() => onDateChange(addDays(date, -7))}>
                    <Icon name="arrow_back" /> Semana anterior
                </Button>
                <input type="date" id="fechaReferencia" className="campo-fecha" aria-label="Seleccionar fecha de referencia" value={toDateInput(date)} onChange={(event) => {
                    const next = fromDateInput(event.target.value);
                    if (next) onDateChange(next);
                }} />
                <Button id="semanaSiguiente" variant="secondary" aria-label="Ver semana siguiente" onClick={() => onDateChange(addDays(date, 7))}>
                    Semana siguiente <Icon name="arrow_forward" />
                </Button>
            </div>
        </section>
    );
}

function AuditFilters({ draft, onEdit, onApply, onClear, alertFilterRef }) {
    const set = (key) => (event) => onEdit({ ...draft, [key]: event.target.value });
    return (
        <form id="formFiltros" className="filtros-bitacora" onSubmit={(event) => {
            event.preventDefault();
            onApply();
        }}>
            <div className="campo">
                <label htmlFor="filtroAlerta">ID de alerta</label>
                <input type="text" id="filtroAlerta" ref={alertFilterRef} value={draft.alert} placeholder="UUID de la alerta" autoComplete="off" onChange={set("alert")} />
            </div>
            <div className="campo">
                <label htmlFor="filtroAccion">Tipo de evento</label>
                <select id="filtroAccion" value={draft.action} onChange={set("action")}>
                    <option value="">Todos</option>
                    {Object.entries(auditActions).map(([action, [label]]) => <option value={action} key={action}>{label}</option>)}
                </select>
            </div>
            <div className="campo">
                <label htmlFor="filtroResultado">Resultado</label>
                <select id="filtroResultado" value={draft.outcome} onChange={set("outcome")}>
                    <option value="">Todos</option>
                    {Object.entries(outcomes).map(([outcome, { text }]) => <option value={outcome} key={outcome}>{text}</option>)}
                </select>
            </div>
            <div className="campo">
                <label htmlFor="filtroOrden">Orden</label>
                <select id="filtroOrden" value={draft.order} onChange={set("order")}>
                    <option value="desc">Más recientes primero</option>
                    <option value="asc">Más antiguos primero</option>
                </select>
            </div>
            <div className="acciones-filtros">
                <Button variant="primary" type="submit">Aplicar filtros</Button>
                <Button id="limpiarFiltros" variant="secondary" onClick={onClear}>Limpiar</Button>
            </div>
        </form>
    );
}

function AuditTable({ events, onOpen, loading }) {
    return (
        <DataTable stickyActions label="Eventos de la bitácora. Las horas corresponden a Chile." className="monitor-table" wrapperId="contenedorTabla">
            <thead>
                <tr>
                    {["Momento", "Evento / canal", "Resultado", "Responsable", "Alerta vinculada", "Detalle"].map((header) => (
                        <th scope="col" key={header}>{header}</th>
                    ))}
                </tr>
            </thead>
            <tbody id="tablaEventos">
                {loading ? <SkeletonRows columns={6} /> : events.map((event) => {
                    const action = actionText(event.action);
                    const date = auditTime(event.timestamp);
                    const phase = { principal: "Principal", respaldo: "Respaldo", resumen: "Resumen de envíos" }[event.notification?.phase];
                    const context = [event.channel && channelText(event.channel), phase].filter(Boolean).join(" · ");
                    const actor = actorText(event);
                    const fallbackActor = event.actor_id && actor === `Usuario (${event.actor_id})`;
                    return (
                        <tr key={event.event_id} data-resultado={event.outcome}>
                            <td>
                                {date === "—" ? "Fecha no registrada" : (
                                    <time className="monitor-cell-stack" dateTime={event.timestamp} title={date} aria-label={date}>
                                        <strong>{auditTime(event.timestamp, { day: "2-digit", month: "short" })}</strong>
                                        <small>{auditTime(event.timestamp, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</small>
                                    </time>
                                )}
                            </td>
                            <td>
                                <div className="monitor-cell-stack">
                                    <strong className="etiqueta-evento" title={action}>{action}</strong>
                                    {context && <small className="etiqueta-canal">{context}</small>}
                                </div>
                            </td>
                            <td><AuditOutcome event={event} showIcon /></td>
                            <td aria-label={fallbackActor ? actor : undefined} title={fallbackActor ? actor : undefined}>
                                {fallbackActor ? `Usuario (${shortId(event.actor_id)})` : actor}
                            </td>
                            <td>
                                {event.alerta_id ? <span className="monitor-id" title={event.alerta_id} aria-label={`ID de alerta ${event.alerta_id}. Valor completo disponible en el detalle.`}>{shortId(event.alerta_id)}</span> : "—"}
                            </td>
                            <td><DetailButton label={`Ver detalle: ${action}, ${date}`} onClick={(click) => onOpen(event, click.currentTarget)} /></td>
                        </tr>
                    );
                })}
            </tbody>
        </DataTable>
    );
}

export default function Bitacora() {
    const [date, setDate] = useState(todayInChile);
    const [draft, setDraft] = useState(defaultAuditFilters);
    const [applied, setApplied] = useState(defaultAuditFilters);
    const [offset, setOffset] = useState(0);
    const [selected, setSelected] = useState(null);
    const triggerRef = useRef(null);
    const alertFilterRef = useRef(null);
    const query = auditQuery(date, applied);
    const { data, loading, error, reload } = usePage(AUDIT_URL, query, offset, AUDIT_PAGE_SIZE);

    function load(nextDraft = draft, newOffset = 0) {
        setApplied(nextDraft);
        setOffset(newOffset);
        reload();
    }

    function followAlert(id) {
        const nextDraft = { ...defaultAuditFilters, alert: id, order: draft.order };
        setSelected(null);
        setDraft(nextDraft);
        load(nextDraft);
        requestAnimationFrame(() => alertFilterRef.current?.focus());
    }

    return (
        <>
            <PageHeader title="Bitácora del sistema" description="Consulta de la trazabilidad de alertas, despachos, evaluaciones y eventos técnicos registrados en el sistema." />
            <AuditPeriod date={date} onDateChange={(nextDate) => {
                setDate(nextDate);
                load();
            }} />
            <section className="resumen-bitacora" aria-label="Tipos de eventos">
                {Object.entries(auditActions).map(([action, [label, description]]) => (
                    <details key={action} className="tarjeta-resumen">
                        <summary><span className="tarjeta-resumen-etiqueta">{label}</span><span className="flecha-tarjeta" aria-hidden="true" /></summary>
                        <div className="descripcion-tarjeta">{description}</div>
                    </details>
                ))}
            </section>
            <section className="panel-bitacora">
                <div className="cabecera-panel-bitacora">
                    <h2>Eventos de la bitácora</h2>
                    <div className="acciones-cabecera-bitacora">
                        <Button variant="primary" id="recargarBitacora" onClick={() => load(draft, data?.offset ?? offset)}>Actualizar</Button>
                        <ExcelDownload id="descargarExcelBitacora" url={data ? `${AUDIT_URL}/export?${query}` : null} fallbackFilename="bitacora_eventos.xlsx" />
                    </div>
                </div>
                <AuditFilters draft={draft} onEdit={setDraft} onApply={load} alertFilterRef={alertFilterRef} onClear={() => {
                    setDraft(defaultAuditFilters);
                    load(defaultAuditFilters);
                }} />
                <div aria-busy={loading}>
                    {loading && <AuditTable loading />}
                    {error && <Status type="error" error={error} messages={auditErrorMessages} onRetry={reload} />}
                    {data && !data.items.length && <Status type="vacio">No se encontraron registros para el periodo o filtros seleccionados.</Status>}
                    {Boolean(data?.items.length) && (
                        <>
                            <AuditTable events={data.items} onOpen={(event, trigger) => {
                                triggerRef.current = trigger;
                                setSelected(event);
                            }} />
                            <nav className="monitor-pagination" id="paginacionBitacora" aria-label="Paginación de la bitácora">
                                <span id="textoPaginacion" role="status">{data.offset + 1}–{Math.min(data.offset + AUDIT_PAGE_SIZE, data.total)} de {data.total} eventos</span>
                                <div className="monitor-pagination-buttons">
                                    <Button id="paginaAnterior" variant="secondary" disabled={data.offset === 0} onClick={() => load(draft, data.offset - AUDIT_PAGE_SIZE)}>Anterior</Button>
                                    <Button id="paginaSiguiente" variant="secondary" disabled={data.offset + AUDIT_PAGE_SIZE >= data.total} onClick={() => load(draft, data.offset + AUDIT_PAGE_SIZE)}>Siguiente</Button>
                                </div>
                            </nav>
                        </>
                    )}
                </div>
            </section>
            {selected && <AuditDetail key={selected.event_id} event={selected} onClose={() => setSelected(null)} onFollowAlert={followAlert} returnFocusRef={triggerRef} />}
        </>
    );
}
