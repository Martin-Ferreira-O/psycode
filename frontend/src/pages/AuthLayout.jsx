import { useState } from "react";
import { Button, Icon, Status } from "../ui.jsx";

export function AuthLayout({ logoUrl, title, description, footer, children, reset = false }) {
    return (
        <main className="login-wrapper">
            <section className="login-visual">
                <div className="login-university-logo"><img src={logoUrl} alt="Universidad Autónoma de Chile" /></div>
                <div className="visual-glow visual-glow-1" />
                <div className="visual-glow visual-glow-2" />
                <div className="visual-grid" />
                <div className="visual-content">
                    <h1>Información clara para decisiones que importan.</h1>
                    <div className="visual-features">
                        {["Gestión de alertas", "Evaluación profesional", "Seguimiento centralizado"].map(feature => (
                            <div className="visual-feature" key={feature}><span className="feature-dot" />{feature}</div>
                        ))}
                    </div>
                </div>
                <div className="visual-footer">
                    <span>Plataforma institucional</span>
                    <span className="visual-status"><span className="status-dot" />Acceso seguro</span>
                </div>
            </section>
            <section className="login-panel" aria-labelledby="auth-title">
                <div className={`login-card${reset ? " password-reset-card" : ""}`}>
                    <header className="login-card-header">
                        <h2 id="auth-title">{title}</h2>
                        <p>{description}</p>
                    </header>
                    {children}
                    <footer className="login-card-footer">{footer}</footer>
                </div>
            </section>
        </main>
    );
}

export function PasswordField({ label, action, disabled, id, fieldName = "contraseña", toggleId, ...props }) {
    const [visible, setVisible] = useState(false);
    return (
        <div className="form-group">
            <div className="password-label-row"><label htmlFor={id}>{label}</label>{action}</div>
            <div className="input-shell password-input-wrapper">
                <Icon name="lock" className="input-icon" />
                <input {...props} id={id} name={id} type={visible ? "text" : "password"} disabled={disabled} required />
                <Button variant="ghost" iconOnly className="toggle-password-btn" id={toggleId}
                    aria-controls={id} aria-pressed={visible} disabled={disabled}
                    aria-label={`${visible ? "Ocultar" : "Mostrar"} ${fieldName}`}
                    onClick={() => setVisible(value => !value)}>
                    <Icon name={visible ? "visibility_off" : "visibility"} />
                </Button>
            </div>
        </div>
    );
}

export function AuthStatus({ id = "alert-box", value, messages, onRetry }) {
    return value ? (
        <Status id={id} className="alert-box" type={value.type} error={value.error} messages={messages} onRetry={onRetry}>
            {value.message}
        </Status>
    ) : null;
}

export function AuthSubmit({ id = "submit-btn", busy, disabled, busyLabel, arrow = true, children }) {
    return (
        <Button id={id} className="auth-submit" variant="primary" type="submit" disabled={disabled} busy={busy} busyLabel={busyLabel}>
            <span className="btn-text">{children}{arrow && <Icon name="arrow_forward" />}</span>
        </Button>
    );
}
