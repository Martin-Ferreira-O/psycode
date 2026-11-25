import { useCallback, useRef, useState } from "react";
import { apiGetDatos, ErrorSolicitud } from "../api.js";
import { codigoAlertaVisible, formatearBox, formatearFecha, formatearHora, formatearTipoRiesgo, obtenerEtiquetaEvaluacion } from "../format.js";
import { Badge, Button, Dialog, Icon, Status } from "../ui.jsx";
import { alertLevel, alertUrl, evaluationChoices, withEvaluation } from "./alerts.js";
import { useResource } from "./resources.js";

export function SeverityBadge({ alert }) {
    const { text, tone, number } = alertLevel(alert);
    return <Badge tone={tone} aria-label={number ? `Nivel ${number}: ${text}` : text}>{text}</Badge>;
}

export function DetailButton({ label, onClick, icon = "chevron_right", ...props }) {
    return (
        <Button variant="secondary" iconOnly aria-label={label} title="Ver detalle" onClick={onClick} {...props}>
            <Icon name={icon} />
        </Button>
    );
}

function DetailValue({ label, id, children }) {
    return (
        <div className="alert-detail-value">
            <span>{label}</span>
            <strong id={id}>{children}</strong>
        </div>
    );
}

function dateTime(value) {
    return value ? `${formatearFecha(value)} · ${formatearHora(value)}` : "No disponible";
}

function EvidenceMetadata({ evidence, compact = false }) {
    const score = evidence.puntaje == null ? null : (
        <>
            Puntaje de la categoría {evidence.puntaje.toLocaleString("es-CL")}
            {evidence.umbral != null && <> · Umbral {evidence.umbral.toLocaleString("es-CL")}</>}
        </>
    );
    return (
        <>
            <p>
                Nivel {evidence.nivel_matriz} de la matriz
                {compact ? score && <> · {score}</> : <> · Intervalo {evidence.inicio}–{evidence.fin} s</>}
            </p>
            {evidence.plazo && <p>Plazo expresado en la frase: {evidence.plazo}</p>}
            {!compact && score && <p>{score}</p>}
        </>
    );
}

function FragmentEvidence({ analysis, alertIsTest, transcriptOpen, toggleTranscript, transcript }) {
    const evidence = Array.isArray(analysis?.evidencias)
        ? [...analysis.evidencias].sort((a, b) => a.inicio - b.inicio || a.fin - b.fin)
        : [];
    const pending = Array.isArray(analysis?.evidencias_pendientes) ? analysis.evidencias_pendientes : [];
    return (
        <>
            {analysis && evidence.length === 0 && (
                <section className="alert-detail-section" aria-label="Evidencia de la señal">
                    <h3>{analysis.categoria}</h3>
                    <EvidenceMetadata evidence={analysis} />
                </section>
            )}
            <section id="seccionTranscripcion" className="alert-detail-section" aria-labelledby="tituloTranscripcion">
                <h3 id="tituloTranscripcion">{evidence.length ? "Evidencias del fragmento" : "Fragmento de transcripción"}</h3>
                {alertIsTest && (
                    <Button aria-expanded={transcriptOpen} aria-controls="detalleTranscripcion" onClick={toggleTranscript}>
                        {transcriptOpen ? "Ocultar transcripción" : "Ver transcripción"}
                    </Button>
                )}
                {evidence.length ? (
                    <ol id="detalleTranscripcion" className="alert-evidence-list" role="list" hidden={alertIsTest && !transcriptOpen}>
                        {evidence.map((item, index) => (
                            <li key={`${item.inicio}-${item.fin}-${item.nivel_matriz}-${index}`}>
                                <div className="alert-evidence-heading">
                                    <h4>{item.categoria}</h4>
                                    <span className="alert-evidence-interval">{item.inicio}–{item.fin} s</span>
                                </div>
                                <EvidenceMetadata evidence={item} compact />
                                <blockquote className="alert-detail-transcript">{item.texto}</blockquote>
                                {(item.contexto_anterior || item.contexto_posterior) && (
                                    <details className="alert-evidence-context">
                                        <summary>Contexto cercano</summary>
                                        <div className="alert-evidence-context-text">
                                            {item.contexto_anterior && <p><strong>Antes:</strong> {item.contexto_anterior}</p>}
                                            {item.contexto_posterior && <p><strong>Después:</strong> {item.contexto_posterior}</p>}
                                        </div>
                                    </details>
                                )}
                            </li>
                        ))}
                    </ol>
                ) : (
                    <p id="detalleTranscripcion" className="alert-detail-transcript" hidden={alertIsTest && !transcriptOpen}>
                        {transcript.trim() ? transcript : "Esta alerta no tiene un fragmento de transcripción disponible."}
                    </p>
                )}
                {pending.length > 0 && (
                    <details className="alert-evidence-pending">
                        <summary>Tramos pendientes de verificar ({pending.length})</summary>
                        <ul>
                            {pending.map((item, index) => (
                                <li key={`${item.start}-${item.end}-${index}`}>
                                    {item.start}–{item.end} s · {item.code === "JEV_BELOW_THRESHOLD" ? "Bajo el umbral" : "Evidencia incierta"}
                                </li>
                            ))}
                        </ul>
                    </details>
                )}
            </section>
        </>
    );
}

export default function AlertDetail({ id, onClose, returnFocusRef, evaluation, saving, onEvaluate }) {
    const closeRef = useRef(null);
    const [option, setOption] = useState("");
    const [feedback, setFeedback] = useState(null);
    const [transcriptOpen, setTranscriptOpen] = useState(false);
    const load = useCallback(async (signal) => {
        const detail = await apiGetDatos(alertUrl(id), { signal });
        if (detail?.alerta_id !== id) throw new ErrorSolicitud();
        return detail;
    }, [id]);
    const { data, loading, error, reload } = useResource(load);
    const alert = data && withEvaluation(data, evaluation);
    const pending = alert?.estado_evaluacion === "pendiente";
    const canEvaluate = pending && Boolean(onEvaluate) && !feedback?.conflict;
    const registered = alert && !pending;
    const transcript = typeof alert?.descripcion === "string" ? alert.descripcion : "";
    const title = alert ? codigoAlertaVisible(alert.alerta_id) : "Detalle de alerta";

    async function submit(event) {
        event.preventDefault();
        if (saving || !canEvaluate) return;
        if (!option) {
            setFeedback({ type: "error", text: "Selecciona una opción antes de guardar." });
            return;
        }
        setFeedback(null);
        try {
            const result = await onEvaluate(alert.alerta_id, option);
            if (result) {
                setFeedback({
                    type: result.conflict ? "error" : "exito",
                    text: result.conflict
                        ? "La alerta ya tiene una evaluación. Se actualizó el detalle."
                        : "Evaluación registrada.",
                });
            }
        } catch (error) {
            setFeedback({ type: "error", error, conflict: error.evaluationConflict });
        }
    }

    function retry() {
        setFeedback(null);
        setOption("");
        reload();
    }

    return (
        <Dialog open onClose={onClose} title={title} className="alert-detail-dialog" initialFocusRef={closeRef} returnFocusRef={returnFocusRef}>
            <div id="modalDetalle">
                <header className="alert-detail-header">
                    <div>
                        <span>Detalle de alerta</span>
                        <h2 id="tituloModal">{title}</h2>
                        {alert?.es_prueba && <Badge tone="warning">Alerta de prueba</Badge>}
                    </div>
                    <Button ref={closeRef} iconOnly variant="secondary" aria-label="Cerrar" onClick={onClose} data-cerrar-modal>
                        <Icon name="close" />
                    </Button>
                </header>
                <div className="alert-detail-body">
                    {loading && <Status type="carga">Cargando detalle…</Status>}
                    {error && <Status type="error" error={error} onRetry={retry} />}
                    {feedback && !canEvaluate && (
                        <div id="estadoDetalle">
                            <Status type={feedback.type} error={feedback.error} messages={{ 404: "No encontramos la evaluación registrada." }}
                                onRetry={feedback.type === "error" ? retry : undefined}>
                                {feedback.text}
                            </Status>
                        </div>
                    )}
                    {alert && (
                        <>
                            <div className="alert-detail-grid">
                                <DetailValue label="Box" id="detalleBox">{formatearBox(alert.box)}</DetailValue>
                                <DetailValue label="Tipo de riesgo" id="detalleTipo">{formatearTipoRiesgo(alert.tipo_riesgo)}</DetailValue>
                                <DetailValue label="Prioridad de revisión" id="detalleNivel"><SeverityBadge alert={alert} /></DetailValue>
                                <DetailValue label="Fecha y hora" id="detalleFecha">{dateTime(alert.fecha_hora)}</DetailValue>
                                <DetailValue label="Estado" id="detalleEstado">{pending ? "Pendiente" : obtenerEtiquetaEvaluacion(alert.estado_evaluacion)}</DetailValue>
                                <DetailValue label="Sesión" id="detalleSesion">{alert.sesion_id || "—"}</DetailValue>
                            </div>
                            <FragmentEvidence analysis={alert.analisis} alertIsTest={alert.es_prueba} transcript={transcript}
                                transcriptOpen={transcriptOpen} toggleTranscript={() => setTranscriptOpen(open => !open)} />
                            {canEvaluate && (
                                <form id="formularioEvaluacion" className="alert-detail-section" onSubmit={submit}>
                                    <fieldset>
                                        <legend>Evaluar detección</legend>
                                        <p>La evaluación se puede registrar una sola vez.</p>
                                        <div className="alert-detail-options">
                                            {Object.entries(evaluationChoices).map(([value, description]) => (
                                                <label key={value}>
                                                    <input type="radio" name="evaluacion" value={value} checked={option === value} onChange={() => setOption(value)} disabled={saving} />
                                                    <span><strong>{obtenerEtiquetaEvaluacion(value)}</strong>
                                                        {alert.es_prueba && value === "correcta" ? "La detección coincide con el escenario simulado." : description}
                                                    </span>
                                                </label>
                                            ))}
                                        </div>
                                    </fieldset>
                                    {feedback && (
                                        <Status id="mensajeEvaluacion" type="error" error={feedback.error} messages={{
                                                400: "El identificador de alerta o la evaluación no son válidos.",
                                                404: "La alerta ya no existe.",
                                            }}>
                                                {feedback.text}
                                            </Status>
                                    )}
                                    <Button variant="primary" id="guardarEvaluacion" type="submit" busy={saving} busyLabel="Guardando…">Guardar evaluación</Button>
                                </form>
                            )}
                            {registered && (
                                <section id="evaluacionRegistrada" className="alert-detail-section">
                                    <h3>Evaluación registrada</h3>
                                    <div className="alert-detail-grid">
                                        <DetailValue label="Resultado" id="resultadoEvaluacion">
                                            {obtenerEtiquetaEvaluacion(alert.evaluacion?.evaluacion ?? alert.evaluacion?.resultado ?? alert.estado_evaluacion)}
                                        </DetailValue>
                                        <DetailValue label="Evaluado por" id="evaluadoPor">{alert.evaluacion?.usuario || "No disponible"}</DetailValue>
                                        <DetailValue label="Fecha de evaluación" id="fechaEvaluacion">{dateTime(alert.evaluacion?.fecha_hora)}</DetailValue>
                                    </div>
                                    <p className="alert-detail-note">Esta evaluación ya fue guardada y no puede modificarse.</p>
                                </section>
                            )}
                        </>
                    )}
                </div>
            </div>
        </Dialog>
    );
}
