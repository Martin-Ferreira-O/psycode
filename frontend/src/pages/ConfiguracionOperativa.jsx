import { useEffect, useRef, useState } from "react";
import { apiGetDatos, describirError } from "../api.js";
import { solicitarCambioAdministrativo } from "../admin/solicitudes.js";
import { PageHeader } from "../layout.jsx";
import { Button, Icon, Skeleton, Status } from "../ui.jsx";
import { AjustesModelos, AjustesSmile, Campo, CAMPOS_MODELOS, CAMPOS_SMILE, prepararAjustes } from "./AjustesProcesamiento.jsx";

const ENDPOINT = "/api/v1/configuracion-operativa";
const LISTA = "lista_distribucion";
const SUPERVISORES = "supervisores_activos";
const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const SECCIONES = [
    { id: "horario", titulo: "Horario clínico", icono: "calendar", descripcion: "Define los días y las horas en que se autoriza la operación clínica.",
        campos: ["enabled_days", "open_time", "close_time"], contenido: AjustesHorario },
    { id: "smile", titulo: "Integración Smile", icono: "monitor", descripcion: "Configura el PC que recopila la agenda y los boxes que abarca.",
        campos: CAMPOS_SMILE, contenido: AjustesSmile },
    { id: "audio", titulo: "Captura de audio", icono: "microphone", descripcion: "Elige cómo se divide el audio de las nuevas sesiones.",
        campos: ["audio_chunk_mode", "audio_chunk_duration"], contenido: AjustesAudio },
    { id: "modelos", titulo: "Modelos de procesamiento", icono: "settings", descripcion: "Selecciona los modelos para transcribir el audio y analizar las sesiones.",
        campos: CAMPOS_MODELOS, contenido: AjustesModelos },
    { id: "alertas", titulo: "Notificaciones", icono: "email", descripcion: "Configura quién recibe las alertas y el correo que se usa si falla un envío.",
        campos: ["notification_mode", "primary_email", "backup_enabled", "backup_email"], contenido: AjustesAlertas },
];
const CAMPOS_GENERALES = SECCIONES.filter(({ id }) => id !== "smile" && id !== "modelos").flatMap(({ campos }) => campos);
const CAMPOS = [...CAMPOS_GENERALES, ...CAMPOS_MODELOS, ...CAMPOS_SMILE, "non_field_errors"];

function seccionDesdeURL() {
    const id = window.location.hash.slice(1);
    return SECCIONES.find((seccion) => seccion.id === id)?.id ?? SECCIONES[0].id;
}

function formularioDesdeConfiguracion(configuracion) {
    return {
        ...configuracion,
        enabled_days: (configuracion.enabled_days ?? []).map(Number),
        open_time: configuracion.open_time ?? "",
        close_time: configuracion.close_time ?? "",
        notification_mode: configuracion.notification_mode === SUPERVISORES ? SUPERVISORES : LISTA,
        primary_email: configuracion.primary_email ?? "",
        backup_enabled: Boolean(configuracion.backup_enabled),
        backup_email: configuracion.backup_email ?? "",
        audio_chunk_duration: configuracion.audio_chunk_duration ?? 60,
        audio_chunk_mode: configuracion.audio_chunk_mode === "session" ? "session" : "fixed",
        timezone: configuracion.timezone || "America/Santiago",
    };
}

function ultimaActualizacion({ updated_at, timezone }) {
    if (!updated_at) return "";
    const fecha = new Intl.DateTimeFormat("es-CL", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: timezone,
    }).format(new Date(updated_at));
    return `Última actualización: ${fecha}`;
}

function AjustesHorario({ formulario, actualizar, errores }) {
    function cambiarDia(dia) {
        const dias = formulario.enabled_days.includes(dia)
            ? formulario.enabled_days.filter((item) => item !== dia)
            : [...formulario.enabled_days, dia].sort((a, b) => a - b);
        actualizar("enabled_days", dias);
    }

    return (
        <>
            <fieldset className="grupo-configuracion" id="enabled_days" tabIndex={-1}
                aria-describedby={errores.enabled_days ? "enabled_days-error" : undefined}>
                <legend>Días habilitados</legend>
                <div className="opciones-seleccion">
                    {DIAS.map((dia, numero) => (
                        <label className="seleccion-configuracion" key={dia}>
                            <input type="checkbox" name="enabled_days" value={numero}
                                checked={formulario.enabled_days.includes(numero)} onChange={() => cambiarDia(numero)} />
                            <span>{dia}</span>
                        </label>
                    ))}
                </div>
                {errores.enabled_days && <p className="error-configuracion" id="enabled_days-error">{errores.enabled_days.join(" ")}</p>}
            </fieldset>
            <fieldset className="grupo-configuracion">
                <legend>Horas de atención</legend>
                <div className="campos-configuracion">
                    {[["open_time", "Apertura"], ["close_time", "Cierre"]].map(([campo, titulo]) => (
                        <Campo key={campo} campo={campo} titulo={titulo} errores={errores}>
                            {(props) => <input {...props} type="time" required value={formulario[campo]}
                                onChange={(evento) => actualizar(campo, evento.target.value)} />}
                        </Campo>
                    ))}
                </div>
                <p className="nota-configuracion">
                    <Icon name="history" />
                    <span>Zona horaria del horario clínico <strong>{formulario.timezone}</strong></span>
                </p>
            </fieldset>
        </>
    );
}

function OpcionConfiguracion({ campo, valor, seleccionado, titulo, descripcion, actualizar }) {
    return (
        <label className="opcion-configuracion">
            <input type="radio" name={campo} value={valor} checked={seleccionado}
                onChange={() => actualizar(campo, valor)} />
            <span>
                <strong>{titulo}</strong>
                <span>{descripcion}</span>
            </span>
        </label>
    );
}

function AjustesAudio({ formulario, actualizar, errores }) {
    const fija = formulario.audio_chunk_mode === "fixed";
    return (
        <>
            <fieldset className="grupo-configuracion" id="audio_chunk_mode" tabIndex={-1}
                aria-describedby={errores.audio_chunk_mode ? "audio_chunk_mode-error" : undefined}>
                <legend>Modo de fragmentación</legend>
                <div className="opciones-configuracion">
                    <OpcionConfiguracion campo="audio_chunk_mode" valor="fixed" seleccionado={fija}
                        titulo="Duración fija" descripcion="Cada fragmento se transcribe y analiza por separado." actualizar={actualizar} />
                    <OpcionConfiguracion campo="audio_chunk_mode" valor="session" seleccionado={!fija}
                        titulo="Sesión completa" descripcion="El audio se transcribe y analiza en un solo bloque al cierre." actualizar={actualizar} />
                </div>
                {errores.audio_chunk_mode && <p className="error-configuracion" id="audio_chunk_mode-error">{errores.audio_chunk_mode.join(" ")}</p>}
                <div className="campos-configuracion">
                    <Campo campo="audio_chunk_duration" titulo="Duración del fragmento (segundos)" errores={errores}
                        ayuda={fija ? "Usa al menos 10 segundos. Se recomiendan 60 segundos." : "La duración fija se conserva para cuando vuelvas a usarla."}>
                        {(props) => <input {...props} type="number" min={10} step={1} list="duracionesFragmento"
                            required={fija} disabled={!fija} value={formulario.audio_chunk_duration}
                            onChange={(evento) => actualizar("audio_chunk_duration", evento.target.value)} />}
                    </Campo>
                </div>
                <datalist id="duracionesFragmento">
                    <option value="10">10 s (mínimo)</option>
                    <option value="60">60 s (recomendado)</option>
                    <option value="600">600 s (10 minutos)</option>
                </datalist>
            </fieldset>
            <p className="nota-configuracion nota-configuracion--advertencia">
                <Icon name="warning" />
                <span>Cambiar la duración o usar la sesión completa puede afectar la precisión del análisis y el tiempo de envío de las alertas.</span>
            </p>
        </>
    );
}

function AjustesAlertas({ formulario, actualizar, errores }) {
    const esLista = formulario.notification_mode === LISTA;
    return (
        <>
            <fieldset className="grupo-configuracion" id="notification_mode" tabIndex={-1}
                aria-describedby={errores.notification_mode ? "notification_mode-error" : undefined}>
                <legend>Destinatarios principales</legend>
                <div className="opciones-configuracion">
                    <OpcionConfiguracion campo="notification_mode" valor={LISTA} seleccionado={esLista}
                        titulo="Lista de distribución" descripcion="Envía las alertas a una dirección cuyos integrantes se administran fuera de Psycode."
                        actualizar={actualizar} />
                    <OpcionConfiguracion campo="notification_mode" valor={SUPERVISORES} seleccionado={!esLista}
                        titulo="Supervisores activos" descripcion="Envía las alertas a todos los supervisores habilitados."
                        actualizar={actualizar} />
                </div>
                {errores.notification_mode && <p className="error-configuracion" id="notification_mode-error">{errores.notification_mode.join(" ")}</p>}
                {esLista && (
                    <div className="campos-configuracion">
                        <Campo campo="primary_email" titulo="Correo de la lista de distribución" errores={errores}>
                            {(props) => <input {...props} type="email" maxLength={254} required
                                value={formulario.primary_email} onChange={(evento) => actualizar("primary_email", evento.target.value)} />}
                        </Campo>
                    </div>
                )}
            </fieldset>
            <fieldset className="grupo-configuracion">
                <legend>Correo de respaldo</legend>
                <label className="opcion-configuracion">
                    <input id="backup_enabled" type="checkbox" checked={formulario.backup_enabled}
                        aria-describedby={errores.backup_enabled ? "backup_enabled-error" : undefined}
                        onChange={(evento) => actualizar("backup_enabled", evento.target.checked)} />
                    <span>
                        <strong>Activar correo de respaldo</strong>
                        <span>Se usa si falla el envío a alguno de los destinatarios principales.</span>
                    </span>
                </label>
                {errores.backup_enabled && <p className="error-configuracion" id="backup_enabled-error">{errores.backup_enabled.join(" ")}</p>}
                <div className="campos-configuracion">
                    <Campo campo="backup_email" titulo="Correo del encargado del sistema" errores={errores}
                        ayuda="La dirección se conserva al desactivar el respaldo.">
                        {(props) => <input {...props} type="email" maxLength={254}
                            disabled={!formulario.backup_enabled} required={formulario.backup_enabled}
                            value={formulario.backup_email} onChange={(evento) => actualizar("backup_email", evento.target.value)} />}
                    </Campo>
                </div>
            </fieldset>
        </>
    );
}

export default function ConfiguracionOperativa() {
    const [formulario, setFormulario] = useState(null);
    const [vigente, setVigente] = useState(null);
    const [seccionActiva, setSeccionActiva] = useState(seccionDesdeURL);
    const [errores, setErrores] = useState({});
    const [errorCarga, setErrorCarga] = useState(null);
    const [intento, setIntento] = useState(0);
    const [guardando, setGuardando] = useState(false);
    const [aviso, setAviso] = useState(null);
    const solicitudGuardado = useRef(null);
    const campoPorEnfocar = useRef(null);

    useEffect(() => {
        const controlador = new AbortController();
        apiGetDatos(ENDPOINT, { signal: controlador.signal })
            .then((configuracion) => {
                if (!controlador.signal.aborted) cargarConfiguracion(configuracion);
            })
            .catch((error) => {
                if (!controlador.signal.aborted && !describirError(error).omitido) setErrorCarga(error);
            });
        return () => controlador.abort();
    }, [intento]);

    useEffect(() => () => solicitudGuardado.current?.abort(), []);

    useEffect(() => {
        const actualizarSeccion = () => setSeccionActiva(seccionDesdeURL());
        window.addEventListener("hashchange", actualizarSeccion);
        return () => window.removeEventListener("hashchange", actualizarSeccion);
    }, []);

    useEffect(() => {
        if (!campoPorEnfocar.current || guardando) return;
        document.getElementById(campoPorEnfocar.current)?.focus();
        campoPorEnfocar.current = null;
    }, [errores, guardando, seccionActiva]);

    function cargarConfiguracion(configuracion) {
        const valores = formularioDesdeConfiguracion(configuracion);
        setVigente(valores);
        setFormulario(valores);
        setErrores({});
    }

    function abrirSeccion(id) {
        if (window.location.hash !== `#${id}`) window.history.pushState(null, "", `#${id}`);
        setSeccionActiva(id);
    }

    function actualizar(campo, valor) {
        setAviso(null);
        setErrores((actual) => ({ ...actual, [campo]: undefined }));
        setFormulario((actual) => ({ ...actual, [campo]: valor }));
    }

    function campoModificado(campo) {
        return JSON.stringify(formulario[campo]) !== JSON.stringify(vigente[campo]);
    }

    function mostrarErrores(campos, mensaje) {
        const campo = Object.keys(campos).find((nombre) => campos[nombre]?.length && CAMPOS.includes(nombre) && nombre !== "non_field_errors");
        const seccion = SECCIONES.find(({ campos: nombres }) => nombres.includes(campo));
        if (seccion) {
            campoPorEnfocar.current = campo;
            abrirSeccion(seccion.id);
        }
        setErrores(campos);
        setAviso({ type: "error", texto: seccion ? "Revisa los campos indicados." : mensaje });
    }

    async function guardar(evento) {
        evento.preventDefault();
        if (solicitudGuardado.current) return;
        const form = evento.currentTarget;
        const { open_time, close_time, backup_enabled, notification_mode } = formulario;
        const primary_email = formulario.primary_email.trim();
        const backup_email = formulario.backup_email.trim();
        const duracion = Number(formulario.audio_chunk_duration);
        const duracionValida = Number.isSafeInteger(duracion) && duracion >= 10;

        const baseModificada = CAMPOS_GENERALES.some(campoModificado);
        const erroresBase = {};
        if (baseModificada) {
            if (!open_time || !close_time || open_time >= close_time) {
                erroresBase.close_time = ["La hora de apertura debe ser anterior a la de cierre."];
            }
            if (formulario.audio_chunk_mode === "fixed" && !duracionValida) {
                erroresBase.audio_chunk_duration = ["Ingresa un número entero de al menos 10 segundos."];
            }
            if (notification_mode === LISTA && !form.elements.primary_email.validity.valid) {
                erroresBase.primary_email = ["Ingresa un correo válido para la lista de distribución."];
            }
            if (backup_enabled && !form.elements.backup_email.validity.valid) {
                erroresBase.backup_email = ["Ingresa un correo válido para activar el respaldo."];
            }
        }

        const base = {
            enabled_days: formulario.enabled_days, open_time, close_time,
            notification_mode, primary_email, backup_enabled, backup_email,
            audio_chunk_mode: formulario.audio_chunk_mode,
            audio_chunk_duration: duracionValida ? duracion : 60,
        };
        const ajustes = formulario.options ? prepararAjustes(formulario, vigente) : { payload: {}, errores: {} };
        const erroresValidacion = { ...erroresBase, ...ajustes.errores };
        if (Object.keys(erroresValidacion).length) {
            mostrarErrores(erroresValidacion);
            return;
        }
        const payload = { ...(baseModificada ? base : {}), ...ajustes.payload };
        if (!Object.keys(payload).length) return;

        const controlador = new AbortController();
        solicitudGuardado.current = controlador;
        setAviso(null);
        setGuardando(true);
        try {
            const configuracion = await solicitarCambioAdministrativo(ENDPOINT, {
                method: "PUT", payload, signal: controlador.signal, campos: CAMPOS,
            });
            if (controlador.signal.aborted) return;
            cargarConfiguracion(configuracion);
            setAviso({ type: "exito", texto: "La configuración operativa se guardó correctamente." });
        } catch (error) {
            if (!controlador.signal.aborted && !describirError(error).omitido) {
                const mensaje = error.estado === 403
                    ? "No tienes permiso para modificar la configuración operativa."
                    : describirError(error).mensaje;
                const campos = error.detalles?.fields ?? {};
                mostrarErrores(campos, campos.non_field_errors?.join(" ") || mensaje);
            }
        } finally {
            solicitudGuardado.current = null;
            if (!controlador.signal.aborted) setGuardando(false);
        }
    }

    const secciones = SECCIONES.filter(({ id }) => formulario?.options || (id !== "smile" && id !== "modelos"));
    const activa = secciones.find(({ id }) => id === seccionActiva)?.id ?? secciones[0].id;
    const hayCambios = formulario && (CAMPOS.some(campoModificado) || campoModificado("smile_legacy_active"));

    return (
        <>
            <PageHeader title="Configuración operativa"
                description="Administra los ajustes de captura, procesamiento y alertas de la clínica." />
            {errorCarga?.estado === 403
                ? <Status type="error">Esta pantalla y sus datos están disponibles únicamente para administradores.</Status>
                : errorCarga
                    ? <Status type="error" error={errorCarga} onRetry={() => {
                        setErrorCarga(null);
                        setIntento((actual) => actual + 1);
                    }} />
                    : !formulario && (
                        <div className="configuracion-cargando" role="status">
                            <span>Cargando configuración…</span>
                            <Skeleton className="ui-skeleton-field" />
                            <Skeleton className="ui-skeleton-field" />
                        </div>
                    )}
            {formulario && (
                <div className="configuracion-operativa">
                    <div className="configuracion-lateral">
                        <nav className="configuracion-nav" aria-label="Secciones de configuración">
                            {secciones.map(({ id, titulo, icono, campos }) => (
                                <a key={id} href={`#${id}`} aria-current={id === activa ? "location" : undefined}
                                    onClick={(evento) => {
                                        if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
                                        evento.preventDefault();
                                        abrirSeccion(id);
                                    }}>
                                    <Icon name={icono} />
                                    <span>{titulo}</span>
                                    {campos.some((campo) => errores[campo]?.length)
                                        ? <Icon name="warning" className="configuracion-nav-error" />
                                        : <Icon name="chevron_right" className="configuracion-nav-flecha" />}
                                </a>
                            ))}
                        </nav>
                        <Button className="configuracion-almacenamiento" href="/api/v1/almacenamiento/panel">
                            <Icon name="hard_drive" />
                            Almacenamiento del servidor
                            <Icon name="arrow_forward" />
                        </Button>
                    </div>
                    <form id="formularioConfiguracion" className="configuracion-formulario" onSubmit={guardar} noValidate aria-busy={guardando}>
                        <fieldset className="configuracion-secciones" disabled={guardando}>
                            {secciones.map(({ id, titulo, icono, descripcion, contenido: Contenido }) => (
                                <section key={id} className="configuracion-seccion" hidden={id !== activa}
                                    aria-labelledby={`titulo-${id}`}>
                                    <header className="configuracion-seccion-cabecera">
                                        <span className="configuracion-seccion-icono"><Icon name={icono} /></span>
                                        <div>
                                            <h2 id={`titulo-${id}`}>{titulo}</h2>
                                            <p>{descripcion}</p>
                                        </div>
                                    </header>
                                    <div className="configuracion-seccion-cuerpo">
                                        <Contenido formulario={formulario} vigente={vigente} actualizar={actualizar} errores={errores} />
                                    </div>
                                </section>
                            ))}
                        </fieldset>
                        <div className="configuracion-guardado">
                            {aviso && <Status type={aviso.type}>{aviso.texto}</Status>}
                            <div className="configuracion-guardado-fila">
                                <span id="ultimaActualizacion" aria-live="polite">
                                    {hayCambios ? "Tienes cambios sin guardar" : ultimaActualizacion(vigente)}
                                </span>
                                <Button id="guardarConfiguracion" type="submit" variant="primary" disabled={!hayCambios}
                                    busy={guardando} busyLabel="Guardando…">
                                    Guardar configuración
                                </Button>
                            </div>
                        </div>
                    </form>
                </div>
            )}
        </>
    );
}
