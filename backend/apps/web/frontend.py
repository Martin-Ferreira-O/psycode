"""Configuración pública de las pantallas que renderiza React."""

from django.shortcuts import render
from django.templatetags.static import static


SCREENS = {
    "login": ("Iniciar sesión", "Sistema de Alertas - Acceso institucional", ("login",)),
    "password_reset_confirm": ("Nueva contraseña", "Nueva contraseña - Sistema de Alertas", ("login",)),
    "dashboard": ("Dashboard de alertas", "Dashboard de alertas", ("dashboard", "alertas")),
    "evaluaciones": ("Registro de evaluaciones", "Registro de evaluaciones", ("alertas", "evaluaciones")),
    "usuarios": ("Gestión de usuarios", "Gestión de usuarios | Psycode", ("usuarios",)),
    "pcs": ("Gestión de PCs", "Gestión de PCs | Psycode", ("pcs",)),
    "bitacora": ("Bitácora del sistema", "Bitácora | Psycode", ("alertas", "bitacora")),
    "configuracion_operativa": ("Configuración operativa", "Configuración operativa | Psycode", ("configuracion_operativa",)),
    "almacenamiento": ("Almacenamiento del servidor", "Almacenamiento del servidor | Psycode", ("configuracion_operativa", "almacenamiento")),
}


def render_screen(request, page, **page_config):
    heading, title, styles = SCREENS[page]
    public = page in {"login", "password_reset_confirm"}
    base = ("styles",)
    stylesheets = [f"web/css/{name}.css" for name in (*base, "estados", *styles)]
    config = {"page": page, "heading": heading, "public": public, "logoUrl": static("web/img/logo.png"), **page_config}
    return render(request, "web/app.html", {"config": config, "title": title, "stylesheets": stylesheets})
