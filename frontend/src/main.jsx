import { Component, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { retirarTokensAntiguos } from "./api.js";
import { AppLayout } from "./layout.jsx";
import { Status } from "./ui.jsx";

const pages = {
    login: lazy(() => import("./pages/Login.jsx")),
    password_reset_confirm: lazy(() => import("./pages/PasswordReset.jsx")),
    dashboard: lazy(() => import("./pages/Dashboard.jsx")),
    evaluaciones: lazy(() => import("./pages/Evaluaciones.jsx")),
    usuarios: lazy(() => import("./pages/Usuarios.jsx")),
    pcs: lazy(() => import("./pages/Pcs.jsx")),
    bitacora: lazy(() => import("./pages/Bitacora.jsx")),
    configuracion_operativa: lazy(() => import("./pages/ConfiguracionOperativa.jsx")),
    almacenamiento: lazy(() => import("./pages/Almacenamiento.jsx")),
};

class PageError extends Component {
    state = { failed: false };

    static getDerivedStateFromError() {
        return { failed: true };
    }

    render() {
        if (this.state.failed) {
            return <div className="ui-session-panel">
                <Status type="error" onRetry={() => window.location.reload()}>No pudimos cargar la página.</Status>
            </div>;
        }
        return this.props.children;
    }
}

const config = JSON.parse(document.getElementById("psycode-config").textContent);
const Page = pages[config.page];
const resetToken = config.page === "password_reset_confirm" ?
    new URLSearchParams(window.location.search).get("token") : null;

if (resetToken) window.history.replaceState(null, "", window.location.pathname);
retirarTokensAntiguos();

function Screen({ user }) {
    return (
        <Suspense fallback={<div className="ui-session-panel"><Status>Cargando página…</Status></div>}>
            <Page config={config} user={user} resetToken={resetToken} />
        </Suspense>
    );
}

createRoot(document.getElementById("psycode-root")).render(
    <PageError>
        {config.public ? <Screen /> : <AppLayout config={config}>{user => <Screen user={user} />}</AppLayout>}
    </PageError>
);
