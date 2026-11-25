import { useEffect, useState } from "react";
import { apiGetDatos } from "../api.js";
import { Badge, DataTable, Icon } from "../ui.jsx";

export const CAMPOS_MODELOS = ["jev_threshold", "speechmatics_model"];
export const CAMPOS_SMILE = [
    "smile_collector_id", "smile_source", "smile_url", "smile_interval", "smile_timeout",
    "smile_request_timeout", "smile_format", "smile_boxes",
];

const LIMITES = {
    smile_interval: [1, 86400],
    smile_timeout: [1, 3600],
    smile_request_timeout: [1, 300],
};

const MODELOS = {
    enhanced: {
        nombre: "Enhanced", recomendado: true,
        beneficio: "Prioriza la precisión al transcribir el diálogo terapéutico. Usa el diccionario de términos de psicología de Psycode.",
    },
    standard: {
        nombre: "Standard",
        beneficio: "Para transcribir más rápido sesiones con voces claras y poco ruido de fondo.",
    },
    "melia-1": {
        nombre: "Melia 1",
        beneficio: "Para sesiones en las que predomina el relato del paciente en lenguaje cotidiano.",
    },
    "oak-1": {
        nombre: "Oak 1 Medical",
        beneficio: "Para sesiones en las que se mencionan diagnósticos, medicamentos o abreviaturas clínicas.",
    },
};

const USD = new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD", currencyDisplay: "code", useGrouping: "always" });
const USD_HORA = new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD", currencyDisplay: "code", maximumFractionDigits: 4 });
const FECHA_TARIFAS = new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeZone: "America/Santiago" });
const NUMERO = new Intl.NumberFormat("es-CL", { useGrouping: "always", maximumFractionDigits: 2 });
const PUNTAJE_JEV = new Intl.NumberFormat("es-CL", { minimumFractionDigits: 2, maximumFractionDigits: 20 });
const UMBRAL_INICIAL_JEV = 0.55;
const PASOS_UMBRAL_JEV = 20;
const MINUTOS_POR_SESION = 45;
const HORAS_POR_SESION = MINUTOS_POR_SESION / 60;
const BOXES_SPEECHMATICS = 5;
const MAX_SESIONES_POR_BOX = 9;
const MAX_DIAS_HABILES = 23;
const UMBRAL_DESCUENTO = 500;
const PORCENTAJE_DESCUENTO = 20;

function explicarUmbralJev(umbral) {
    if (umbral === 0) return "Todos los puntajes pasan este filtro, incluso los que están en cero.";
    if (umbral <= 0.15) return "Pasan incluso señales muy débiles. Pueden aparecer muchas alertas por frases ambiguas.";
    if (umbral <= 0.25) return "Deja pasar señales débiles. Puede ayudar a captar alusiones indirectas y también generar alertas por frases ambiguas.";
    if (umbral <= 0.35) return "Filtra las señales más débiles y todavía deja pasar indicios sutiles.";
    if (umbral <= 0.45) return "Exige un indicio más claro. Algunas alusiones muy sutiles pueden quedar fuera.";
    if (umbral < UMBRAL_INICIAL_JEV) return "Queda cerca del ajuste inicial y deja pasar algunas señales adicionales.";
    if (umbral === UMBRAL_INICIAL_JEV) return "Umbral inicial de Psycode.";
    if (umbral <= 0.65) return "Sube un poco la exigencia. Algunas señales que pasaban con el ajuste inicial quedan fuera.";
    if (umbral <= 0.75) return "Solo pasan señales con puntajes altos. Pueden quedar fuera indicios reales con puntajes intermedios.";
    if (umbral === 1) return "Solo pasan las señales que reciben el puntaje máximo.";
    return "Exige un puntaje muy alto. Incluso algunas señales en frases explícitas pueden quedar fuera.";
}

export function prepararAjustes(formulario, vigente) {
    const opciones = formulario.options;
    const campos = CAMPOS_MODELOS.filter((campo) => formulario[campo] !== vigente[campo]);
    if (formulario.smile_legacy_active !== vigente.smile_legacy_active
        || CAMPOS_SMILE.some((campo) => JSON.stringify(formulario[campo]) !== JSON.stringify(vigente[campo]))) {
        campos.push(...CAMPOS_SMILE);
    }

    const errores = {};
    const payload = Object.fromEntries(campos.map((campo) => [campo, formulario[campo]]));
    if (campos.includes("jev_threshold")) {
        const valor = payload.jev_threshold;
        if (!Number.isFinite(valor) || valor < 0 || valor > 1) {
            errores.jev_threshold = ["Selecciona un valor entre 0 y 1."];
        }
    }
    if (!campos.includes("smile_collector_id")) return { payload, errores };

    const { smile_collector_id, smile_boxes, smile_url, smile_format, smile_source } = payload;
    if (formulario.smile_legacy_active) {
        errores.smile_collector_id = ["Selecciona un PC compatible o desactiva la designación anterior."];
    }
    if (smile_collector_id && !opciones.smile_collectors.some((pc) => pc.id === smile_collector_id)) {
        errores.smile_collector_id = ["Selecciona un PC con credencial activa."];
    }
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(smile_source)) {
        errores.smile_source = ["Usa solo letras ASCII, números, guiones o guiones bajos."];
    }
    if (smile_url || smile_collector_id) {
        try {
            const url = new URL(smile_url);
            if (!/^https:\/\//i.test(smile_url) || url.protocol !== "https:" || url.username || url.password
                || /[\s\\?#]/.test(smile_url) || /^https:\/\/[^/]*@/i.test(smile_url)
                || url.port === "0" || smile_url.length >= 2048 || !/\/index\.php\/*$/.test(url.pathname)) {
                throw new Error("URL inválida");
            }
        } catch {
            errores.smile_url = ["Ingresa una URL HTTPS terminada en /index.php/, sin credenciales ni parámetros."];
        }
    }
    if (!Object.hasOwn(opciones.smile_formats, smile_format)) errores.smile_format = ["Selecciona un formato disponible."];
    if (new Set(smile_boxes).size !== smile_boxes.length
        || smile_boxes.some((box) => !opciones.smile_boxes.includes(box))
        || (smile_collector_id && !smile_boxes.length)) {
        errores.smile_boxes = ["Selecciona los boxes que cubrirá el colector."];
    } else if (smile_collector_id && smile_format === "smile.excel.v1" && smile_boxes.length !== 1) {
        errores.smile_boxes = ["Selecciona un solo box para Excel."];
    }
    for (const [campo, [min, max]] of Object.entries(LIMITES)) {
        const valor = Number(payload[campo]);
        if (!Number.isInteger(valor) || valor < min || valor > max) {
            errores[campo] = [`Ingresa un número entero entre ${min} y ${max}.`];
        }
        payload[campo] = valor;
    }
    if (!errores.smile_request_timeout && payload.smile_request_timeout > payload.smile_timeout) {
        errores.smile_request_timeout = ["El tiempo de red debe ser igual o menor que el de ejecución."];
    }
    return { payload, errores };
}

export function Campo({ campo, titulo, errores, ayuda, className = "", children }) {
    const error = errores[campo]?.join(" ");
    return (
        <div className={`campo-configuracion ${className}`}>
            <label htmlFor={campo}>{titulo}</label>
            {children({
                id: campo, name: campo, "aria-invalid": error ? true : undefined,
                "aria-describedby": [ayuda && `${campo}-ayuda`, error && `${campo}-error`].filter(Boolean).join(" ") || undefined,
            })}
            {(ayuda || error) && (
                <div className="campo-configuracion-detalle">
                    {ayuda && <p className="ayuda-configuracion" id={`${campo}-ayuda`}>{ayuda}</p>}
                    {error && <p className="error-configuracion" id={`${campo}-error`}>{error}</p>}
                </div>
            )}
        </div>
    );
}

export function AjustesSmile({ formulario, vigente, actualizar, errores }) {
    const { options, smile_collector_id } = formulario;
    if (!options) return null;
    const vigentePC = options.smile_collectors.find((pc) => pc.id === vigente.smile_collector_id);
    const seleccionado = options.smile_collectors.find((pc) => pc.id === smile_collector_id);
    const cambio = (campo) => (evento) => actualizar(campo, evento.target.value);
    const numero = (campo, titulo) => (
        <Campo campo={campo} titulo={titulo} errores={errores}>
            {(props) => <input {...props} type="number" min={LIMITES[campo][0]} max={LIMITES[campo][1]} step={1}
                value={formulario[campo]} onChange={cambio(campo)} />}
        </Campo>
    );
    return (
        <>
            <fieldset className="grupo-configuracion">
                <legend>Conexión</legend>
                <p className="nota-configuracion">
                    <Icon name="info" />
                    <span>
                        {vigentePC ? `Colector vigente: ${vigentePC.name} (${vigentePC.box}).`
                            : vigente.smile_legacy_active ? "Hay una designación anterior. Selecciona un PC para gestionarlo desde esta página."
                                : vigente.smile_collector_id ? "El colector vigente ya no está disponible."
                                    : "No hay un colector designado."}
                        {" "}El PC elegido necesita las credenciales de Smile en su configuración local.
                    </span>
                </p>
                <div className="campos-configuracion">
                    <Campo campo="smile_collector_id" titulo="PC designado" errores={errores}
                        ayuda={seleccionado?.connected && !seleccionado.smile_config_supported
                            ? "Este PC necesita una actualización del agente para recibir la configuración desde la web." : undefined}>
                        {(props) => <select {...props} value={formulario.smile_legacy_active ? "legacy" : (smile_collector_id ?? "")}
                            onChange={(evento) => {
                                actualizar("smile_collector_id", evento.target.value || null);
                                actualizar("smile_legacy_active", false);
                            }}>
                            {formulario.smile_legacy_active && <option value="legacy" disabled>Designación anterior</option>}
                            <option value="">Sin colector</option>
                            {smile_collector_id && !options.smile_collectors.some((pc) => pc.id === smile_collector_id) &&
                                <option value={smile_collector_id} disabled>PC ya no disponible</option>}
                            {options.smile_collectors.map((pc) => (
                                <option key={pc.id} value={pc.id}>{pc.name} ({pc.box}) · {pc.connected ? "Conectado" : "Sin conexión"}</option>
                            ))}
                        </select>}
                    </Campo>
                    <Campo campo="smile_source" titulo="Identificador de la fuente" errores={errores}
                        ayuda="Conserva el identificador si ya hay salas vinculadas al catálogo.">
                        {(props) => <input {...props} maxLength={64} value={formulario.smile_source} onChange={cambio("smile_source")} />}
                    </Campo>
                    <Campo campo="smile_url" titulo="URL de Smile" errores={errores} className="campo-configuracion--ancho"
                        ayuda="Dirección HTTPS terminada en /index.php/.">
                        {(props) => <input {...props} type="url" maxLength={2047} value={formulario.smile_url} onChange={cambio("smile_url")} />}
                    </Campo>
                </div>
            </fieldset>
            <fieldset className="grupo-configuracion">
                <legend>Agenda y boxes</legend>
                <div className="campos-configuracion">
                    <Campo campo="smile_format" titulo="Formato de agenda" errores={errores}
                        ayuda="JSON permite varios boxes. Excel admite un solo box por reporte.">
                        {(props) => <select {...props} value={formulario.smile_format} onChange={cambio("smile_format")}>
                            {Object.entries(options.smile_formats).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>}
                    </Campo>
                </div>
                <fieldset className="alcance-smile" id="smile_boxes" tabIndex={-1}
                    aria-describedby={errores.smile_boxes ? "smile_boxes-ayuda smile_boxes-error" : "smile_boxes-ayuda"}>
                    <legend>Boxes incluidos en la recolección</legend>
                    <p className="ayuda-configuracion" id="smile_boxes-ayuda">Selecciona el alcance inicial del reporte. En JSON, el catálogo agrega las salas vinculadas a esta fuente.</p>
                    <div className="opciones-seleccion opciones-seleccion--boxes">
                        {options.smile_boxes.map((box) => (
                            <label className="seleccion-configuracion" key={box}>
                                <input type="checkbox" checked={formulario.smile_boxes.includes(box)} onChange={(evento) => {
                                    const seleccion = new Set(formulario.smile_boxes);
                                    if (evento.target.checked) seleccion.add(box);
                                    else seleccion.delete(box);
                                    actualizar("smile_boxes", options.smile_boxes.filter((item) => seleccion.has(item)));
                                }} />
                                <span>{box}</span>
                            </label>
                        ))}
                    </div>
                    {errores.smile_boxes && <p className="error-configuracion" id="smile_boxes-error">{errores.smile_boxes.join(" ")}</p>}
                </fieldset>
            </fieldset>
            <fieldset className="grupo-configuracion">
                <legend>Tiempos de recolección</legend>
                <div className="campos-configuracion campos-configuracion--tiempos">
                    {numero("smile_interval", "Intervalo de recolección (s)")}
                    {numero("smile_timeout", "Límite por ejecución (s)")}
                    {numero("smile_request_timeout", "Límite por solicitud HTTP (s)")}
                </div>
            </fieldset>
        </>
    );
}

function ComparadorSpeechmatics({ modelos, modeloSeleccionado, modeloActivo, seleccionar, error, activa }) {
    const [sesionesPorBox, setSesionesPorBox] = useState(String(MAX_SESIONES_POR_BOX));
    const [dias, setDias] = useState("22");
    const [catalogo, setCatalogo] = useState(null);
    useEffect(() => {
        if (!activa) return;
        const controlador = new AbortController();
        apiGetDatos("/api/v1/configuracion-operativa/speechmatics", { signal: controlador.signal })
            .then((datos) => {
                if (!Array.isArray(datos.models)) throw new Error("Catálogo inválido");
                if (!controlador.signal.aborted) setCatalogo(datos);
            })
            .catch(() => {
                if (!controlador.signal.aborted) {
                    setCatalogo((anterior) => anterior?.models.length ? { ...anterior, status: "stale" }
                        : { status: "unavailable", models: [] });
                }
            });
        return () => controlador.abort();
    }, [activa]);

    const publicados = new Map((catalogo?.models ?? []).map((modelo) => [modelo.id, modelo]));
    const ids = new Set([...modelos, ...publicados.keys(), modeloActivo, modeloSeleccionado].filter(Boolean));
    const filas = Array.from(ids, (id) => publicados.get(id) ?? { id, name: MODELOS[id]?.nombre ?? id });
    let estadoTarifas = "Consultando el catálogo de Speechmatics…";
    if (catalogo?.fetched_at) {
        const fecha = FECHA_TARIFAS.format(new Date(catalogo.fetched_at));
        estadoTarifas = catalogo.status === "stale"
            ? `No se pudieron actualizar las tarifas. Se muestran las últimas verificadas el ${fecha}.`
            : `Tarifas consultadas el ${fecha}.`;
    } else if (catalogo) {
        estadoTarifas = "No se pudieron verificar las tarifas de Speechmatics. Puedes seguir eligiendo el modelo.";
    }
    const diasHabiles = Number(dias);
    const diasValidos = dias !== "" && Number.isInteger(diasHabiles) && diasHabiles >= 0 && diasHabiles <= MAX_DIAS_HABILES;
    const errores = diasValidos ? {} : { estimacionDias: [`Ingresa entre 0 y ${MAX_DIAS_HABILES} días hábiles.`] };
    const horasDiarias = Number(sesionesPorBox) * BOXES_SPEECHMATICS * HORAS_POR_SESION;
    const horasMensuales = diasValidos ? horasDiarias * diasHabiles : null;
    const descuento = horasMensuales > UMBRAL_DESCUENTO ? PORCENTAJE_DESCUENTO : 0;

    return (
        <div className="configuracion-speechmatics">
            <fieldset className="seleccion-speechmatics" id="speechmatics_model" tabIndex={-1}
                aria-invalid={error ? true : undefined} aria-describedby={error ? "speechmatics_model-error" : undefined}>
                <legend><h3>Modelo de Speechmatics</h3></legend>
                {error && <p className="error-configuracion" id="speechmatics_model-error">{error}</p>}
                {filas.length > 0 ? <>
                    <p className="ayuda-configuracion">Elige un modelo para transcribir las sesiones de psicología en español chileno.</p>
                    <ul className="estimacion-speechmatics-modelos" role="list">
                        {filas.map(({ id: modelo, name }) => {
                            const { beneficio, recomendado } = MODELOS[modelo] ?? {};
                            const seleccionado = modelo === modeloSeleccionado;
                            const activo = modelo === modeloActivo;
                            const campo = `modelo-speechmatics-${modelo}`;
                            return (
                                <li key={modelo} className="estimacion-speechmatics-modelo"
                                    data-seleccionado={seleccionado || undefined}>
                                    <div className="estimacion-speechmatics-modelo-cabecera">
                                        <div className="estimacion-speechmatics-modelo-opcion">
                                            <input id={campo} name="speechmatics_model" type="radio" value={modelo}
                                                checked={seleccionado} onChange={() => seleccionar(modelo)}
                                                aria-describedby={[beneficio && `${campo}-beneficio`, (activo || seleccionado || recomendado) && `${campo}-estado`].filter(Boolean).join(" ") || undefined} />
                                            <h4><label htmlFor={campo}>{name}</label></h4>
                                        </div>
                                        {(activo || seleccionado || recomendado) && <div className="estimacion-speechmatics-insignias" id={`${campo}-estado`}>
                                            {activo && <Badge tone="info">Modelo activo</Badge>}
                                            {seleccionado && !activo && <Badge tone="warning">Selección sin guardar</Badge>}
                                            {recomendado && <Badge tone="success">Recomendado</Badge>}
                                        </div>}
                                    </div>
                                    {beneficio && <p className="estimacion-speechmatics-beneficio" id={`${campo}-beneficio`}>{beneficio}</p>}
                                </li>
                            );
                        })}
                    </ul>
                </> : <p className="nota-configuracion">No hay modelos de Speechmatics disponibles.</p>}
            </fieldset>
            {filas.length > 0 && (
                <details className="estimacion-speechmatics-costos">
                    <summary>Ver costos estimados por modelo</summary>
                    <fieldset className="estimacion-speechmatics-escenario" onKeyDown={(evento) => {
                        if (evento.key === "Enter") evento.preventDefault();
                    }}>
                        <legend>Escenario mensual · {BOXES_SPEECHMATICS} boxes</legend>
                        <div className="campos-configuracion estimacion-speechmatics-campos">
                            <Campo campo="estimacionSesiones" errores={errores}
                                ayuda={`Hasta ${MAX_SESIONES_POR_BOX} sesiones por box, de ${MINUTOS_POR_SESION} minutos cada una.`}
                                titulo={<>Sesiones diarias por box <span aria-hidden="true">· {sesionesPorBox}</span></>}>
                                {(props) => <input {...props} type="range" min={0} max={MAX_SESIONES_POR_BOX} step={1} value={sesionesPorBox}
                                    onChange={(evento) => setSesionesPorBox(evento.target.value)} />}
                            </Campo>
                            <Campo campo="estimacionDias" titulo="Días hábiles al mes" errores={errores} ayuda="De lunes a viernes.">
                                {(props) => <input {...props} type="number" min={0} max={MAX_DIAS_HABILES} step={1} value={dias}
                                    onChange={(evento) => setDias(evento.target.value)} />}
                            </Campo>
                        </div>
                        <div className="estimacion-speechmatics-total" role="status">
                            {horasMensuales === null ? <span>Revisa los días hábiles para ver la estimación.</span>
                                : <div className="estimacion-speechmatics-horas">
                                    <span><strong>{NUMERO.format(horasMensuales)} h</strong> de audio al mes</span>
                                    <span>Eso equivale a {NUMERO.format(diasHabiles ? horasDiarias : 0)} h de audio por día hábil entre todos los boxes.</span>
                                </div>}
                            {descuento > 0 && <Badge tone="success">
                                {descuento} % de descuento estimado
                            </Badge>}
                        </div>
                    </fieldset>
                    <p className="estado-tarifas-speechmatics" role="status">{estadoTarifas}</p>
                    {catalogo?.models.length > 0 && <DataTable label="Costos estimados de Speechmatics" className="estimacion-speechmatics-tabla">
                        <thead><tr>
                            <th scope="col">Modelo</th><th scope="col">Por hora</th><th scope="col">Al mes</th>
                        </tr></thead>
                        <tbody>{filas.map(({ id, name, usd_per_hour: tarifa }) => {
                            const subtotal = horasMensuales !== null && tarifa != null ? horasMensuales * tarifa : null;
                            return <tr key={id}>
                                <th scope="row">{name}</th>
                                <td>{tarifa == null ? "Sin tarifa" : USD_HORA.format(tarifa)}</td>
                                <td>{subtotal === null ? "—" : USD.format(subtotal * (100 - descuento) / 100)}
                                    {descuento > 0 && subtotal !== null && <small>Sin descuento: {USD.format(subtotal)}</small>}
                                </td>
                            </tr>;
                        })}</tbody>
                    </DataTable>}
                    <p className="estimacion-speechmatics-fuente">
                        La proyección supone que se transcribe todo el audio con tarifas Batch en USD antes de impuestos.
                        Si el escenario supera {UMBRAL_DESCUENTO} h al mes, se estima un {PORCENTAJE_DESCUENTO} % de descuento. Su aplicación a la factura depende del contrato.
                        {" "}<a href="https://www.speechmatics.com/pricing.md" target="_blank" rel="noreferrer">Tarifas públicas de Speechmatics</a>
                    </p>
                </details>
            )}
        </div>
    );
}

export function AjustesModelos({ formulario, vigente, actualizar, errores, activa }) {
    const { options, jev_threshold: umbral } = formulario;
    if (!options) return null;
    const umbralSelector = Math.round(umbral * PASOS_UMBRAL_JEV) / PASOS_UMBRAL_JEV;
    const ayudaUmbral = `Versión activa ${vigente.jev_model} · Umbral guardado ${PUNTAJE_JEV.format(vigente.jev_threshold)}`;
    return (
        <>
            <ComparadorSpeechmatics modelos={options.speechmatics_models} modeloSeleccionado={formulario.speechmatics_model}
                modeloActivo={vigente.speechmatics_model} seleccionar={(modelo) => actualizar("speechmatics_model", modelo)}
                error={errores.speechmatics_model?.join(" ")} activa={activa} />
            {umbral != null && <fieldset className="grupo-configuracion umbral-jev">
                <legend>Análisis con JEV</legend>
                <div className="umbral-jev-panel">
                    <Campo campo="jev_threshold" errores={errores}
                        titulo={<>Umbral de JEV <span aria-hidden="true">· {PUNTAJE_JEV.format(umbral)}</span></>}
                        ayuda={umbral === umbralSelector ? ayudaUmbral
                            : `${ayudaUmbral}. El selector se mueve en pasos de 0,05. El valor guardado se conserva hasta que ajustes el selector y guardes.`}>
                        {(props) => <div>
                            <input {...props} type="range" min={0} max={1} step={1 / PASOS_UMBRAL_JEV} value={umbralSelector}
                                aria-valuetext={PUNTAJE_JEV.format(umbralSelector)}
                                onChange={(evento) => actualizar("jev_threshold", evento.target.valueAsNumber)} />
                            <div className="umbral-jev-escala" aria-hidden="true">
                                <span>0 · Más sensible</span>
                                <span>1 · Más estricto</span>
                            </div>
                        </div>}
                    </Campo>
                    <div className="nota-configuracion">
                        <Icon name="info" />
                        <div>
                            <p role="status">{explicarUmbralJev(umbral)}</p>
                            <p>Para pasar el filtro, el puntaje debe ser {PUNTAJE_JEV.format(umbral)} o más. El sistema también verifica la evidencia y el contexto.</p>
                        </div>
                    </div>
                </div>
            </fieldset>}
        </>
    );
}

