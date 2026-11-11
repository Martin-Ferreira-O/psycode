import { createContext, useContext, useEffect, useRef, useState } from "react";
import { apiGetDatos, cerrarSesion } from "./api.js";
import { Button, Icon, Skeleton, Status } from "./ui.jsx";

const Session = createContext(null);

const navigation = [
    { page: "dashboard", href: "/dashboard", label: "Dashboard", icon: "dashboard" },
    { page: "evaluaciones", href: "/evaluaciones", label: "Registro de evaluaciones", icon: "fact_check" },
    { page: "usuarios", href: "/usuarios", label: "Gestión de usuarios", icon: "manage_accounts", admin: true },
    { page: "pcs", href: "/api/v1/pcs/panel", label: "Gestión de PCs", icon: "monitor", admin: true },
    { page: "bitacora", href: "/bitacora", label: "Bitácora", icon: "history", admin: true },
    { page: "configuracion_operativa", href: "/configuracion-operativa", label: "Configuración operativa", icon: "settings", admin: true },
];

export function UserBadge({ user: explicitUser } = {}) {
    const sessionUser = useContext(Session);
    const user = explicitUser ?? sessionUser;
    if (!user) return null;
    const isAdmin = user.rol === "admin";
    return (
        <div className="usuario-dashboard">
            <div className="usuario-avatar" data-usuario-icono aria-hidden="true">{isAdmin ? "A" : "S"}</div>
            <div className="usuario-datos">
                <strong data-usuario-rol>{isAdmin ? "Administrador" : "Supervisor"}</strong>
                <span data-usuario-sesion>{user.usuario || "Usuario no disponible"}</span>
            </div>
        </div>
    );
}

export function PageHeader({ title, description, children }) {
    return (
        <header className="cabecera-dashboard ui-page-header">
            <div>
                <h1>{title}</h1>
                {description && <p className="subtitulo-dashboard">{description}</p>}
            </div>
            <UserBadge />
            {children && <div className="ui-page-actions">{children}</div>}
        </header>
    );
}

const loadingSections = {
    dashboard: ["Indicadores principales", "Comportamiento mensual", "Historial de alertas"],
    evaluaciones: ["Evaluaciones registradas"],
    usuarios: ["Usuarios registrados"],
    pcs: ["Equipos de la clínica"],
    bitacora: ["Eventos de la bitácora"],
    configuracion_operativa: ["Horario clínico y alertas"],
    almacenamiento: ["Espacio del servidor", "Limpieza periódica"],
};

export function PageLoading({ config }) {
    return (
        <>
            <PageHeader title={config.heading} />
            <div className="ui-page-loading" aria-busy="true">
                {loadingSections[config.page].map(title => (
                    <section key={title} className="ui-loading-panel">
                        <h2>{title}</h2>
                        <Skeleton />
                        <Skeleton />
                        <Skeleton />
                    </section>
                ))}
            </div>
        </>
    );
}

function Sidebar({ config, user }) {
    const [loggingOut, setLoggingOut] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const sidebarRef = useRef(null);
    const toggleRef = useRef(null);
    const active = config.page === "almacenamiento" ? "configuracion_operativa" : config.page;

    useEffect(() => {
        if (!menuOpen) return;

        const mobileLayout = window.matchMedia("(max-width: 950px)");
        const close = () => setMenuOpen(false);

        function closeOnOutsidePress(event) {
            if (!sidebarRef.current.contains(event.target)) close();
        }

        document.addEventListener("click", closeOnOutsidePress);
        mobileLayout.addEventListener("change", close);
        window.addEventListener("pageshow", close);
        return () => {
            document.removeEventListener("click", closeOnOutsidePress);
            mobileLayout.removeEventListener("change", close);
            window.removeEventListener("pageshow", close);
        };
    }, [menuOpen]);

    function closeOnEscape(event) {
        if (menuOpen && event.key === "Escape") {
            event.preventDefault();
            setMenuOpen(false);
            toggleRef.current.focus();
        }
    }

    async function logout() {
        setLoggingOut(true);
        try {
            await cerrarSesion();
        } finally {
            setLoggingOut(false);
        }
    }

    return (
        <aside className="barra-lateral ui-sidebar" ref={sidebarRef} onKeyDown={closeOnEscape}>
            <div className="marca-universidad">
                <img src={config.logoUrl} alt="Universidad Autónoma de Chile" className="logo-universidad-sidebar" />
            </div>
            <button type="button" className="sidebar-toggle" ref={toggleRef}
                aria-expanded={menuOpen} aria-controls="sidebar-panel" onClick={() => setMenuOpen(open => !open)}>
                <Icon name={menuOpen ? "close" : "menu"} />
                Menú
            </button>
            <div id="sidebar-panel" className="sidebar-panel" data-open={menuOpen}>
                <nav className="navegacion" aria-label="Navegación principal">
                    {navigation.filter(link => !link.admin || user?.rol === "admin").map(link => (
                        <a key={link.page} href={link.href} className={`enlace-menu${active === link.page ? " activo" : ""}`}
                            aria-current={active === link.page ? "page" : undefined} data-admin-only={link.admin || undefined}>
                            <Icon name={link.icon} />
                            {link.label}
                        </a>
                    ))}
                </nav>
                {user && (
                    <Button variant="ghost" id="logout-btn" className="cerrar-sesion" data-logout=""
                        aria-label="Cerrar sesión" busy={loggingOut} busyLabel="Cerrando sesión…" onClick={logout}>
                        <Icon name="logout" /><span>Cerrar sesión</span>
                    </Button>
                )}
            </div>
        </aside>
    );
}

const adminMessages = {
    usuarios: "Esta pantalla y sus datos están disponibles únicamente para administradores.",
    pcs: "Esta pantalla y sus datos están disponibles únicamente para administradores.",
    bitacora: "Esta pantalla y sus datos están disponibles únicamente para administradores.",
    configuracion_operativa: "Esta pantalla y sus datos están disponibles únicamente para administradores.",
    almacenamiento: "Esta pantalla y sus datos están disponibles únicamente para administradores.",
};

export function AppLayout({ config, children }) {
    const [user, setUser] = useState(null);
    const [sessionError, setSessionError] = useState(null);
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        async function loadSession() {
            try {
                const data = await apiGetDatos("/api/v1/auth/me", { signal: controller.signal });
                if (!controller.signal.aborted) {
                    setUser({ ...data, rol: data.rol?.trim().toLowerCase(), usuario: data.usuario?.trim() });
                    setSessionError(null);
                }
            } catch (error) {
                if (!controller.signal.aborted) {
                    setUser(null);
                    setSessionError(error);
                }
            }
        }
        loadSession();

        function revalidate(event) {
            if (event.persisted) loadSession();
        }
        window.addEventListener("pageshow", revalidate);
        return () => {
            controller.abort();
            window.removeEventListener("pageshow", revalidate);
        };
    }, [attempt]);

    const denied = user && user.rol !== "admin" && adminMessages[config.page];
    const contentClass = `contenido-dashboard${config.page === "bitacora" ? " contenido-bitacora" : ""}`;

    return (
        <Session.Provider value={user}>
            <div className="aplicacion ui-app">
                <a className="saltar-contenido" href="#contenido-principal">Saltar al contenido</a>
                <Sidebar config={config} user={user} />
                <main id="contenido-principal" className={`principal ui-main ${contentClass}`} tabIndex={-1}>
                    {user && !denied ? children(user) : denied || sessionError ? (
                        <div className="ui-session-panel">
                            <PageHeader title={config.heading} />
                            {denied && <Status type="error">{denied}</Status>}
                            {sessionError && <Status type="error" error={sessionError} onRetry={() => {
                                setSessionError(null);
                                setAttempt(value => value + 1);
                            }} />}
                        </div>
                    ) : <PageLoading config={config} />}
                </main>
            </div>
        </Session.Provider>
    );
}
