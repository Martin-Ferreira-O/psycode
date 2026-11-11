import { useRef, useState } from "react";
import { cabecerasNavegador, ErrorSolicitud, retirarTokensAntiguos, solicitarJson } from "../api.js";
import { Button, Dialog, Icon } from "../ui.jsx";
import { AuthLayout, AuthStatus, AuthSubmit, PasswordField } from "./AuthLayout.jsx";

const loginErrors = {
    401: "Usuario o contraseña incorrectos. Revisa tus datos e inténtalo nuevamente.",
    403: "Tu cuenta no está habilitada para iniciar sesión. Contacta al administrador.",
};

function publicPost(url, body) {
    return solicitarJson(url, {
        method: "POST",
        credentials: "same-origin",
        headers: cabecerasNavegador({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
    });
}

function Recovery({ open, onClose, trigger }) {
    const input = useRef(null);
    const inFlight = useRef(false);
    const [email, setEmail] = useState("");
    const [status, setStatus] = useState(null);
    const pending = status?.type === "carga";

    function close() {
        setStatus(null);
        onClose();
    }

    async function submit(event) {
        event.preventDefault();
        if (inFlight.current) return;
        inFlight.current = true;
        setStatus({ type: "carga", message: "Enviando instrucciones…" });
        try {
            await publicPost("/api/v1/auth/password-reset", { correo: email.trim() });
            setStatus({ type: "exito", message: "Si el usuario existe, se enviaron instrucciones de recuperación a su correo." });
            setEmail("");
        } catch (error) {
            setStatus({ type: "error", error });
        } finally {
            inFlight.current = false;
        }
    }

    return (
        <Dialog id="recovery-modal" open={open} onClose={close} busy={pending}
            initialFocusRef={input} returnFocusRef={trigger} className="modal-card auth-dialog" title="Recuperar contraseña">
            <header className="modal-header">
                <div><span className="modal-eyebrow">Recuperación de acceso</span><h3>Recuperar contraseña</h3></div>
                <Button variant="secondary" iconOnly id="close-modal-btn" aria-label="Cerrar" disabled={pending} onClick={close}>
                    <Icon name="close" />
                </Button>
            </header>
            <div className="modal-body">
                <p className="modal-desc">Ingresa tu correo institucional para recibir las instrucciones de recuperación.</p>
                <AuthStatus id="recovery-alert" value={status} />
                <form id="recovery-form" onSubmit={submit}>
                    <div className="form-group">
                        <label htmlFor="recovery-username">Correo institucional</label>
                        <div className="input-shell">
                            <Icon name="email" className="input-icon" />
                            <input ref={input} id="recovery-username" type="email" autoComplete="email"
                                placeholder="nombre@institucion.cl" value={email} onChange={event => setEmail(event.target.value)} required />
                        </div>
                    </div>
                    <AuthSubmit id="recovery-submit-btn" busy={pending} busyLabel="Enviando" arrow={false}>Enviar instrucciones</AuthSubmit>
                </form>
            </div>
        </Dialog>
    );
}

export default function Login({ config }) {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [status, setStatus] = useState(null);
    const [recoveryOpen, setRecoveryOpen] = useState(false);
    const recoveryTrigger = useRef(null);
    const inFlight = useRef(false);

    async function submit(event) {
        event?.preventDefault();
        if (inFlight.current) return;
        const usuario = username.trim();
        if (!usuario || !password) {
            setStatus({ type: "error", message: "Por favor, ingresa tu usuario y contraseña." });
            return;
        }

        inFlight.current = true;
        setStatus({ type: "carga", message: "Iniciando sesión…" });
        try {
            const data = await publicPost("/api/v1/auth/login", { usuario, password });
            if (data.authenticated !== true) throw new ErrorSolicitud();
            retirarTokensAntiguos();
            window.location.assign("/dashboard");
        } catch (error) {
            inFlight.current = false;
            setStatus({ type: "error", error });
        }
    }

    return (
        <AuthLayout logoUrl={config.logoUrl} title="Iniciar sesión"
            description="Ingresa con tus credenciales institucionales para continuar."
            footer={<><Icon name="lock" /><span>Acceso restringido a personal autorizado</span></>}>
            <AuthStatus value={status} messages={loginErrors} onRetry={status?.error ? submit : undefined} />
            <form id="login-form" onSubmit={submit} noValidate>
                <div className="form-group">
                    <label htmlFor="username">Correo institucional o usuario</label>
                    <div className="input-shell">
                        <Icon name="person" className="input-icon" />
                        <input id="username" name="username" placeholder="nombre@institucion.cl" autoComplete="username"
                            value={username} onChange={event => setUsername(event.target.value)} required />
                    </div>
                </div>
                <PasswordField id="password" label="Contraseña" toggleId="toggle-password" autoComplete="current-password"
                    placeholder="Ingresa tu contraseña" value={password} onChange={event => setPassword(event.target.value)}
                    action={<button type="button" className="forgot-link auth-link" id="forgot-password-link" ref={recoveryTrigger}
                        onClick={() => setRecoveryOpen(true)}>¿Olvidaste tu contraseña?</button>} />
                <AuthSubmit busy={status?.type === "carga"} busyLabel="Iniciando sesión">Ingresar al sistema</AuthSubmit>
            </form>
            <Recovery open={recoveryOpen} trigger={recoveryTrigger} onClose={() => setRecoveryOpen(false)} />
        </AuthLayout>
    );
}
