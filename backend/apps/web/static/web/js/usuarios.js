const URL_USUARIOS = "/api/v1/auth/admin/users";

const elementosUsuarios = {
    tabla: document.querySelector("#tablaUsuarios"),
    tablaContenedor: document.querySelector("#tablaUsuariosContenedor"),
    resultado: document.querySelector("#resultadoUsuarios"),
    estadoCarga: document.querySelector("#estadoCargaUsuarios"),
    estadoError: document.querySelector("#estadoErrorUsuarios"),
    mensajeError: document.querySelector("#mensajeErrorUsuarios"),
    estadoVacio: document.querySelector("#estadoVacioUsuarios"),
    botonReintentar: document.querySelector("#botonReintentarUsuarios"),
    botonCrear: document.querySelector("#botonCrearUsuario"),
    modal: document.querySelector("#modalUsuario"),
    tituloModal: document.querySelector("#tituloModalUsuario"),
    formulario: document.querySelector("#formularioUsuario"),
    mensajeFormulario: document.querySelector("#mensajeFormularioUsuario"),
    grupoUsuario: document.querySelector("#grupoUsuario"),
    grupoPassword: document.querySelector("#grupoPassword"),
    grupoActivo: document.querySelector("#grupoActivo"),
    usuario: document.querySelector("#usuarioUsuario"),
    nombre: document.querySelector("#nombreUsuario"),
    correo: document.querySelector("#correoUsuario"),
    password: document.querySelector("#passwordUsuario"),
    confirmarPassword: document.querySelector("#confirmarPasswordUsuario"),
    rol: document.querySelector("#rolUsuario"),
    activo: document.querySelector("#activoUsuario"),
    botonGuardar: document.querySelector("#botonGuardarUsuario"),
    botonCancelar: document.querySelector("#botonCancelarUsuario"),
    botonCerrar: document.querySelector("#botonCerrarModalUsuario"),
    modalConfirmacion: document.querySelector("#modalConfirmacionUsuario"),
    tituloConfirmacion: document.querySelector("#tituloConfirmacionUsuario"),
    textoConfirmacion: document.querySelector("#textoConfirmacionUsuario"),
    botonCancelarConfirmacion: document.querySelector("#botonCancelarConfirmacion"),
    botonConfirmarEstado: document.querySelector("#botonConfirmarEstado")
};

let usuarios = [];
let usuarioEnEdicion = null;
let usuarioCambioEstado = null;
let usuarioSesionId = null;
const focoFormularioUsuario = crearControlFocoModal(elementosUsuarios.modal);
const focoConfirmacionUsuario = crearControlFocoModal(elementosUsuarios.modalConfirmacion);

function ocultar(elemento) {
    if (elemento) elemento.hidden = true;
}

function mostrar(elemento) {
    if (elemento) elemento.hidden = false;
}

function limpiarElemento(elemento) {
    if (!elemento) return;
    while (elemento.firstChild) elemento.removeChild(elemento.firstChild);
}

function textoRol(rol) {
    return rol === "admin" ? "Administrador" : "Supervisor";
}

function mensajeSegunEstado(estado) {
    if (estado === 403) return "No tienes permisos para administrar usuarios.";
    if (estado === 404) return "El usuario solicitado ya no existe.";
    if (estado >= 500) return "El servidor no pudo completar la solicitud. Intenta nuevamente.";
    return "No se pudo completar la operación.";
}

function crearIconoAccion(tipo) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.classList.add("icono-boton");

    if (tipo === "editar") {
        const p1 = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const p2 = document.createElementNS("http://www.w3.org/2000/svg", "path");
        p1.setAttribute("d", "M4 20h4L18.5 9.5a2.12 2.12 0 0 0-3-3L5.5 17v3z");
        p2.setAttribute("d", "M13.5 6.5l4 4");
        svg.appendChild(p1);
        svg.appendChild(p2);
    }

    if (tipo === "desactivar") {
        const arco = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const cuerpo = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        arco.setAttribute("d", "M7 11V8a5 5 0 0 1 10 0v3");
        cuerpo.setAttribute("x", "5");
        cuerpo.setAttribute("y", "11");
        cuerpo.setAttribute("width", "14");
        cuerpo.setAttribute("height", "10");
        cuerpo.setAttribute("rx", "2");
        svg.appendChild(arco);
        svg.appendChild(cuerpo);
    }

    if (tipo === "activar") {
        const arco = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const cuerpo = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        arco.setAttribute("d", "M17 11V8a5 5 0 0 0-10 0");
        cuerpo.setAttribute("x", "5");
        cuerpo.setAttribute("y", "11");
        cuerpo.setAttribute("width", "14");
        cuerpo.setAttribute("height", "10");
        cuerpo.setAttribute("rx", "2");
        svg.appendChild(arco);
        svg.appendChild(cuerpo);
    }

    return svg;
}

async function leerRespuestaUsuarios(response) {
    if (!response) return null;

    let cuerpo = null;
    try {
        cuerpo = await response.json();
    } catch {
        cuerpo = null;
    }

    if (!response.ok) {
        const error = new Error("No se pudo completar la solicitud.");
        error.estado = response.status;
        error.codigo = cuerpo?.error?.code || null;
        error.detalles = cuerpo?.error?.details || null;
        error.mensajeApi = cuerpo?.error?.message || null;
        throw error;
    }

    if (cuerpo?.success !== true) {
        const error = new Error("Respuesta inválida del servidor.");
        error.estado = response.status;
        throw error;
    }

    return cuerpo.data;
}

function obtenerMensajeValidacion(error) {
    const campos = error?.detalles?.fields;

    if (campos && typeof campos === "object") {
        const prioridad = ["usuario", "nombre", "correo", "password", "rol", "activo", "non_field_errors"];

        for (const campo of prioridad) {
            const mensajes = campos[campo];
            if (Array.isArray(mensajes) && mensajes.length) {
                if (campo === "correo") return `Correo: ${mensajes[0]}`;
                if (campo === "usuario") return `Usuario: ${mensajes[0]}`;
                if (campo === "password") return `Contraseña: ${mensajes[0]}`;
                return mensajes[0];
            }
        }
    }

    if (error?.codigo === "AUTH_FORBIDDEN") return "No tienes permisos para realizar esta acción.";
    if (error?.codigo === "AUTH_USER_INACTIVE") return "Tu cuenta no se encuentra activa.";
    if (error?.estado === 400) return "Revisa los datos ingresados e intenta nuevamente.";
    return error?.mensajeApi || mensajeSegunEstado(error?.estado);
}

async function cargarUsuarioSesionActual() {
    try {
        const response = await apiRequest("/api/v1/auth/me", { method: "GET" });
        const datos = await leerRespuestaUsuarios(response);
        if (datos?.id) usuarioSesionId = datos.id;
    } catch {
        usuarioSesionId = null;
    }
}

function mostrarCargaUsuarios() {
    mostrar(elementosUsuarios.estadoCarga);
    ocultar(elementosUsuarios.estadoError);
    ocultar(elementosUsuarios.estadoVacio);
    ocultar(elementosUsuarios.tablaContenedor);
    if (elementosUsuarios.resultado) elementosUsuarios.resultado.textContent = "Cargando usuarios...";
}

function mostrarErrorUsuarios(mensaje) {
    ocultar(elementosUsuarios.estadoCarga);
    ocultar(elementosUsuarios.estadoVacio);
    ocultar(elementosUsuarios.tablaContenedor);
    mostrar(elementosUsuarios.estadoError);

    if (elementosUsuarios.mensajeError) elementosUsuarios.mensajeError.textContent = mensaje;
    if (elementosUsuarios.resultado) elementosUsuarios.resultado.textContent = "No fue posible recuperar los usuarios.";
}

function mostrarListaVacia() {
    ocultar(elementosUsuarios.estadoCarga);
    ocultar(elementosUsuarios.estadoError);
    ocultar(elementosUsuarios.tablaContenedor);
    mostrar(elementosUsuarios.estadoVacio);

    if (elementosUsuarios.resultado) elementosUsuarios.resultado.textContent = "0 usuarios registrados";
}

function mostrarTablaUsuarios() {
    ocultar(elementosUsuarios.estadoCarga);
    ocultar(elementosUsuarios.estadoError);
    ocultar(elementosUsuarios.estadoVacio);
    mostrar(elementosUsuarios.tablaContenedor);

    if (elementosUsuarios.resultado) {
        elementosUsuarios.resultado.textContent =
            usuarios.length === 1 ? "1 usuario registrado" : `${usuarios.length} usuarios registrados`;
    }
}

function crearCelda(texto = "") {
    const celda = document.createElement("td");
    celda.textContent = texto;
    return celda;
}

function crearEtiquetaRol(usuario) {
    const celda = document.createElement("td");
    const etiqueta = document.createElement("span");

    etiqueta.className = `etiqueta-rol ${usuario.rol === "admin" ? "admin" : "supervisor"}`;
    etiqueta.textContent = textoRol(usuario.rol);

    celda.appendChild(etiqueta);
    return celda;
}

function crearEtiquetaEstado(usuario) {
    const celda = document.createElement("td");
    const etiqueta = document.createElement("span");

    etiqueta.className = `etiqueta-usuario-estado ${usuario.activo ? "activo" : "inactivo"}`;
    etiqueta.textContent = usuario.activo ? "Activo" : "Inactivo";

    celda.appendChild(etiqueta);
    return celda;
}

function crearAccionesUsuario(usuario) {
    const celda = document.createElement("td");
    const contenedor = document.createElement("div");
    contenedor.className = "acciones-usuario";

    const botonEditar = document.createElement("button");
    botonEditar.type = "button";
    botonEditar.className = "boton-icono-usuario";
    botonEditar.dataset.tooltip = "Editar";
    botonEditar.setAttribute("aria-label", `Editar usuario ${usuario.usuario}`);
    botonEditar.appendChild(crearIconoAccion("editar"));
    botonEditar.addEventListener("click", () => abrirModalEditar(usuario, botonEditar));

    const botonEstado = document.createElement("button");
    botonEstado.type = "button";
    botonEstado.className = "boton-icono-usuario";

    if (usuario.activo) {
        botonEstado.classList.add("accion-desactivar");
        botonEstado.dataset.tooltip = "Desactivar";
        botonEstado.appendChild(crearIconoAccion("desactivar"));
    } else {
        botonEstado.classList.add("accion-activar");
        botonEstado.dataset.tooltip = "Activar";
        botonEstado.appendChild(crearIconoAccion("activar"));
    }

    botonEstado.setAttribute(
        "aria-label",
        `${usuario.activo ? "Desactivar" : "Activar"} usuario ${usuario.usuario}`
    );

    if (usuarioSesionId && usuario.id === usuarioSesionId && usuario.activo) {
        botonEstado.disabled = true;
        botonEstado.dataset.tooltip = "No puedes desactivar tu propia cuenta";
    } else {
        botonEstado.addEventListener("click", () => abrirConfirmacionEstado(usuario, botonEstado));
    }

    contenedor.appendChild(botonEditar);
    contenedor.appendChild(botonEstado);
    celda.appendChild(contenedor);

    return celda;
}

function renderizarUsuarios() {
    limpiarElemento(elementosUsuarios.tabla);

    if (!usuarios.length) {
        mostrarListaVacia();
        return;
    }

    for (const usuario of usuarios) {
        const fila = document.createElement("tr");

        const celdaUsuario = document.createElement("td");
        const usuarioDestacado = document.createElement("strong");
        usuarioDestacado.textContent = usuario.usuario;
        celdaUsuario.appendChild(usuarioDestacado);

        fila.appendChild(celdaUsuario);
        fila.appendChild(crearCelda(usuario.nombre || "—"));
        fila.appendChild(crearCelda(usuario.correo || "—"));
        fila.appendChild(crearEtiquetaRol(usuario));
        fila.appendChild(crearEtiquetaEstado(usuario));
        fila.appendChild(crearAccionesUsuario(usuario));

        elementosUsuarios.tabla.appendChild(fila);
    }

    mostrarTablaUsuarios();
}

async function cargarUsuarios() {
    mostrarCargaUsuarios();

    try {
        const response = await apiRequest(URL_USUARIOS, { method: "GET" });
        if (!response) return;

        const datos = await leerRespuestaUsuarios(response);
        usuarios = Array.isArray(datos) ? datos : [];
        renderizarUsuarios();
    } catch (error) {
        console.error("ERROR USUARIOS:", error);

        if (error?.estado === 403) {
            mostrarErrorUsuarios("No tienes permisos para acceder a la gestión de usuarios.");
            if (elementosUsuarios.botonCrear) elementosUsuarios.botonCrear.hidden = true;
            return;
        }

        mostrarErrorUsuarios(mensajeSegunEstado(error?.estado));
    }
}

function mostrarErrorFormulario(mensaje) {
    elementosUsuarios.mensajeFormulario.textContent = mensaje;
    mostrar(elementosUsuarios.mensajeFormulario);
}

function limpiarErrorFormulario() {
    elementosUsuarios.mensajeFormulario.textContent = "";
    ocultar(elementosUsuarios.mensajeFormulario);
}

function abrirModalBase(focoInicial, origen) {
    mostrar(elementosUsuarios.modal);
    document.body.style.overflow = "hidden";
    focoFormularioUsuario.abrir(focoInicial, origen);
}

function abrirModalCrear(evento) {
    usuarioEnEdicion = null;
    elementosUsuarios.formulario.reset();
    limpiarErrorFormulario();

    elementosUsuarios.tituloModal.textContent = "Crear usuario";
    elementosUsuarios.botonGuardar.textContent = "Crear usuario";

    mostrar(elementosUsuarios.grupoUsuario);
    mostrar(elementosUsuarios.grupoPassword);
    mostrar(elementosUsuarios.grupoActivo);

    elementosUsuarios.usuario.disabled = false;
    elementosUsuarios.usuario.required = true;
    elementosUsuarios.password.required = true;
    elementosUsuarios.confirmarPassword.required = true;
    elementosUsuarios.password.type = "password";
    elementosUsuarios.confirmarPassword.type = "password";
    elementosUsuarios.rol.value = "supervisor";
    elementosUsuarios.activo.value = "true";

    abrirModalBase(elementosUsuarios.usuario, evento.currentTarget);
}

function abrirModalEditar(usuario, origen) {
    usuarioEnEdicion = usuario;
    elementosUsuarios.formulario.reset();
    limpiarErrorFormulario();

    elementosUsuarios.tituloModal.textContent = "Editar usuario";
    elementosUsuarios.botonGuardar.textContent = "Guardar cambios";

    ocultar(elementosUsuarios.grupoUsuario);
    ocultar(elementosUsuarios.grupoPassword);
    ocultar(elementosUsuarios.grupoActivo);

    elementosUsuarios.usuario.required = false;
    elementosUsuarios.password.required = false;
    elementosUsuarios.confirmarPassword.required = false;
    elementosUsuarios.password.type = "password";
    elementosUsuarios.confirmarPassword.type = "password";

    elementosUsuarios.nombre.value = usuario.nombre || "";
    elementosUsuarios.correo.value = usuario.correo || "";
    elementosUsuarios.rol.value = usuario.rol || "supervisor";

    abrirModalBase(elementosUsuarios.nombre, origen);
}

function cerrarModalUsuario() {
    ocultar(elementosUsuarios.modal);
    document.body.style.overflow = "";
    usuarioEnEdicion = null;
    limpiarErrorFormulario();

    focoFormularioUsuario.cerrar(elementosUsuarios.botonCrear);
}

async function crearUsuario() {
    const payload = {
        usuario: elementosUsuarios.usuario.value.trim(),
        nombre: elementosUsuarios.nombre.value.trim(),
        correo: elementosUsuarios.correo.value.trim(),
        password: elementosUsuarios.password.value,
        rol: elementosUsuarios.rol.value,
        activo: elementosUsuarios.activo.value === "true"
    };

    const response = await apiRequest(URL_USUARIOS, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    return leerRespuestaUsuarios(response);
}

async function editarUsuario() {
    const payload = {
        nombre: elementosUsuarios.nombre.value.trim(),
        correo: elementosUsuarios.correo.value.trim(),
        rol: elementosUsuarios.rol.value
    };

    const response = await apiRequest(`${URL_USUARIOS}/${usuarioEnEdicion.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    return leerRespuestaUsuarios(response);
}

async function guardarUsuario(evento) {
    evento.preventDefault();
    limpiarErrorFormulario();

    if (!elementosUsuarios.formulario.checkValidity()) {
        elementosUsuarios.formulario.reportValidity();
        return;
    }

    if (!usuarioEnEdicion &&
        elementosUsuarios.password.value !== elementosUsuarios.confirmarPassword.value)
        {
        mostrarErrorFormulario("Las contraseñas no coinciden.");
        elementosUsuarios.confirmarPassword.focus();
        return;
    }

    elementosUsuarios.botonGuardar.disabled = true;
    const textoOriginal = elementosUsuarios.botonGuardar.textContent;
    elementosUsuarios.botonGuardar.textContent = "Guardando...";

    try {
        if (usuarioEnEdicion) await editarUsuario();
        else await crearUsuario();

        cerrarModalUsuario();
        await cargarUsuarios();
    } catch (error) {
        mostrarErrorFormulario(obtenerMensajeValidacion(error));
    } finally {
        elementosUsuarios.botonGuardar.disabled = false;
        elementosUsuarios.botonGuardar.textContent = textoOriginal;
    }
}

function abrirConfirmacionEstado(usuario, origen) {
    usuarioCambioEstado = usuario;

    const vaAActivar = !usuario.activo;

    elementosUsuarios.tituloConfirmacion.textContent = vaAActivar ? "Activar usuario" : "Desactivar usuario";

    elementosUsuarios.textoConfirmacion.textContent = vaAActivar
        ? `¿Deseas activar la cuenta de ${usuario.usuario}?`
        : `¿Estás seguro de que deseas desactivar la cuenta de ${usuario.usuario}?`;

    elementosUsuarios.botonConfirmarEstado.textContent = vaAActivar ? "Activar" : "Desactivar";
    elementosUsuarios.botonConfirmarEstado.classList.toggle("activar", vaAActivar);

    mostrar(elementosUsuarios.modalConfirmacion);
    document.body.style.overflow = "hidden";

    focoConfirmacionUsuario.abrir(elementosUsuarios.botonCancelarConfirmacion, origen);
}

function cerrarConfirmacionEstado() {
    ocultar(elementosUsuarios.modalConfirmacion);
    document.body.style.overflow = "";
    usuarioCambioEstado = null;

    focoConfirmacionUsuario.cerrar(elementosUsuarios.botonCrear);
}

async function confirmarCambioEstado() {
    if (!usuarioCambioEstado) return;

    elementosUsuarios.botonConfirmarEstado.disabled = true;
    const textoOriginal = elementosUsuarios.botonConfirmarEstado.textContent;
    elementosUsuarios.botonConfirmarEstado.textContent = "Procesando...";

    try {
        const response = await apiRequest(
            `${URL_USUARIOS}/${usuarioCambioEstado.id}/toggle-active`,
            { method: "PATCH" }
        );

        await leerRespuestaUsuarios(response);
        cerrarConfirmacionEstado();
        await cargarUsuarios();
    } catch (error) {
        cerrarConfirmacionEstado();
        mostrarErrorUsuarios(obtenerMensajeValidacion(error));
    } finally {
        elementosUsuarios.botonConfirmarEstado.disabled = false;
        elementosUsuarios.botonConfirmarEstado.textContent = textoOriginal;
    }
}

function manejarEscape(evento) {
    if (evento.key !== "Escape") return;

    if (elementosUsuarios.modalConfirmacion && !elementosUsuarios.modalConfirmacion.hidden) {
        cerrarConfirmacionEstado();
        return;
    }

    if (elementosUsuarios.modal && !elementosUsuarios.modal.hidden) cerrarModalUsuario();
}

elementosUsuarios.botonCrear?.addEventListener("click", abrirModalCrear);
elementosUsuarios.botonReintentar?.addEventListener("click", cargarUsuarios);
elementosUsuarios.formulario?.addEventListener("submit", guardarUsuario);
elementosUsuarios.botonCancelar?.addEventListener("click", cerrarModalUsuario);
elementosUsuarios.botonCerrar?.addEventListener("click", cerrarModalUsuario);
elementosUsuarios.botonCancelarConfirmacion?.addEventListener("click", cerrarConfirmacionEstado);
elementosUsuarios.botonConfirmarEstado?.addEventListener("click", confirmarCambioEstado);

document.querySelectorAll("[data-cerrar-modal-usuario]").forEach((elemento) => {
    elemento.addEventListener("click", cerrarModalUsuario);
});

document.querySelectorAll("[data-cerrar-confirmacion]").forEach((elemento) => {
    elemento.addEventListener("click", cerrarConfirmacionEstado);
});

document.addEventListener("keydown", manejarEscape);

document.querySelectorAll("[data-toggle-password]").forEach((boton) => {
    boton.addEventListener("click", () => {
        const campo = document.querySelector(`#${boton.dataset.togglePassword}`);

        if (!campo) return;

        const mostrarPassword = campo.type === "password";

        campo.type = mostrarPassword ? "text" : "password";
        boton.setAttribute("aria-pressed", String(mostrarPassword));
        boton.setAttribute(
            "aria-label",
            mostrarPassword ? "Ocultar contraseña" : "Mostrar contraseña"
        );
    });
});

async function iniciarGestionUsuarios() {
    await cargarUsuarioSesionActual();
    await cargarUsuarios();
}

iniciarGestionUsuarios();