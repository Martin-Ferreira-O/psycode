import { useEffect, useRef, useState } from "react";
import { codigoAlertaVisible, formatearFecha, formatearHora, obtenerEtiquetaEvaluacion, obtenerResultado } from "../format.js";
import { PageHeader } from "../layout.jsx";
import { Badge, Button, DataTable, Status } from "../ui.jsx";
import AlertDetail, { DetailButton } from "../monitor/AlertDetail.jsx";
import { ALERTS_URL, ALERT_PAGE_SIZE } from "../monitor/alerts.js";
import { usePage } from "../monitor/resources.js";

const systemRecords = {
    correcta: "Detección confirmada",
    falso_positivo: "Error del modelo",
    neutro: "Indeterminada",
};

const resultTones = { correcta: "success", falso_positivo: "danger", neutro: "neutral" };

export default function Evaluaciones() {
    const [offset, setOffset] = useState(0);
    const [selected, setSelected] = useState(null);
    const titleRef = useRef(null);
    const detailTrigger = useRef(null);
    const shouldFocus = useRef(false);
    const { data, loading, error, reload } = usePage(ALERTS_URL, "revisadas=true", offset, ALERT_PAGE_SIZE);

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
    const summary = loading ? "Consultando evaluaciones…"
        : error ? "No se pudieron consultar las evaluaciones."
        : pages > 1 ? `Mostrando ${pageOffset + 1}–${pageOffset + data.items.length} de ${total} evaluaciones`
        : total === 1 ? "1 evaluación registrada" : `${total} evaluaciones registradas`;

    function movePage(newOffset) {
        shouldFocus.current = true;
        setOffset(newOffset);
    }

    function retry() {
        shouldFocus.current = true;
        reload();
    }

    return (
        <>
            <PageHeader title="Registro de evaluaciones" description="Consulta las alertas que ya fueron revisadas y revisa el resultado, junto a la fecha de cada evaluación." />
            <section className="panel-alertas panel-evaluaciones" aria-busy={loading}>
                <div className="panel-cabecera">
                    <div>
                        <h2 id="tituloEvaluaciones" ref={titleRef} tabIndex={-1}>Evaluaciones registradas</h2>
                        <p id="resultadoEvaluaciones" role="status">{summary}</p>
                    </div>
                </div>
                {loading && <Status id="estadoVacioEvaluaciones" type="carga">Cargando evaluaciones…</Status>}
                {error && <Status id="estadoVacioEvaluaciones" type="error" error={error} messages={{ 404: "No encontramos el registro de evaluaciones solicitado." }} onRetry={retry} />}
                {data && data.items.length === 0 && <Status id="estadoVacioEvaluaciones" type="vacio">Todavía no existen alertas evaluadas.</Status>}
                {Boolean(data?.items.length) && (
                    <DataTable stickyActions className="monitor-table monitor-table-alerts" label="Evaluaciones registradas" wrapperId="tablaEvaluacionesContenedor">
                        <thead>
                            <tr>
                                <th scope="col">Alerta</th>
                                <th scope="col">Evaluación seleccionada</th>
                                <th scope="col">Registro del sistema</th>
                                <th scope="col">Estado</th>
                                <th scope="col">Fecha de evaluación</th>
                                <th scope="col">Acción</th>
                            </tr>
                        </thead>
                        <tbody id="tablaEvaluaciones">
                            {data.items.map((alert) => {
                                const result = obtenerResultado(alert);
                                const date = alert.evaluacion?.fecha_hora;
                                const code = codigoAlertaVisible(alert.alerta_id);
                                return (
                                    <tr key={alert.alerta_id}>
                                        <td><strong className="monitor-id">{code}</strong></td>
                                        <td><Badge tone={resultTones[result]}>{obtenerEtiquetaEvaluacion(result)}</Badge></td>
                                        <td>{systemRecords[result] || "Indeterminada"}</td>
                                        <td><Badge tone="success">Revisada</Badge></td>
                                        <td><div className="monitor-cell-stack">{formatearFecha(date)}<small>{formatearHora(date)}</small></div></td>
                                        <td><DetailButton label={`Ver detalle de ${code}`} data-alerta={alert.alerta_id} onClick={(event) => {
                                            detailTrigger.current = event.currentTarget;
                                            setSelected(alert.alerta_id);
                                        }} /></td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </DataTable>
                )}
                {pages > 1 && (
                    <nav id="paginacionEvaluaciones" className="monitor-pagination" aria-label="Paginación de evaluaciones">
                        <span id="paginaEvaluaciones">Página {page} de {pages}</span>
                        <div className="monitor-pagination-buttons">
                            <Button id="evaluacionesAnterior" variant="secondary" disabled={page === 1} onClick={() => movePage(pageOffset - ALERT_PAGE_SIZE)}>Anterior</Button>
                            <Button id="evaluacionesSiguiente" variant="secondary" disabled={page === pages} onClick={() => movePage(pageOffset + ALERT_PAGE_SIZE)}>Siguiente</Button>
                        </div>
                    </nav>
                )}
                <div className="pie-evaluaciones">Cada resultado queda asociado a la alerta y se conserva como parte de la bitácora.</div>
            </section>
            {selected && <AlertDetail key={selected} id={selected} onClose={() => setSelected(null)} returnFocusRef={detailTrigger} />}
        </>
    );
}
