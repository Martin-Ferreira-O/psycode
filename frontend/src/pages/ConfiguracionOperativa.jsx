import { useEffect, useRef, useState } from "react";
import { apiGetDatos, describirError } from "../api.js";
import { solicitarCambioAdministrativo } from "../admin/solicitudes.js";
import { PageHeader } from "../layout.jsx";
import { Button, Skeleton, Status } from "../ui.jsx";

const ENDPOINT = "/api/v1/configuracion-operativa";
const LISTA = "lista_distribucion";
const SUPERVISORES = "supervisores_activos";
const CAMPOS = [
    "enabled_days", "open_time", "close_time", "notification_mode",
    "primary_email", "backup_enabled", "backup_email", "non_field_errors",
];
const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const DENEGADO = "Esta pantalla y sus datos están disponibles únicamente para administradores.";

function formularioDesdeConfiguracion(configuracion) {
    return {
        enabled_days: (configuracion.enabled_days ?? []).map(Number),
        open_time: configuracion.open_time ?? "",
        close_time: configuracion.close_time ?? "",
        notification_mode: configuracion.notification_mode === SUPERVISORES ? SUPERVISORES : LISTA,
        primary_email: configuracion.primary_email ?? "",
        backup_enabled: Boolean(configuracion.backup_enabled),
        backup_email: configuracion.backup_email ?? "",
        timezone: configuracion.timezone || "America/Santiago",
        updated_at: configuracion.updated_at,
    };
}

function ultimaActualizacion({ updated_at, timezone }) {
    if (!updated_at) return "Configuración vigente";
    const fecha = new Intl.DateTimeFormat("es-CL", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: timezone,
    }).format(new Date(updated_at));
    return `Última actualización: ${fecha}`;
}

function mensajeGuardado(error) {
    if (error.estado === 403) return "No tienes permiso para modificar la configuración operativa.";
    const mensajes = Object.values(error.detalles?.fields ?? {}).flat();
    return mensajes.length ? mensajes.join(" ") : describirError(error).mensaje;
}

function OpcionDestinatario({ modo, seleccionado, titulo, descripcion, cambiarModo, children }) {
    return (
        <div className={`opcion-destinatario${seleccionado ? " opcion-destinatario--activa" : ""}`}>
            <label className="opcion-destinatario-cabecera">
                <input type="radio" name="notification_mode" value={modo}
                    checked={seleccionado} onChange={() => cambiarModo(modo)} />
                <span className="opcion-destinatario-titulo">{titulo}</span>
                {seleccionado && <span className="insignia-opcion-activa" aria-hidden="true">Opción activa</span>}
            </label>
            <p className="orientacion-destinatario">{descripcion}</p>
            {children}
        </div>
    );
}

export default function ConfiguracionOperativa() {
    const [formulario, setFormulario] = useState(null);
    const [errorCarga, setErrorCarga] = useState(null);
    const [intento, setIntento] = useState(0);
    const [guardando, setGuardando] = useState(false);
    const [aviso, setAviso] = useState(null);
    const solicitudGuardado = useRef(null);

    useEffect(() => {
        const controlador = new AbortController();
        apiGetDatos(ENDPOINT, { signal: controlador.signal })
            .then((configuracion) => {
                if (!controlador.signal.aborted) setFormulario(formularioDesdeConfiguracion(configuracion));
            })
            .catch((error) => {
                if (!controlador.signal.aborted && !describirError(error).omitido) setErrorCarga(error);
            });
        return () => controlador.abort();
    }, [intento]);

    useEffect(() => () => solicitudGuardado.current?.abort(), []);

    function reintentar() {
        setErrorCarga(null);
        setIntento((actual) => actual + 1);
    }

    function actualizar(campo, valor) {
        setAviso(null);
        setFormulario((actual) => ({ ...actual, [campo]: valor }));
    }

    function cambiarDia(dia) {
        const dias = formulario.enabled_days.includes(dia)
            ? formulario.enabled_days.filter((item) => item !== dia)
            : [...formulario.enabled_days, dia].sort((a, b) => a - b);
        actualizar("enabled_days", dias);
    }

    async function guardar(evento) {
        evento.preventDefault();
        if (solicitudGuardado.current) return;
        setAviso(null);
        const form = evento.currentTarget;
        const { open_time, close_time, backup_enabled, notification_mode } = formulario;
        const primary_email = formulario.primary_email.trim();
        const backup_email = formulario.backup_email.trim();

        if (notification_mode === LISTA && !form.elements.primary_email.validity.valid) {
            setAviso({ type: "error", texto: "Debes ingresar un correo válido para la lista de distribución." });
            form.elements.primary_email.reportValidity();
            return;
        }
        if (backup_enabled && !form.elements.backup_email.validity.valid) {
            setAviso({ type: "error", texto: "Debes ingresar un correo válido para activar el respaldo." });
            form.elements.backup_email.reportValidity();
            return;
        }
        if (!form.reportValidity()) return;
        if (open_time >= close_time) {
            setAviso({ type: "error", texto: "La hora de apertura debe ser anterior a la hora de cierre." });
            form.elements.close_time.focus();
            return;
        }

        const payload = {
            enabled_days: formulario.enabled_days, open_time, close_time,
            notification_mode, primary_email, backup_enabled, backup_email,
        };
        const controlador = new AbortController();
        solicitudGuardado.current = controlador;
        setGuardando(true);
        try {
            const configuracion = await solicitarCambioAdministrativo(ENDPOINT, {
                method: "PUT", payload, signal: controlador.signal, campos: CAMPOS,
            });
            if (controlador.signal.aborted) return;
            setFormulario(formularioDesdeConfiguracion(configuracion));
            setAviso({ type: "exito", texto: "La configuración operativa se guardó correctamente." });
        } catch (error) {
            if (!controlador.signal.aborted && !describirError(error).omitido) {
                setAviso({ type: "error", texto: mensajeGuardado(error) });
            }
        } finally {
            solicitudGuardado.current = null;
            if (!controlador.signal.aborted) setGuardando(false);
        }
    }

    const esLista = formulario?.notification_mode === LISTA;

    return (
        <>
            <PageHeader title="Configuración operativa"
                description="Administra los días, el horario clínico y los destinatarios de alertas." />
            <section className="panel-configuracion panel-configuracion-operativa" aria-labelledby="tituloConfiguracion"
                aria-busy={!formulario && !errorCarga}>
                <div className="configuracion-cabecera">
                    <div>
                        <h2 id="tituloConfiguracion">Horario clínico y alertas</h2>
                        <p>La configuración vigente se carga desde el servidor.</p>
                    </div>
                    {!errorCarga && <div className="zona-horaria">
                        <span>Zona horaria utilizada</span>
                        <strong id="zonaHoraria">{formulario?.timezone ?? <Skeleton className="ui-skeleton-count" />}</strong>
                    </div>}
                </div>
                {!errorCarga && (
                    <Button variant="secondary" className="boton-navegacion-configuracion" href="/api/v1/almacenamiento/panel">
                        Almacenamiento del servidor
                    </Button>
                )}
                {errorCarga?.estado === 403
                    ? <Status type="error">{DENEGADO}</Status>
                    : errorCarga
                        ? <Status type="error" error={errorCarga} onRetry={reintentar} />
                        : !formulario && (
                            <>
                                {["Días habilitados", "Horario clínico", "Destinatarios de alertas", "Correo de respaldo"].map(title => (
                                    <fieldset key={title} className="grupo-configuracion">
                                        <legend>{title}</legend>
                                        <Skeleton className="ui-skeleton-field" />
                                    </fieldset>
                                ))}
                            </>
                        )}
                {formulario && (
                    <>
                        <form id="formularioConfiguracion" onSubmit={guardar} noValidate aria-busy={guardando}>
                            <fieldset className="grupo-configuracion" disabled={guardando}>
                                <legend>Días habilitados</legend>
                                <p className="ayuda-configuracion">Selecciona los días en que se autoriza la operación clínica.</p>
                                <div className="dias-semana">
                                    {DIAS.map((dia, numero) => (
                                        <label className="dia-semana" key={dia}>
                                            <input type="checkbox" name="enabled_days" value={numero}
                                                checked={formulario.enabled_days.includes(numero)}
                                                onChange={() => cambiarDia(numero)} />
                                            <span>{dia}</span>
                                        </label>
                                    ))}
                                </div>
                            </fieldset>

                            <fieldset className="grupo-configuracion" disabled={guardando}>
                                <legend>Horario clínico</legend>
                                <div className="campos-horario">
                                    <label className="campo-configuracion">
                                        <span>Apertura</span>
                                        <input id="horaApertura" type="time" name="open_time" required
                                            value={formulario.open_time}
                                            onChange={(evento) => actualizar("open_time", evento.target.value)} />
                                    </label>
                                    <label className="campo-configuracion">
                                        <span>Cierre</span>
                                        <input id="horaCierre" type="time" name="close_time" required
                                            value={formulario.close_time}
                                            onChange={(evento) => actualizar("close_time", evento.target.value)} />
                                    </label>
                                </div>
                                <p className="ayuda-configuracion">La hora de apertura debe ser anterior a la de cierre.</p>
                            </fieldset>

                            <fieldset className="grupo-configuracion" disabled={guardando}>
                                <legend>Destinatarios de alertas</legend>
                                <p className="ayuda-configuracion">Selecciona quién recibirá las notificaciones principales de alertas.</p>
                                <div className="opciones-destinatarios" role="radiogroup" aria-label="Modalidad de destinatarios principales">
                                    <OpcionDestinatario modo={LISTA} seleccionado={esLista} titulo="Lista de distribución"
                                        descripcion="Las alertas se enviarán a la dirección configurada. Sus integrantes se administran fuera de Psycode"
                                        cambiarModo={(modo) => actualizar("notification_mode", modo)}>
                                        {esLista && (
                                            <div className="contenedor-correo-distribucion">
                                                <label className="campo-configuracion">
                                                    <span>Correo de lista de distribución</span>
                                                    <input id="correoPrincipal" type="email" name="primary_email"
                                                        maxLength={254} autoComplete="email" required
                                                        value={formulario.primary_email}
                                                        onChange={(evento) => actualizar("primary_email", evento.target.value)} />
                                                </label>
                                            </div>
                                        )}
                                    </OpcionDestinatario>
                                    <OpcionDestinatario modo={SUPERVISORES} seleccionado={!esLista} titulo="Supervisores activos"
                                        descripcion="Las alertas se enviarán al correo registrado de todos los supervisores habilitados, aunque no tengan una sesión iniciada"
                                        cambiarModo={(modo) => actualizar("notification_mode", modo)} />
                                </div>
                            </fieldset>

                            <fieldset className="grupo-configuracion" disabled={guardando}>
                                <legend>Correo de respaldo</legend>
                                <label className="control-respaldo">
                                    <input id="respaldoHabilitado" name="backup_enabled" type="checkbox"
                                        aria-describedby="ayudaCorreoRespaldo conservacionCorreoRespaldo"
                                        checked={formulario.backup_enabled}
                                        onChange={(evento) => actualizar("backup_enabled", evento.target.checked)} />
                                    <span>Activar correo de respaldo</span>
                                </label>
                                <p className="ayuda-configuracion" id="ayudaCorreoRespaldo">
                                    El correo de respaldo se utiliza solo ante fallos del envío a la lista de distribución o a cualquiera de los supervisores destinatarios.
                                    No recibe una copia cuando todos los envíos principales son exitosos.
                                </p>
                                <div className="campos-correos">
                                    <label className="campo-configuracion">
                                        <span>Correo del encargado del sistema</span>
                                        <input id="correoRespaldo" type="email" name="backup_email"
                                            maxLength={254} autoComplete="email"
                                            aria-describedby="ayudaCorreoRespaldo conservacionCorreoRespaldo"
                                            disabled={!formulario.backup_enabled} required={formulario.backup_enabled}
                                            value={formulario.backup_email}
                                            onChange={(evento) => actualizar("backup_email", evento.target.value)} />
                                    </label>
                                </div>
                                <p className="ayuda-configuracion" id="conservacionCorreoRespaldo">
                                    Al desactivarlo y guardar, la dirección se conserva para volver a utilizarla, pero deja de recibir avisos de respaldo.
                                </p>
                            </fieldset>

                            {aviso && <Status type={aviso.type}>{aviso.texto}</Status>}
                            <div className="acciones-configuracion">
                                <span id="ultimaActualizacion" className="ultima-actualizacion">{ultimaActualizacion(formulario)}</span>
                                <Button id="guardarConfiguracion" type="submit" variant="primary" busy={guardando} busyLabel="Guardando…">
                                    Guardar configuración
                                </Button>
                            </div>
                        </form>
                    </>
                )}
            </section>
        </>
    );
}
