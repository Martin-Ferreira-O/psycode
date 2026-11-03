document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("reset-confirm-form");
  const nuevaPassInput = document.getElementById("nueva_password");
  const confirmPassInput = document.getElementById("confirm_password");
  const submitBtn = document.getElementById("submit-btn");
  const alertBox = document.getElementById("alert-box");

  // Elementos del Checklist
  const chkLength = document.getElementById("chk-length");
  const chkCase = document.getElementById("chk-case");
  const chkNumber = document.getElementById("chk-number");
  const chkSymbol = document.getElementById("chk-symbol");
  const chkMatch = document.getElementById("chk-match");

  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  if (token) {
    const cleanUrl = window.location.origin + window.location.pathname;
    window.history.replaceState({}, document.title, cleanUrl);
  } else {
    mostrarEstado(
      alertBox,
      "error",
      "El enlace de recuperación es inválido o no contiene un token de acceso."
    );
    nuevaPassInput.disabled = true;
    confirmPassInput.disabled = true;
    submitBtn.disabled = true;
    document.querySelectorAll(".toggle-password-btn").forEach(btn => { btn.disabled = true; });
    return;
  }

  document.querySelectorAll(".toggle-password-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-target");
      const input = document.getElementById(targetId);
      const isPassword = input.getAttribute("type") === "password";
      input.setAttribute("type", isPassword ? "text" : "password");
      btn.setAttribute("aria-pressed", String(isPassword));
      const campo = targetId === "nueva_password" ? "nueva contraseña" : "confirmación de contraseña";
      btn.setAttribute("aria-label", `${isPassword ? "Ocultar" : "Mostrar"} ${campo}`);
    });
  });

  function actualizarChecklist() {
    const p1 = nuevaPassInput.value;
    const p2 = confirmPassInput.value;

    const validaciones = [
      { el: chkLength, cumple: p1.length >= 12 },
      { el: chkCase, cumple: /[a-z]/.test(p1) && /[A-Z]/.test(p1) },
      { el: chkNumber, cumple: /\d/.test(p1) },
      { el: chkSymbol, cumple: /[^a-zA-Z0-9]/.test(p1) },
      { el: chkMatch, cumple: p1.length > 0 && p1 === p2 },
    ];

    validaciones.forEach(({ el, cumple }) => {
      if (!el) return;
      el.classList.toggle("valid", cumple);
      const icono = el.querySelector(".chk-icon");
      if (icono) {
        icono.innerHTML = cumple ? "&#10003;" : "&#9675;";
      }
    });
  }

  nuevaPassInput.addEventListener("input", actualizarChecklist);
  confirmPassInput.addEventListener("input", actualizarChecklist);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (submitBtn.disabled) return;
    limpiarEstado(alertBox);

    const nuevaPassword = nuevaPassInput.value;
    const confirmPassword = confirmPassInput.value;

    if (nuevaPassword.length < 12) {
      mostrarEstado(alertBox, "error", "La contraseña debe tener al menos 12 caracteres.");
      return;
    }

    if (!/[a-z]/.test(nuevaPassword) || !/[A-Z]/.test(nuevaPassword)) {
      mostrarEstado(alertBox, "error", "La contraseña debe contener mayúsculas y minúsculas.");
      return;
    }

    if (!/\d/.test(nuevaPassword)) {
      mostrarEstado(alertBox, "error", "La contraseña debe contener al menos un número.");
      return;
    }

    if (!/[^a-zA-Z0-9]/.test(nuevaPassword)) {
      mostrarEstado(alertBox, "error", "La contraseña debe contener al menos un símbolo especial.");
      return;
    }

    if (nuevaPassword !== confirmPassword) {
      mostrarEstado(alertBox, "error", "Las contraseñas no coinciden.");
      return;
    }

    establecerCargaBoton(submitBtn, true, "Actualizando…");
    mostrarCarga(alertBox, "Actualizando contraseña…");
    nuevaPassInput.disabled = true;
    confirmPassInput.disabled = true;

    try {
      await solicitarJson("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: token,
          nueva_password: nuevaPassword,
        }),
      });

      mostrarEstado(
        alertBox,
        "exito",
        "Contraseña actualizada con éxito. Redirigiendo al inicio de sesión…"
      );

      setTimeout(() => {
        window.location.href = "/";
      }, 2500);
    } catch (error) {
      nuevaPassInput.disabled = false;
      confirmPassInput.disabled = false;
      establecerCargaBoton(submitBtn, false);

      mostrarError(alertBox, error, {
        mensajes: {
          400: "La contraseña ingresada no cumple con las políticas de seguridad institucionales o el enlace ha expirado.",
          404: "El enlace es inválido o no fue encontrado. Solicita una nueva recuperación.",
        },
      });
    }
  });
});