document.addEventListener("DOMContentLoaded", () => {
  // Elementos Login
  const form = document.getElementById("login-form");
  const usernameInput = document.getElementById("username");
  const passwordInput = document.getElementById("password");
  const toggleBtn = document.getElementById("toggle-password");
  const submitBtn = document.getElementById("submit-btn");
  const btnText = submitBtn.querySelector(".btn-text");
  const btnLoader = submitBtn.querySelector(".btn-loader");
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
    hideAlert(alertBox);

    const usuario = usernameInput.value.trim();
    const password = passwordInput.value;

    // Validación previa
    if (!usuario || !password) {
      showAlert(alertBox, "Por favor, ingresa tu correo y contraseña.");
      return;
    }

    setLoading(submitBtn, btnText, btnLoader, true);

    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usuario, password }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        if (data.data?.access_token) {
          localStorage.setItem("access_token", data.data.access_token);
          localStorage.setItem("refresh_token", data.data.refresh_token);
        }
        window.location.href = "/dashboard";
      } else {
        showAlert(alertBox, data.message || "Credenciales incorrectas. Inténtalo de nuevo.");
      }
    } catch (error) {
      showAlert(alertBox, "Error de conexión con el servidor. Inténtalo más tarde.");
    } finally {
      setLoading(submitBtn, btnText, btnLoader, false);
    }
  });

  // Manejo Modal de Recuperación
  forgotLink.addEventListener("click", (e) => {
    e.preventDefault();
    hideAlert(recoveryAlert);
    recoveryModal.style.display = "flex";
  });

  closeModalBtn.addEventListener("click", () => {
    recoveryModal.style.display = "none";
  });

  recoveryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideAlert(recoveryAlert);

    const usuario = recoveryInput.value.trim();
    if (!usuario) {
      showAlert(recoveryAlert, "Por favor, ingresa tu correo institucional.");
      return;
    }

    const rText = recoverySubmitBtn.querySelector(".btn-text");
    const rLoader = recoverySubmitBtn.querySelector(".btn-loader");
    setLoading(recoverySubmitBtn, rText, rLoader, true);

    try {
      const response = await fetch("/api/v1/auth/password-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ correo: usuario })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showAlert(
          recoveryAlert, 
          "Si el usuario existe, se enviaron instrucciones de recuperación a su correo.", 
          true
        );
        recoveryForm.reset();
      } else {
        showAlert(recoveryAlert, data.message || "No fue posible iniciar el proceso de recuperación.");
      }
    } catch (error) {
      showAlert(recoveryAlert, "Error de conexión con el servidor.");
    } finally {
      setLoading(recoverySubmitBtn, rText, rLoader, false);
    }
  });

  function showAlert(targetBox, message, isSuccess = false) {
    targetBox.textContent = message;
    targetBox.style.display = "block";
    targetBox.className = isSuccess ? "alert-box success" : "alert-box";
  }

  function hideAlert(targetBox) {
    targetBox.style.display = "none";
  }

  function setLoading(btn, textEl, loaderEl, isLoading) {
    btn.disabled = isLoading;
    textEl.style.display = isLoading ? "none" : "inline";
    loaderEl.style.display = isLoading ? "inline" : "none";
  }
});