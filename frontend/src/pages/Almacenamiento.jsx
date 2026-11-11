import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { apiGetDatos, apiPost, leerRespuesta } from "../api.js";
import { PageHeader } from "../layout.jsx";
import { Button, Dialog, Skeleton, Status } from "../ui.jsx";

const ENDPOINT = "/api/v1/almacenamiento";
const RESULTADOS = {
    success: "Completada",
    partial: "Completada con fallos",
    failure: "Fallida",
    interrupted: "Interrumpida; se reintentará",
    running: "En ejecución",
};
const PROTECCIONES = {
    minimo_24_horas: "conservación mínima de 24 h",
    analisis_activo: "análisis activo",
    recuperable: "procesamiento recuperable",
    temporal_reciente: "carga reciente",
    archivo_en_uso: "archivo en uso",
};
const UNIDADES = ["B", "KiB", "MiB", "GiB", "TiB"];
const formatoNumero = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });

function bytes(valor) {
    if (!Number.isFinite(valor)) return "—";
    let indice = 0;
    while (valor >= 1024 && indice < UNIDADES.length - 1) {
        valor /= 1024;
        indice++;
    }
    return `${formatoNumero.format(valor)} ${UNIDADES[indice]}`;
}

function archivos(cantidad) {
    return `${cantidad} ${cantidad === 1 ? "archivo" : "archivos"}`;
}

function fecha(valor) {
    return valor ? new Date(valor).toLocaleString("es-CL") : "Sin ejecuciones registradas";
}

function mensajeError(error) {
    if (error?.estado === 403) return "Solo los administradores pueden acceder al almacenamiento del servidor.";
    if (error?.estado === 409) return "La vista previa venció o hay otra limpieza activa. Actualiza el estado y solicita otra vista previa.";
    return "No se pudo completar la solicitud. Actualiza el estado antes de volver a intentar la limpieza.";
}

function presentarError(error) {
    return { type: "error", texto: mensajeError(error) };
}

function resumenLimpieza(resultado) {
    const eliminados = resultado.removed === 1 ? "eliminado" : "eliminados";
    return `${bytes(resultado.freed_bytes)} liberados · ${archivos(resultado.removed)} ${eliminados} · ${resultado.failures} fallos · ${resultado.protected} protegidos al revalidar. Los borrados fallidos se reintentarán automáticamente.`;
}

function DatosAlmacenamiento({ info, ocupado, previsualizar, liberarRef }) {
    const metricas = [
        ["Ocupado en el volumen", "used_bytes"],
        ["Disponible en el volumen", "available_bytes"],
        ["Material de procesamiento", "managed_bytes"],
        ["Liberable ahora", "reclaimable_bytes"],
        ["Archivos protegidos", "protected_bytes"],
    ];
    const resumen = (
        <dl className="metricas-almacenamiento">
            {metricas.map(([nombre, campo]) => (
                <div key={campo}>
                    <dt>{nombre}</dt>
                    <dd>{info ? bytes(info[campo]) : <Skeleton className="ui-skeleton-count" />}
                        {info && campo === "protected_bytes" && ` · ${archivos(info.protected_files)}`}
                    </dd>
                </div>
            ))}
        </dl>
    );
    const ultima = info?.last_run;
    const resultado = ultima
        ? `${RESULTADOS[ultima.outcome] || ultima.outcome} · ${bytes(ultima.freed_bytes)} liberados · ${ultima.failures} fallos`
        : "Pendiente";
    const retraso = info?.delay_seconds > 0
        ? `${Math.ceil(info.delay_seconds / 60)} minutos de retraso. Revisa el servicio de limpieza.`
        : "Sin retraso";
    const ejecucion = [
        ["Última ejecución", ultima ? fecha(ultima.started_at) : "Aún no se ha ejecutado"],
        ["Resultado", resultado],
        ["Próxima ejecución prevista", `${fecha(info?.next_run_at)} · cada 15 minutos`],
        ["Retraso", retraso],
    ];
    const motivos = Object.entries(info?.reasons ?? {})
        .map(([razon, cantidad]) => `${cantidad}: ${PROTECCIONES[razon] || "protegidos"}`).join(" · ");
    return (
        <div aria-busy={!info || ocupado}>
            {resumen}
            <p className="ayuda-configuracion">{info ? motivos || "No hay archivos protegidos en este momento." : <Skeleton className="ui-skeleton-count" />}</p>
            <p className="ayuda-configuracion">El audio se conserva al menos 24 horas desde su recepción central. Las cargas, los análisis activos y los pendientes recuperables están protegidos. Los fallos requieren revisión y vencen a los 7 días de la última recepción, cuando la recepción está cerrada y no hay análisis activos.</p>
            <p className="ayuda-configuracion">Se conservan alertas, extractos, revisiones, bitácora, usuarios, configuración y agenda. El espacio del volumen incluye otros datos; esta limpieza solo gestiona sus propios fragmentos.</p>
            <h2 className="subtitulo-almacenamiento">Limpieza periódica</h2>
            <dl className="ejecucion-almacenamiento">
                {ejecucion.map(([nombre, valor]) => (
                    <Fragment key={nombre}><dt>{nombre}</dt><dd>{info ? valor : <Skeleton className="ui-skeleton-count" />}</dd></Fragment>
                ))}
            </dl>
            {info && (
                <>
                    <p className="ayuda-configuracion">
                        {info.pending_deletions} borrados pendientes · {info.intervention_deletions} requieren intervención · {info.stale_active_jobs || 0} análisis demorados · {info.review_jobs} trabajos en revisión · {info.expired_jobs} vencidos · {info.audit_pending} registros pendientes de bitácora.
                    </p>
                    <p className="ayuda-configuracion">
                        {info.encryption?.verified
                            ? "Cifrado de volúmenes y protección local de claves verificados."
                            : "Cifrado o protección de claves sin verificar. Revisa la verificación del almacenamiento antes de procesar material sensible."}
                    </p>
                    <div className="acciones-configuracion">
                        <p className="ayuda-configuracion">La vista previa muestra hasta 1000 archivos. Se comprueban nuevamente las protecciones antes de borrar.</p>
                        <Button ref={liberarRef} variant="primary" onClick={previsualizar} disabled={ocupado}>Liberar espacio</Button>
                    </div>
                </>
            )}
        </div>
    );
}

export default function Almacenamiento() {
    const [info, setInfo] = useState(null);
    const [vista, setVista] = useState(null);
    const [vencida, setVencida] = useState(false);
    const [operacion, setOperacion] = useState(null);
    const [aviso, setAviso] = useState({ type: "carga", texto: "Cargando almacenamiento…" });
    const solicitud = useRef(null);
    const cancelarRef = useRef(null);
    const liberarRef = useRef(null);

    const ejecutar = useCallback(async (tipo, accion) => {
        if (solicitud.current) return;
        const controlador = new AbortController();
        solicitud.current = controlador;
        setOperacion(tipo);
        try {
            await accion(controlador.signal);
        } finally {
            if (solicitud.current === controlador) solicitud.current = null;
            if (!controlador.signal.aborted) setOperacion(null);
        }
    }, []);

    const cargar = useCallback(async (signal, anuncio = null) => {
        try {
            const datos = await apiGetDatos(ENDPOINT, { signal });
            if (signal.aborted) return;
            setInfo(datos);
            setAviso(anuncio);
        } catch (error) {
            if (signal.aborted || error?.codigo === "SESION_FINALIZADA") return;
            setInfo(null);
            const fallo = presentarError(error);
            if (anuncio?.type === "exito") {
                fallo.texto = `${anuncio.texto} No se pudo actualizar el espacio del servidor.`;
            }
            setAviso(anuncio?.type === "error" ? anuncio : fallo);
        }
    }, []);

    const actualizar = useCallback(() => ejecutar("carga", (signal) => {
        setAviso({ type: "carga", texto: "Consultando almacenamiento…" });
        return cargar(signal);
    }), [ejecutar, cargar]);

    useEffect(() => {
        actualizar();
        return () => {
            solicitud.current?.abort();
            solicitud.current = null;
        };
    }, [actualizar]);

    const vistaAbierta = vista !== null;
    useEffect(() => {
        if (vistaAbierta) return undefined;
        const temporizador = setInterval(() => {
            if (!document.hidden) actualizar();
        }, 60000);
        return () => clearInterval(temporizador);
    }, [actualizar, vistaAbierta]);

    useEffect(() => {
        if (!vista) return undefined;
        const temporizador = setTimeout(() => setVencida(true), Math.max(0, vista.vence - Date.now()));
        return () => clearTimeout(temporizador);
    }, [vista]);

    function previsualizar() {
        return ejecutar("vista", async (signal) => {
            setAviso({ type: "carga", texto: "Calculando vista previa…" });
            try {
                const datos = await leerRespuesta(await apiPost(`${ENDPOINT}/vista-previa`, {}, { signal }));
                if (signal.aborted) return;
                setVencida(false);
                setVista({ ...datos, vence: Date.now() + datos.expires_in_seconds * 1000 });
                setAviso(null);
            } catch (error) {
                if (!signal.aborted && error?.codigo !== "SESION_FINALIZADA") setAviso(presentarError(error));
            }
        });
    }

    function limpiar() {
        if (!vista?.preview_token || vencida) return;
        if (Date.now() >= vista.vence) {
            setVencida(true);
            return;
        }
        return ejecutar("limpieza", async (signal) => {
            let anuncio;
            try {
                const respuesta = await apiPost(`${ENDPOINT}/liberar`, { preview_token: vista.preview_token }, { signal });
                anuncio = { type: "exito", texto: resumenLimpieza(await leerRespuesta(respuesta)) };
            } catch (error) {
                if (signal.aborted || error?.codigo === "SESION_FINALIZADA") return;
                anuncio = presentarError(error);
            }
            if (signal.aborted) return;
            await cargar(signal, anuncio);
            if (!signal.aborted) setVista(null);
        });
    }

    const ocupado = operacion !== null;
    const limpiando = operacion === "limpieza";
    const cargaInicial = !info && aviso?.type === "carga";
    return (
        <>
            <PageHeader title="Almacenamiento del servidor"
                description="Consulta el espacio y libera material de procesamiento que ya cumplió su conservación.">
                <Button variant="secondary" href="/configuracion-operativa">Volver a Configuración operativa</Button>
            </PageHeader>
            <section className="panel-configuracion" aria-labelledby="tituloEspacio">
                <div className="configuracion-cabecera">
                    <h2 id="tituloEspacio">Espacio del servidor</h2>
                    <Button variant="secondary" onClick={actualizar} disabled={ocupado}>Actualizar</Button>
                </div>
                {aviso && !cargaInicial && <Status type={aviso.type}>{aviso.texto}</Status>}
                {(info || cargaInicial) && <DatosAlmacenamiento info={info} ocupado={ocupado} previsualizar={previsualizar} liberarRef={liberarRef} />}
            </section>
            <Dialog open={vistaAbierta} onClose={() => setVista(null)} title="Vista previa de limpieza"
                className="dialogo-almacenamiento" busy={limpiando}
                initialFocusRef={cancelarRef} returnFocusRef={liberarRef}>
                {vista && (
                    <>
                        <h2>Vista previa de limpieza</h2>
                        <p>Se podrán liberar {bytes(vista.preview_bytes)} en {archivos(vista.preview_files)}. Permanecerán protegidos {bytes(vista.protected_bytes)}. Las alertas y los extractos seguirán disponibles.</p>
                        <p>También se retira contexto de procesamiento de sesiones cerradas según la misma política automática. Las protecciones se revalidarán al confirmar. Esta vista previa vence en 5 minutos.</p>
                        {vencida && !limpiando && <Status type="error">La vista previa venció. Cancela y solicita otra.</Status>}
                        <div className="acciones-configuracion">
                            <Button ref={cancelarRef} variant="secondary" onClick={() => setVista(null)} disabled={limpiando}>
                                Cancelar
                            </Button>
                            <Button variant="danger" onClick={limpiar} busy={limpiando} busyLabel="Limpiando…"
                                disabled={!vista.preview_token || vencida}>
                                Confirmar limpieza
                            </Button>
                        </div>
                    </>
                )}
            </Dialog>
        </>
    );
}
