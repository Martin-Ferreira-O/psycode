import { useEffect, useRef, useState } from "react";
import { solicitarJson } from "../api.js";
import { Icon } from "../ui.jsx";
import { AuthLayout, AuthStatus, AuthSubmit, PasswordField } from "./AuthLayout.jsx";

const rules = [
    ["length", "Al menos 12 caracteres", password => password.length >= 12, "La contraseña debe tener al menos 12 caracteres."],
    ["case", "Mayúsculas y minúsculas", password => /[a-z]/.test(password) && /[A-Z]/.test(password),
        "La contraseña debe contener mayúsculas y minúsculas."],
    ["number", "Al menos un número", password => /\d/.test(password), "La contraseña debe contener al menos un número."],
    ["symbol", "Al menos un símbolo (!, @, #…)", password => /[^a-zA-Z0-9]/.test(password),
        "La contraseña debe contener al menos un símbolo especial."],
    ["match", "Las contraseñas deben coincidir", (password, confirm) => password.length > 0 && password === confirm,
        "Las contraseñas no coinciden."],
];

const resetErrors = {
    400: "La contraseña ingresada no cumple con las políticas de seguridad institucionales o el enlace ha expirado.",
    404: "El enlace es inválido o no fue encontrado. Solicita una nueva recuperación.",
};

export default function PasswordReset({ config, resetToken }) {
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [status, setStatus] = useState(resetToken ? null : {
        type: "error", message: "El enlace de recuperación es inválido o no contiene un token de acceso.",
    });
    const inFlight = useRef(false);
    const validations = rules.map(([key, label, passes, message]) => ({ key, label, valid: passes(password, confirm), message }));
    const complete = status?.type === "exito";
    const busy = status?.type === "carga";
    const disabled = !resetToken || busy || complete;

    useEffect(() => {
        if (!complete) return;
        const timer = window.setTimeout(() => window.location.assign("/"), 2500);
        return () => window.clearTimeout(timer);
    }, [complete]);

    async function submit(event) {
        event.preventDefault();
        if (disabled || inFlight.current) return;
        const invalid = validations.find(rule => !rule.valid);
        if (invalid) {
            setStatus({ type: "error", message: invalid.message });
            return;
        }

        inFlight.current = true;
        setStatus({ type: "carga", message: "Actualizando contraseña…" });
        try {
            await solicitarJson("/api/v1/auth/password-reset/confirm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token: resetToken, nueva_password: password }),
            });
            setStatus({ type: "exito", message: "Contraseña actualizada con éxito. Redirigiendo al inicio de sesión…" });
        } catch (error) {
            inFlight.current = false;
            setStatus({ type: "error", error });
        }
    }

    return (
        <AuthLayout logoUrl={config.logoUrl} title="Nueva contraseña" reset
            description="Elige una nueva contraseña para recuperar el acceso a tu cuenta."
            footer={<a href="/" className="forgot-link reset-back-link"><Icon name="arrow_back" />Volver al inicio de sesión</a>}>
            <AuthStatus value={status} messages={resetErrors} />
            <form id="reset-confirm-form" onSubmit={submit} noValidate>
                <PasswordField id="nueva_password" label="Nueva contraseña" fieldName="nueva contraseña"
                    disabled={disabled} autoComplete="new-password" minLength={12} aria-describedby="password-requirements"
                    placeholder="Ingresa tu nueva contraseña" value={password} onChange={event => setPassword(event.target.value)} />
                <PasswordField id="confirm_password" label="Confirmar nueva contraseña" fieldName="confirmación de contraseña"
                    disabled={disabled} autoComplete="new-password" minLength={12} aria-describedby="chk-match"
                    placeholder="Repite tu nueva contraseña" value={confirm} onChange={event => setConfirm(event.target.value)} />
                <div className="password-requirements" id="password-requirements">
                    <p className="checklist-title">Tu nueva contraseña debe incluir:</p>
                    <ul className="checklist" id="password-checklist">
                        {validations.map(({ key, label, valid }) => (
                            <li key={key} id={`chk-${key}`} className={`checklist-item${valid ? " valid" : ""}`}>
                                <span className="chk-icon" aria-hidden="true">{valid ? "✓" : "○"}</span>{label}
                            </li>
                        ))}
                    </ul>
                </div>
                <AuthSubmit busy={busy} disabled={disabled} busyLabel="Actualizando…">Actualizar contraseña</AuthSubmit>
            </form>
        </AuthLayout>
    );
}
