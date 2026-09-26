const botonCerrarSesion = document.querySelector("[data-logout]");

if (botonCerrarSesion) {
    botonCerrarSesion.addEventListener(
        "click",
        async () => {
            await cerrarSesion();
        }
    );
}