document.addEventListener("DOMContentLoaded", () => {
  // Elementos Login
  const form = document.getElementById("login-form");
  const usernameInput = document.getElementById("username");
  const passwordInput = document.getElementById("password");
  const toggleBtn = document.getElementById("toggle-password");
  const submitBtn = document.getElementById("submit-btn");
  const alertBox = document.getElementById("alert-box");

  // Elementos Modal Recuperación
  const forgotLink = document.getElementById("forgot-password-link");
  const recoveryModal = document.getElementById("recovery-modal");
  const closeModalBtn = document.getElementById("close-modal-btn");
  const recoveryForm = document.getElementById("recovery-form");
  const recoveryInput = document.getElementById("recovery-username");
  const recoveryAlert = document.getElementById("recovery-alert");
  const recoverySubmitBtn = document.getElementById("recovery-submit-btn");

  // Alternar Visibilidad Contraseña
  toggleBtn.addEventListener("click", () => {
    const isPassword = passwordInput.getAttribute("type") === "password";
    passwordInput.setAttribute("type", isPassword ? "text" : "password");
  });

  // Envío Formulario Login
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (submitBtn.disabled) return;
    limpiarEstado(alertBox);

    const usuario = usernameInput.value.trim();
    const password = passwordInput.value;

    // Validación previa
    if (!usuario || !password) {
      mostrarEstado(alertBox, "error", "Por favor, ingresa tu correo y contraseña.");
      return;
    }

    establecerCargaBoton(submitBtn, true, "Iniciando sesión…");
    mostrarCarga(alertBox, "Iniciando sesión…");

    try {
      const data = await solicitarJson("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usuario, password }),
      });

      if (!data.access_token || !data.refresh_token) throw new ErrorSolicitud();
      localStorage.setItem("access_token", data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      window.location.href = "/dashboard";
    } catch (error) {
      mostrarError(alertBox, error, {
        mensajes: {
          401: "Usuario o contraseña incorrectos. Revisa tus datos e inténtalo de nuevo.",
          403: "Tu cuenta no está habilitada para iniciar sesión. Contacta al administrador.",
        },
        reintentar: () => form.requestSubmit(),
      });
    } finally {
      establecerCargaBoton(submitBtn, false);
    }
  });

  // Manejo Modal de Recuperación
  forgotLink.addEventListener("click", (e) => {
    e.preventDefault();
    limpiarEstado(recoveryAlert);
    recoveryModal.style.display = "flex";
  });

  closeModalBtn.addEventListener("click", () => {
    recoveryModal.style.display = "none";
  });

  recoveryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (recoverySubmitBtn.disabled) return;
    limpiarEstado(recoveryAlert);

    const usuario = recoveryInput.value.trim();
    if (!usuario) {
      mostrarEstado(recoveryAlert, "error", "Por favor, ingresa tu correo institucional.");
      return;
    }

    establecerCargaBoton(recoverySubmitBtn, true, "Enviando…");

    try {
      await solicitarJson("/api/v1/auth/password-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ correo: usuario }),
      });

      mostrarEstado(
        recoveryAlert, "exito",
        "Si el usuario existe, se enviaron instrucciones de recuperación a su correo."
      );
      recoveryForm.reset();
    } catch (error) {
      mostrarError(recoveryAlert, error);
    } finally {
      establecerCargaBoton(recoverySubmitBtn, false);
    }
  });

});
