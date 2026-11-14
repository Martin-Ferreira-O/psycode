import { Icon } from "../ui.jsx";

export const CAMPOS_MODELOS = ["jev_model", "jev_threshold", "speechmatics_model"];
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
    enhanced: ["Enhanced (predeterminado)", "Mayor precisión con acentos, ruido de fondo y terminología clínica en español. Tiene el costo por minuto más alto de estas opciones."],
    standard: ["Standard", "Procesamiento más ligero y menor costo por minuto que Enhanced. Adecuado para grabaciones limpias y transcripción general."],
    "melia-1": ["Melia 1", "Detecta cambios de idioma dentro de la conversación y cuesta menos que Standard según la tarifa pública de Batch. El diccionario personalizado y las puntuaciones de confianza no están disponibles."],
    "oak-1": ["Oak 1 Medical", "Reconoce terminología clínica en conversaciones multilingües y cuesta menos que Enhanced según la tarifa pública de Batch. El diccionario personalizado y las puntuaciones de confianza no están disponibles."],
};

export function prepararAjustes(formulario, vigente) {
    const opciones = formulario.options;
    const campos = CAMPOS_MODELOS.filter((campo) => formulario[campo] !== vigente[campo]);
    if (formulario.smile_legacy_active !== vigente.smile_legacy_active
        || CAMPOS_SMILE.some((campo) => JSON.stringify(formulario[campo]) !== JSON.stringify(vigente[campo]))) {
        campos.push(...CAMPOS_SMILE);
    }

    const errores = {};
    const payload = Object.fromEntries(campos.map((campo) => [campo, formulario[campo]]));
    if (campos.includes("jev_model") && !opciones.jev_models.includes(payload.jev_model)) {
        errores.jev_model = ["Selecciona una versión disponible de Jev."];
    }
    if (campos.includes("jev_threshold")) {
        const entrada = String(payload.jev_threshold).trim().replace(",", ".");
        const valor = Number(entrada);
        if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(entrada) || valor < 0 || valor > 1) {
            errores.jev_threshold = ["Ingresa un número entre 0 y 1."];
        }
        payload.jev_threshold = valor;
    }
    if (campos.includes("speechmatics_model") && !opciones.speechmatics_models.includes(payload.speechmatics_model)) {
        errores.speechmatics_model = ["Selecciona un modelo disponible de Speechmatics."];
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

export function AjustesModelos({ formulario, vigente, actualizar, errores }) {
    const { options } = formulario;
    if (!options) return null;
    return (
        <fieldset className="grupo-configuracion">
            <legend>Transcripción y análisis</legend>
            <div className="campos-configuracion">
                <Campo campo="jev_model" titulo="Modelo de Jev" errores={errores} ayuda={`Versión activa de Jev ${vigente.jev_model}.`}>
                    {(props) => <select {...props} value={formulario.jev_model}
                        onChange={(evento) => actualizar("jev_model", evento.target.value)}>
                        {options.jev_models.map((version) => <option key={version} value={version}>Jev {version}</option>)}
                    </select>}
                </Campo>
                <Campo campo="speechmatics_model" titulo="Modelo de Speechmatics" errores={errores}
                    ayuda={`Modelo activo: ${MODELOS[vigente.speechmatics_model]?.[0] ?? vigente.speechmatics_model}. ${MODELOS[formulario.speechmatics_model]?.[1] ?? ""}`}>
                    {(props) => <select {...props} value={formulario.speechmatics_model}
                        onChange={(evento) => actualizar("speechmatics_model", evento.target.value)}>
                        {options.speechmatics_models.map((modelo) => <option key={modelo} value={modelo}>{MODELOS[modelo]?.[0] ?? modelo}</option>)}
                    </select>}
                </Campo>
                {formulario.jev_threshold != null && (
                    <Campo campo="jev_threshold" titulo="Umbral de JEV" errores={errores}
                        ayuda="Puntaje mínimo de JEV para considerar una señal del modelo. Un umbral más bajo admite más señales, que se verifican según su contexto y evidencia. El valor inicial es 0,55 (rango de 0 a 1).">
                        {(props) => <input {...props} type="text" inputMode="decimal" value={formulario.jev_threshold}
                            onChange={(evento) => actualizar("jev_threshold", evento.target.value)} />}
                    </Campo>
                )}
            </div>
        </fieldset>
    );
}

