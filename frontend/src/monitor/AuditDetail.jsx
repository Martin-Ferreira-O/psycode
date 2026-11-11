import { useEffect, useRef, useState } from "react";
import { Badge, Button, Dialog, Icon } from "../ui.jsx";
import { actionText, actorText, auditActions, auditTime, channelText, notificationDetails, outcomes, outcomeText } from "./audit.js";

export function AuditOutcome({ event, showIcon = false, id }) {
    const tone = outcomes[event.outcome]?.tone || "neutral";
    const text = outcomeText(event);
    return (
        <Badge id={id} className="etiqueta-resultado" tone={tone} title={text}>
            {showIcon && <Icon name={outcomes[event.outcome]?.icon || "remove"} />}
            <span>{text}</span>
        </Badge>
    );
}

function AuditValue({ label, id, children, fullWidth = false }) {
    return (
        <div className={`audit-value${fullWidth ? " audit-value-wide" : ""}`}>
            <span>{label}</span>
            <strong id={id}>{children}</strong>
        </div>
    );
}

function CopyableAuditValue({ label, id, value, copyId, onMessage, fallback = "—" }) {
    const identifier = useRef(null);
    const timeout = useRef(null);
    const [copied, setCopied] = useState(false);

    useEffect(() => () => clearTimeout(timeout.current), []);

    async function copy() {
        try {
            await navigator.clipboard.writeText(value);
            if (!identifier.current) return;
            onMessage("Identificador copiado.");
            setCopied(true);
            clearTimeout(timeout.current);
            timeout.current = setTimeout(() => setCopied(false), 1800);
        } catch {
            if (!identifier.current) return;
            onMessage("No se pudo copiar. Selecciona el identificador completo para copiarlo manualmente.");
            const range = document.createRange();
            range.selectNodeContents(identifier.current);
            const selection = window.getSelection();
            selection?.removeAllRanges();
            selection?.addRange(range);
        }
    }

    return (
        <div className="audit-value audit-value-wide">
            <span>{label}</span>
            <div className="audit-value-copy">
                <strong id={id} ref={identifier}>{value || fallback}</strong>
                {value && (
                    <Button id={copyId} variant="secondary" iconOnly aria-label={`Copiar ${label}`} onClick={copy}>
                        <Icon name={copied ? "check" : "content_copy"} />
                    </Button>
                )}
            </div>
        </div>
    );
}

export default function AuditDetail({ event, onClose, onFollowAlert, returnFocusRef }) {
    const closeRef = useRef(null);
    const [clipboardMessage, setClipboardMessage] = useState("");
    const actor = actorText(event);
    const hasNamedActor = event.actor_id && actor !== `Usuario (${event.actor_id})`;
    const contingency = event.contingencia === true ? "Sí" : event.contingencia === false ? "No" : "No registrado";
    const storage = event.storage;

    return (
        <Dialog open onClose={onClose} title="Detalle del evento" className="audit-dialog" initialFocusRef={closeRef} returnFocusRef={returnFocusRef}>
            <div id="panelDetalle">
                <header className="audit-dialog-header">
                    <h2 id="tituloDetalleEvento">Detalle del evento</h2>
                    <Button id="cerrarDetalle" ref={closeRef} variant="secondary" iconOnly aria-label="Cerrar" onClick={onClose}><Icon name="close" /></Button>
                </header>
                <div className="audit-detail-summary">
                    <AuditOutcome id="detalleResultado" event={event} />
                    <h3 id="detalleAccion">{actionText(event.action)}</h3>
                    <p id="explicacionEvento">{auditActions[event.action]?.[1] || "Evento registrado en el sistema."} Resultado de ejecución: {outcomeText(event).toLowerCase()}.</p>
                    <time id="detalleFecha" dateTime={event.timestamp}>{auditTime(event.timestamp)}</time>
                </div>
                <section className="audit-detail-section">
                    <h3>Contexto del evento</h3>
                    <div className="audit-detail-grid">
                        <AuditValue label="Responsable" id="detalleActor">{hasNamedActor ? `${actor} · ${event.actor_id}` : actor}</AuditValue>
                        <AuditValue label="Canal" id="detalleCanal">{channelText(event.channel)}</AuditValue>
                        <CopyableAuditValue label="ID de alerta" id="detalleAlerta" value={event.alerta_id} copyId="copiarAlerta" onMessage={setClipboardMessage} />
                    </div>
                    {event.alerta_id && (
                        <div className="audit-follow-alert">
                            <Button variant="primary" id="verEventosAlerta" onClick={() => onFollowAlert(event.alerta_id)}>
                                Seguir esta alerta en el período <Icon name="arrow_forward" />
                            </Button>
                            <p id="alcanceRelacion">Consulta la misma alerta en todas las categorías y resultados. Se conserva el período y el orden.</p>
                        </div>
                    )}
                </section>
                {storage && (
                    <section className="audit-detail-section" id="seccionAlmacenamiento">
                        <h3>Limpieza de almacenamiento</h3>
                        <p id="detalleAlmacenamiento">
                            {storage.source === "manual" ? "Manual" : "Automática"} · {storage.freed_bytes} bytes liberados · {storage.removed} archivos eliminados · {storage.failures} fallos · {storage.protected} protegidos · {storage.checkpoints} contextos retirados
                        </p>
                    </section>
                )}
                {event.notification && (
                    <section className="audit-detail-section" id="seccionNotificacion">
                        <h3>Proceso de notificación</h3>
                        <div className="audit-detail-grid" id="detalleNotificacion">
                            {notificationDetails(event.notification).map(([label, value], index) => (
                                <AuditValue label={label} key={label} fullWidth={index === 0}>{value ?? "No registrado"}</AuditValue>
                            ))}
                        </div>
                    </section>
                )}
                <details className="audit-detail-section audit-technical" open>
                    <summary>Datos técnicos</summary>
                    <div className="audit-detail-grid">
                        <CopyableAuditValue label="ID del evento" id="detalleId" value={event.event_id} copyId="copiarEvento" onMessage={setClipboardMessage} fallback="No registrado" />
                        <AuditValue label="ID de sesión" id="detalleSesion" fullWidth>{event.sesion_id || "—"}</AuditValue>
                        <AuditValue label="Secuencia" id="detalleSecuencia">{event.sequence ?? "—"}</AuditValue>
                        <AuditValue label="Duración" id="detalleDuracion">{event.duration_ms == null ? "—" : `${event.duration_ms} ms`}</AuditValue>
                        <AuditValue label="Código de error técnico" id="detalleError">{event.error_code || "—"}</AuditValue>
                        <AuditValue label="Uso del respaldo" id="detalleContingencia">{contingency}</AuditValue>
                        <AuditValue label="Acción registrada" id="detalleAccionTecnica" fullWidth>{event.action || "No registrada"}</AuditValue>
                    </div>
                </details>
                <p className="audit-detail-footnote">El resultado operativo no indica severidad clínica.</p>
                <p id="estadoCopia" className="audit-copy-feedback" role="status">{clipboardMessage}</p>
            </div>
        </Dialog>
    );
}
