const botonCerrarSesion = document.querySelector("[data-logout]");

if (botonCerrarSesion) {
    botonCerrarSesion.addEventListener("click", async () => {
        await cerrarSesion();
    });
}

function mostrarElementosAdmin(esAdmin) {
    document.querySelectorAll("[data-admin-only]").forEach((elemento) => {
        elemento.hidden = !esAdmin;

        if (esAdmin) {
            elemento.style.removeProperty("display");
        } else {
            elemento.style.setProperty("display", "none", "important");
        }
    });
}

async function mostrarUsuarioSesion() {
    const etiquetaUsuario = document.querySelector("[data-usuario-sesion]");
    const etiquetaRol = document.querySelector("[data-usuario-rol]");
    const iconoUsuario = document.querySelector("[data-usuario-icono]");

    mostrarElementosAdmin(false);

    try {
        const datos = await apiGetDatos("/api/v1/auth/me");

        const usuario =
            typeof datos?.usuario === "string"
                ? datos.usuario.trim()
                : "";

        const rol =
            typeof datos?.rol === "string"
                ? datos.rol.trim().toLowerCase()
                : "";

        if (etiquetaUsuario) {
            etiquetaUsuario.textContent =
                usuario || "Usuario no disponible";
        }

        if (rol === "admin") {
            if (etiquetaRol) {
                etiquetaRol.textContent = "Administrador";
            }

            if (iconoUsuario) {
                iconoUsuario.textContent = "A";
            }

            mostrarElementosAdmin(true);
        } else {
            if (etiquetaRol) {
                etiquetaRol.textContent = "Supervisor";
            }

            if (iconoUsuario) {
                iconoUsuario.textContent = "S";
            }

            mostrarElementosAdmin(false);
        }
    } catch (error) {
        if (etiquetaUsuario) {
            etiquetaUsuario.textContent = "Usuario no disponible";
        }

        if (etiquetaRol) {
            etiquetaRol.textContent = "Usuario";
        }

        if (iconoUsuario) {
            iconoUsuario.textContent = "U";
        }

        mostrarElementosAdmin(false);
    }
}

function crearControlFocoModal(dialogo) {
    const fondo = document.querySelector(".aplicacion");
    let focoAnterior = null;
    dialogo.tabIndex = -1;

    function mantenerFoco(evento) {
        if (evento.key !== "Tab") return;

        const controles = [...dialogo.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]")]
            .filter(control => control.tabIndex >= 0 && !control.matches(":disabled")
                && control.getClientRects().length && getComputedStyle(control).visibility === "visible");
        const foco = document.activeElement;
        const indice = controles.indexOf(foco);
        const paso = evento.shiftKey ? -1 : 1;
        const siguiente = indice >= 0 ? controles[indice + paso] : undefined;
        const radio = 'input[type="radio"]';
        if (siguiente && !foco.matches(radio) && !siguiente.matches(radio)) return;

        evento.preventDefault();
        const extremo = evento.shiftKey ? controles.at(-1) : controles[0];
        (siguiente ?? extremo ?? dialogo).focus();
    }

    return {
        abrir(focoInicial, origen = document.activeElement) {
            if (!focoAnterior) {
                focoAnterior = origen ?? document.body;
                fondo.inert = true;
                document.addEventListener("keydown", mantenerFoco);
            }
            focoInicial.focus();
        },
        cerrar(respaldo) {
            if (!focoAnterior) return;
            document.removeEventListener("keydown", mantenerFoco);
            fondo.inert = false;
            focoAnterior.focus();
            if (document.activeElement !== focoAnterior) respaldo?.focus();
            focoAnterior = null;
        },
    };
}

mostrarUsuarioSesion();
