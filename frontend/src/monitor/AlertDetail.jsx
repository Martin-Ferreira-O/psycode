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

export default function AlertDetail({ id, onClose, returnFocusRef, evaluation, saving, onEvaluate }) {
    const closeRef = useRef(null);
    const [option, setOption] = useState("");
    const [feedback, setFeedback] = useState(null);
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
                                <DetailValue label="Nivel" id="detalleNivel"><SeverityBadge alert={alert} /></DetailValue>
                                <DetailValue label="Fecha y hora" id="detalleFecha">{dateTime(alert.fecha_hora)}</DetailValue>
                                <DetailValue label="Estado" id="detalleEstado">{pending ? "Pendiente" : obtenerEtiquetaEvaluacion(alert.estado_evaluacion)}</DetailValue>
                                <DetailValue label="Sesión" id="detalleSesion">{alert.sesion_id || "—"}</DetailValue>
                            </div>
                            {!alert.es_prueba && <section id="seccionTranscripcion" className="alert-detail-section" aria-labelledby="tituloTranscripcion">
                                <h3 id="tituloTranscripcion">Fragmento de transcripción</h3>
                                <p id="detalleTranscripcion" className="alert-detail-transcript">
                                    {transcript.trim() ? transcript : "Esta alerta no tiene un fragmento de transcripción disponible."}
                                </p>
                            </section>}
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
