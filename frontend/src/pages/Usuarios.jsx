import { useEffect, useRef, useState } from "react";
import { apiGetDatos, describirError } from "../api.js";
import { solicitarCambioAdministrativo } from "../admin/solicitudes.js";
import { PageHeader } from "../layout.jsx";
import { Badge, Button, DataTable, Dialog, FilterSelect, Icon, Skeleton, SkeletonRows, Status } from "../ui.jsx";

const ENDPOINT = "/api/v1/auth/admin/users";
const POR_PAGINA = 10;
const COLUMNAS = ["Usuario", "Nombre", "Correo", "Rol", "Estado", "Acciones"];
const ETIQUETAS_CAMPOS = { usuario: "Usuario", correo: "Correo", password: "Contraseña" };
const PRIORIDAD_CAMPOS = ["usuario", "nombre", "correo", "password", "rol", "activo", "non_field_errors"];

function mensajeError(error) {
    const campos = error.detalles?.fields;
    for (const campo of PRIORIDAD_CAMPOS) {
        const mensaje = campos?.[campo]?.[0];
        if (typeof mensaje === "string" && mensaje.trim()) {
            return ETIQUETAS_CAMPOS[campo] ? `${ETIQUETAS_CAMPOS[campo]}: ${mensaje}` : mensaje;
        }
    }
    return describirError(error, {
        403: "No tienes permisos para administrar usuarios.",
        404: "El usuario solicitado ya no existe.",
    }).mensaje;
}

async function obtenerUsuarios(offset, activo, signal) {
    let datos;
    do {
        const parametros = new URLSearchParams({ limit: POR_PAGINA, offset });
        if (activo) parametros.set("activo", activo);
        datos = await apiGetDatos(`${ENDPOINT}?${parametros}`, { signal });
        if (!Array.isArray(datos?.items) || !Number.isInteger(datos.total) || datos.total < 0) {
            throw new Error("Respuesta de usuarios inválida.");
        }
        if (datos.total === 0) return { items: [], total: 0, offset: 0 };
        if (offset < datos.total) return { ...datos, offset };
        offset = Math.floor((datos.total - 1) / POR_PAGINA) * POR_PAGINA;
    } while (!signal.aborted);
    throw new DOMException("Solicitud cancelada", "AbortError");
}

function TablaUsuarios({ usuarios, usuarioActual, editar, confirmar, loading }) {
    return (
        <DataTable label="Usuarios registrados" className="tabla-usuarios" wrapperId="tablaUsuariosContenedor" stickyActions>
            <thead>
                <tr>{COLUMNAS.map((columna) => <th key={columna} scope="col">{columna}</th>)}</tr>
            </thead>
            <tbody id="tablaUsuarios">
                {loading ? <SkeletonRows columns={COLUMNAS.length} /> : usuarios.map((usuario) => {
                    const esAdmin = usuario.rol === "admin";
                    const accion = usuario.activo ? "Desactivar" : "Activar";
                    const propiaCuenta = usuario.id === usuarioActual?.id;
                    return (
                        <tr key={usuario.id}>
                            <td><strong>{usuario.usuario}</strong></td>
                            <td>{usuario.nombre || "—"}</td>
                            <td>{usuario.correo || "—"}</td>
                            <td><Badge tone={esAdmin ? "info" : "neutral"}>{esAdmin ? "Administrador" : "Supervisor"}</Badge></td>
                            <td><Badge tone={usuario.activo ? "success" : "neutral"}>{usuario.activo ? "Activo" : "Inactivo"}</Badge></td>
                            <td>
                                <div className="acciones-usuario">
                                    <Button variant="secondary" iconOnly title="Editar" aria-label={`Editar usuario ${usuario.usuario}`}
                                        onClick={(evento) => editar(usuario, evento.currentTarget)}>
                                        <Icon name="edit" />
                                    </Button>
                                    <Button variant={usuario.activo ? "danger" : "success"} iconOnly disabled={propiaCuenta}
                                        title={propiaCuenta ? "No puedes desactivar tu propia cuenta" : accion}
                                        aria-label={`${accion} usuario ${usuario.usuario}`}
                                        onClick={(evento) => confirmar(usuario, evento.currentTarget)}>
                                        <Icon name={usuario.activo ? "lock" : "lock_open"} />
                                    </Button>
                                </div>
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </DataTable>
    );
}

function PaginacionUsuarios({ datos, cambiarPagina }) {
    const pagina = Math.floor(datos.offset / POR_PAGINA) + 1;
    const totalPaginas = Math.ceil(datos.total / POR_PAGINA);
    if (totalPaginas <= 1) return null;
    return (
        <nav className="paginacion-usuarios" aria-label="Paginación de usuarios">
            <span>Página {pagina} de {totalPaginas}</span>
            <div className="botones-paginacion-usuarios">
                <Button variant="secondary" disabled={pagina <= 1} onClick={() => cambiarPagina(datos.offset - POR_PAGINA)}>
                    Anterior
                </Button>
                <Button variant="secondary" disabled={pagina >= totalPaginas} onClick={() => cambiarPagina(datos.offset + POR_PAGINA)}>
                    Siguiente
                </Button>
            </div>
        </nav>
    );
}

function CampoPassword({ id, name, etiqueta, ayuda }) {
    const [visible, setVisible] = useState(false);
    return (
        <div className="campo-formulario">
            <label htmlFor={id}>{etiqueta}</label>
            <div className="campo-password">
                <input id={id} name={name} type={visible ? "text" : "password"} minLength={12}
                    autoComplete="new-password" aria-describedby={`${id}Ayuda`} required />
                <Button variant="ghost" className="boton-ver-password" iconOnly aria-pressed={visible}
                    aria-label={`${visible ? "Ocultar" : "Mostrar"} ${etiqueta.toLowerCase()}`}
                    onClick={() => setVisible((actual) => !actual)}>
                    <Icon name={visible ? "visibility_off" : "visibility"} />
                </Button>
            </div>
            <small id={`${id}Ayuda`}>{ayuda}</small>
        </div>
    );
}

function FormularioUsuario({ usuario, cancelar, guardar, indicarError, busy, error, focoInicial }) {
    const editando = Boolean(usuario);
    const titulo = editando ? "Editar usuario" : "Crear usuario";

    function enviar(evento) {
        evento.preventDefault();
        if (busy) return;
        indicarError(null);
        const form = evento.currentTarget;
        if (!form.reportValidity()) return;
        const datos = new FormData(form);
        const payload = {
            nombre: datos.get("nombre").trim(),
            correo: datos.get("correo").trim(),
            rol: datos.get("rol"),
        };
        if (!editando) {
            const password = datos.get("password");
            if (password !== datos.get("confirmar_password")) {
                indicarError("Las contraseñas no coinciden.");
                form.elements.confirmar_password.focus();
                return;
            }
            payload.usuario = datos.get("usuario").trim();
            payload.password = password;
            payload.activo = datos.get("activo") === "true";
        }
        guardar(payload);
    }

    return (
        <>
            <header className="modal-usuario-cabecera">
                <h2>{titulo}</h2>
                <Button iconOnly variant="ghost" aria-label="Cerrar ventana" onClick={cancelar} disabled={busy}>
                    <Icon name="close" />
                </Button>
            </header>
            <form className="formulario-usuario" onSubmit={enviar} noValidate>
                {error && <div className="campo-ancho-completo"><Status type="error">{error}</Status></div>}
                <fieldset className="campos-formulario-usuario" disabled={busy}>
                    {!editando && (
                        <div className="campo-formulario">
                            <label htmlFor="usuarioUsuario">Usuario</label>
                            <input ref={focoInicial} id="usuarioUsuario" type="text" name="usuario"
                                maxLength={150} autoComplete="username" aria-describedby="usuarioUsuarioAyuda" required />
                            <small id="usuarioUsuarioAyuda">Este identificador no podrá modificarse posteriormente.</small>
                        </div>
                    )}
                    <div className="campo-formulario">
                        <label htmlFor="nombreUsuario">Nombre completo</label>
                        <input ref={editando ? focoInicial : undefined} id="nombreUsuario" type="text" name="nombre"
                            maxLength={150} autoComplete="name" required defaultValue={usuario?.nombre || ""} />
                    </div>
                    <div className="campo-formulario campo-ancho-completo">
                        <label htmlFor="correoUsuario">Correo</label>
                        <input id="correoUsuario" type="email" name="correo" maxLength={254}
                            autoComplete="email" required defaultValue={usuario?.correo || ""} />
                    </div>
                    {!editando && (
                        <>
                            <CampoPassword id="passwordUsuario" name="password" etiqueta="Contraseña"
                                ayuda="Debe cumplir los requisitos de seguridad del sistema." />
                            <CampoPassword id="confirmarPasswordUsuario" name="confirmar_password" etiqueta="Confirmar contraseña"
                                ayuda="Repite la contraseña para confirmar que fue escrita correctamente." />
                        </>
                    )}
                    <div className="campo-formulario">
                        <label htmlFor="rolUsuario">Rol</label>
                        <select id="rolUsuario" name="rol" required defaultValue={usuario?.rol || "supervisor"}>
                            <option value="supervisor">Supervisor</option>
                            <option value="admin">Administrador</option>
                        </select>
                    </div>
                    {!editando && (
                        <div className="campo-formulario">
                            <label htmlFor="activoUsuario">Estado</label>
                            <select id="activoUsuario" name="activo" defaultValue="true">
                                <option value="true">Activo</option>
                                <option value="false">Inactivo</option>
                            </select>
                        </div>
                    )}
                </fieldset>
                <div className="acciones-formulario-usuario">
                    <Button variant="secondary" onClick={cancelar} disabled={busy}>Cancelar</Button>
                    <Button type="submit" variant="primary" busy={busy} busyLabel="Guardando…">
                        {editando ? "Guardar cambios" : "Crear usuario"}
                    </Button>
                </div>
            </form>
        </>
    );
}

export default function Usuarios({ user }) {
    const [consulta, setConsulta] = useState({ offset: 0, activo: "", enfocar: false });
    const [listado, setListado] = useState({ tipo: "carga" });
    const [modal, setModal] = useState(null);
    const [procesando, setProcesando] = useState(false);
    const [errorModal, setErrorModal] = useState(null);
    const solicitudCambio = useRef(null);
    const tituloListado = useRef(null);
    const origenModal = useRef(null);
    const focoFormulario = useRef(null);
    const focoConfirmacion = useRef(null);

    useEffect(() => {
        const controlador = new AbortController();
        const { signal } = controlador;
        obtenerUsuarios(consulta.offset, consulta.activo, signal)
            .then((datos) => {
                if (!signal.aborted) setListado({ tipo: "listo", datos });
            })
            .catch((error) => {
                if (!signal.aborted && !describirError(error).omitido) setListado({ tipo: "error", error });
            })
            .finally(() => {
                if (consulta.enfocar && !signal.aborted) tituloListado.current?.focus();
            });
        return () => controlador.abort();
    }, [consulta]);

    useEffect(() => () => solicitudCambio.current?.abort(), []);

    function recargar(offset) {
        setListado({ tipo: "carga" });
        setConsulta((actual) => ({ ...actual, offset, enfocar: true }));
    }

    function filtrar(activo) {
        setListado({ tipo: "carga" });
        setConsulta({ offset: 0, activo, enfocar: false });
    }

    function abrir(tipo, usuario, origen) {
        origenModal.current = origen;
        setErrorModal(null);
        setModal({ tipo, usuario });
    }

    function cerrar() {
        if (!solicitudCambio.current) setModal(null);
    }

    async function cambiar(url, method, payload, offset) {
        if (solicitudCambio.current) return;
        const controlador = new AbortController();
        solicitudCambio.current = controlador;
        setProcesando(true);
        setErrorModal(null);

        try {
            await solicitarCambioAdministrativo(url, {
                method, payload, signal: controlador.signal, campos: PRIORIDAD_CAMPOS,
            });
            if (!controlador.signal.aborted) {
                setModal(null);
                recargar(offset);
            }
        } catch (error) {
            if (controlador.signal.aborted || describirError(error).omitido) return;
            setErrorModal(mensajeError(error));
        } finally {
            solicitudCambio.current = null;
            if (!controlador.signal.aborted) setProcesando(false);
        }
    }

    function guardar(payload) {
        const usuario = modal.usuario;
        return usuario
            ? cambiar(`${ENDPOINT}/${usuario.id}`, "PATCH", payload, offsetActual)
            : cambiar(ENDPOINT, "POST", payload, 0);
    }

    const datos = listado.datos;
    const offsetActual = datos?.offset ?? consulta.offset;
    const editando = modal?.tipo === "formulario" && Boolean(modal.usuario);
    const confirmando = modal?.tipo === "confirmacion";
    const usuarioConfirmacion = confirmando ? modal.usuario : null;
    const activar = usuarioConfirmacion && !usuarioConfirmacion.activo;
    const accion = activar ? "Activar" : "Desactivar";
    const estado = { "": "registrado", true: "activo", false: "inactivo" }[consulta.activo];
    const resultado = datos?.total === 1 ? `1 usuario ${estado}` : `${datos?.total} usuarios ${estado}s`;

    return (
        <>
            <PageHeader title="Gestión de usuarios" description="Administra las cuentas y permisos de acceso al sistema." />
            <section className="panel-alertas panel-usuarios" aria-labelledby="tituloUsuariosRegistrados" aria-busy={listado.tipo === "carga"}>
                <div className="panel-cabecera panel-cabecera-usuarios">
                    <div>
                        <h2 id="tituloUsuariosRegistrados" ref={tituloListado} tabIndex={-1}>Usuarios registrados</h2>
                        {datos && <p role="status">{resultado}</p>}
                        {listado.tipo === "carga" && <p><Skeleton className="ui-skeleton-count" /></p>}
                    </div>
                    {user?.rol === "admin" && listado.error?.estado !== 403 && (
                        <div className="barra-usuarios">
                            <FilterSelect label="Filtrar usuarios por estado" value={consulta.activo} onChange={filtrar}>
                                <option value="">Todos los estados</option>
                                <option value="true">Solo activos</option>
                                <option value="false">Solo inactivos</option>
                            </FilterSelect>
                            <Button id="botonCrearUsuario" variant="primary" onClick={(evento) => abrir("formulario", null, evento.currentTarget)}>
                                + Crear usuario
                            </Button>
                        </div>
                    )}
                </div>

                {listado.tipo === "carga" && <TablaUsuarios loading />}
                {listado.tipo === "error" && (
                    <Status type="error" error={listado.error}
                        messages={{ 403: "No tienes permisos para acceder a la gestión de usuarios." }}
                        onRetry={() => recargar(consulta.offset)} />
                )}
                {datos && (datos.items.length ? (
                    <>
                        <TablaUsuarios usuarios={datos.items} usuarioActual={user}
                            editar={(usuario, origen) => abrir("formulario", usuario, origen)}
                            confirmar={(usuario, origen) => abrir("confirmacion", usuario, origen)} />
                        <PaginacionUsuarios datos={datos} cambiarPagina={recargar} />
                    </>
                ) : (
                    <Status type="vacio">
                        {consulta.activo
                            ? `No hay usuarios ${estado}s.`
                            : "No hay usuarios registrados. Crea una cuenta para comenzar a gestionar los accesos."}
                    </Status>
                ))}

                <div className="pie-usuarios">Las cuentas administrativas permiten controlar el acceso y los permisos dentro de Psycode.</div>
            </section>

            <Dialog open={modal?.tipo === "formulario"} onClose={cerrar} busy={procesando}
                className="modal-usuario-contenido" title={editando ? "Editar usuario" : "Crear usuario"}
                initialFocusRef={focoFormulario} returnFocusRef={origenModal}>
                {modal?.tipo === "formulario" && (
                    <FormularioUsuario usuario={modal.usuario} cancelar={cerrar} guardar={guardar}
                        busy={procesando} error={errorModal} indicarError={setErrorModal} focoInicial={focoFormulario} />
                )}
            </Dialog>
            <Dialog open={confirmando} onClose={cerrar} busy={procesando}
                className="modal-confirmacion-contenido" title={`${accion} usuario`}
                initialFocusRef={focoConfirmacion} returnFocusRef={origenModal}>
                {usuarioConfirmacion && (
                    <>
                        <span className={`icono-confirmacion-usuario ${activar ? "activar" : ""}`} aria-hidden="true">
                            <Icon name={activar ? "lock_open" : "lock"} />
                        </span>
                        <h2>{accion} usuario</h2>
                        <p>
                            {activar
                                ? `¿Deseas activar la cuenta de ${usuarioConfirmacion.usuario}?`
                                : `¿Estás seguro de que deseas desactivar la cuenta de ${usuarioConfirmacion.usuario}?`}
                        </p>
                        {errorModal && <Status type="error">{errorModal}</Status>}
                        <div className="acciones-confirmacion-usuario">
                            <Button ref={focoConfirmacion} variant="secondary" onClick={cerrar} disabled={procesando}>Cancelar</Button>
                            <Button variant={activar ? "success" : "danger"} busy={procesando} busyLabel="Procesando…"
                                onClick={() => cambiar(`${ENDPOINT}/${usuarioConfirmacion.id}/toggle-active`, "PATCH", undefined, offsetActual)}>
                                {accion}
                            </Button>
                        </div>
                    </>
                )}
            </Dialog>
        </>
    );
}
