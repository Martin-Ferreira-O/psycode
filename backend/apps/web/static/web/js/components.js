const botonCerrarSesion = document.querySelector("[data-logout]");

if (botonCerrarSesion) {
    botonCerrarSesion.addEventListener(
        "click",
        async () => {
            await cerrarSesion();
        }
    );
}
async function mostrarUsuarioSesion() {
    const etiqueta = document.querySelector("[data-usuario-sesion]");
    if (!etiqueta) return;

    try {
        const datos = await apiGetDatos("/api/v1/auth/me");
        const usuario = typeof datos?.usuario === "string" ? datos.usuario.trim() : "";
        etiqueta.textContent = usuario || "Usuario no disponible";
    } catch (error) {
        etiqueta.textContent = "Usuario no disponible";
    }
}

mostrarUsuarioSesion();
