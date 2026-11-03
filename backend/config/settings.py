"""Configuración compartida. El modo local debe habilitarse explícitamente."""
import json
import os
import re
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"{name} debe ser true o false.")
    return value in {"true", "1"}


def local_path(name, default):
    path = Path(os.getenv(name, default))
    return path if path.is_absolute() else BASE_DIR / path


DEBUG = env_bool("DJANGO_DEBUG")
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY es obligatoria fuera de desarrollo.")
    private_dir = BASE_DIR / ".local"
    private_dir.mkdir(mode=0o700, exist_ok=True)
    key_file = private_dir / "django-secret-key"
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        SECRET_KEY = key_file.read_text().strip()
    else:
        with os.fdopen(fd, "w") as stream:
            SECRET_KEY = secrets.token_urlsafe(64)
            stream.write(SECRET_KEY)
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY debe tener al menos 50 caracteres.")

ALLOWED_HOSTS = [v.strip() for v in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if v.strip()]
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")).rstrip("/")
origin = urlsplit(FRONTEND_BASE_URL)
if (origin.scheme not in {"http", "https"} or not origin.netloc or origin.path
        or origin.query or origin.fragment or origin.username or origin.password):
    raise ImproperlyConfigured("FRONTEND_BASE_URL debe ser un origen HTTP(S), sin ruta ni credenciales.")
if not DEBUG and origin.scheme != "https":
    raise ImproperlyConfigured("FRONTEND_BASE_URL debe usar HTTPS fuera de desarrollo.")
FRONTEND_ORIGIN = FRONTEND_BASE_URL
PASSWORD_RESET_PATH = os.getenv("PASSWORD_RESET_PATH", "/password-reset/confirm")
if (not PASSWORD_RESET_PATH.startswith("/") or PASSWORD_RESET_PATH.startswith("//")
        or urlsplit(PASSWORD_RESET_PATH).query or urlsplit(PASSWORD_RESET_PATH).fragment
        or urlsplit(PASSWORD_RESET_PATH).netloc):
    raise ImproperlyConfigured("PASSWORD_RESET_PATH debe ser una ruta absoluta sin consulta ni fragmento.")

INSTALLED_APPS = [
    "backend.apps.agenda",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "corsheaders",
    "rest_framework",
    "backend.apps.accounts.apps.AccountsConfig",
    "backend.apps.alerts.apps.AlertsConfig",
    "backend.apps.analysis.apps.AnalysisConfig",
    "backend.apps.dashboard.apps.DashboardConfig",
    "backend.apps.notifications.apps.NotificationsConfig",
    "django.contrib.staticfiles",
    "backend.apps.web.apps.WebConfig",
    "backend.apps.operational.apps.OperationalConfig",
    "backend.apps.capture.apps.CaptureConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

STATIC_URL = "/static/"
# Nginx sirve este directorio después de ejecutar collectstatic.
STATIC_ROOT = local_path("STATIC_ROOT", "staticfiles")
ROOT_URLCONF = "backend.config.urls"
WSGI_APPLICATION = "backend.config.wsgi.application"
ASGI_APPLICATION = "backend.config.asgi.application"
APPEND_SLASH = False
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": local_path("SQLITE_PATH", ".local/db.sqlite3"),
    "OPTIONS": {"timeout": 10, "transaction_mode": "IMMEDIATE"},
}}
DATABASES["default"]["NAME"].parent.mkdir(parents=True, exist_ok=True)
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["backend.apps.accounts.authentication.AccountJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "backend.common.errors.exception_handler",
    "UNAUTHENTICATED_USER": None,
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=24),
    "CHECK_REVOKE_TOKEN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ISSUER": "psycode-api",
}
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "psycode").strip() or "psycode"
# Un proceso Django de clínica, baja concurrencia: pool por defecto de PyMongo.
# 5s para fallar rápido y responder 503 en lugar de colgar el request.
MONGODB_SERVER_SELECTION_TIMEOUT_MS = 5000

# Rotación propia transaccional en RefreshSession; no combinar con blacklist app.
PASSWORD_RESET_LIFETIME = timedelta(hours=1)
def positive_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un entero positivo.") from None
    if value <= 0:
        raise ImproperlyConfigured(f"{name} debe ser un entero positivo.")
    return value


EMAIL_DELIVERY_TIMEOUT = positive_int("EMAIL_TIMEOUT_SECONDS", 10)
PASSWORD_RESET_RATE_LIMIT_MAX = positive_int("PASSWORD_RESET_RATE_LIMIT_MAX", 5)
PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS = positive_int("PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS", 900)
EMAIL_BACKEND_CHOICE = os.getenv("EMAIL_BACKEND", "file" if DEBUG else "smtp")
EMAIL_BACKEND_CHOICE = {
    "django.core.mail.backends.filebased.EmailBackend": "file",
    "django.core.mail.backends.smtp.EmailBackend": "smtp",
}.get(EMAIL_BACKEND_CHOICE, EMAIL_BACKEND_CHOICE)
EMAIL_BACKEND = {"file": "django.core.mail.backends.filebased.EmailBackend",
                 "smtp": "django.core.mail.backends.smtp.EmailBackend"}.get(EMAIL_BACKEND_CHOICE)
if EMAIL_BACKEND is None:
    raise ImproperlyConfigured("EMAIL_BACKEND debe ser file o smtp.")
EMAIL_FILE_PATH = local_path("EMAIL_FILE_PATH", ".local/emails")
EMAIL_HOST = os.getenv("SMTP_HOST", os.getenv("EMAIL_HOST", ""))
EMAIL_PORT = positive_int("SMTP_PORT", os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("SMTP_USERNAME", os.getenv("EMAIL_HOST_USER", ""))
EMAIL_HOST_PASSWORD = os.getenv("SMTP_PASSWORD", os.getenv("EMAIL_HOST_PASSWORD", ""))
EMAIL_USE_TLS = env_bool("SMTP_USE_TLS", env_bool("EMAIL_USE_TLS", True))
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = EMAIL_DELIVERY_TIMEOUT
DEFAULT_FROM_EMAIL = os.getenv("EMAIL_FROM", os.getenv("DEFAULT_FROM_EMAIL", "no-reply@psycode.local"))
if EMAIL_BACKEND_CHOICE == "smtp" and (not EMAIL_HOST or not DEFAULT_FROM_EMAIL):
    raise ImproperlyConfigured("SMTP_HOST y EMAIL_FROM son obligatorios para SMTP.")
CORS_ALLOWED_ORIGINS = [FRONTEND_BASE_URL]
CORS_ALLOW_CREDENTIALS = False
CORS_URLS_REGEX = r"^/api/v1/.*$"
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"psycode.audit": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}

# SCRUM-67: destinatarios, sin credenciales de las cuentas receptoras.
NOTIFICATIONS_ENABLED = env_bool("NOTIFICATIONS_ENABLED", False)
NOTIFICATION_EMAIL_TO = os.getenv("NOTIFICATION_EMAIL_TO", "").strip()
NOTIFICATION_EMAIL_BACKUP_TO = os.getenv("NOTIFICATION_EMAIL_BACKUP_TO", "").strip()
TEAMS_ENABLED = False  # Webhook y continuidad pendientes de decisión.

# Ingesta interna: credenciales independientes del JWT de profesionales.
CAPTURE_FRAGMENT_ROOT = local_path("CAPTURE_FRAGMENT_ROOT", ".local/capture-fragments")
CAPTURE_FRAGMENT_MAX_BYTES = positive_int("CAPTURE_FRAGMENT_MAX_BYTES", 25 * 1024 * 1024)
CAPTURE_ORPHAN_MAX_AGE_SECONDS = positive_int("CAPTURE_ORPHAN_MAX_AGE_SECONDS", 3600)
try:
    CAPTURE_AGENTS = json.loads(os.getenv("CAPTURE_AGENTS", "{}"))
    if not isinstance(CAPTURE_AGENTS, dict):
        raise ValueError
    for agent_id, credential in CAPTURE_AGENTS.items():
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent_id)
                or not isinstance(credential, dict) or set(credential) != {"box", "token_sha256"}
                or credential["box"] not in {f"box-{n}" for n in range(3, 8)}
                or not isinstance(credential["token_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", credential["token_sha256"])):
            raise ValueError
except (TypeError, ValueError):
    raise ImproperlyConfigured("CAPTURE_AGENTS debe contener identidades, boxes y hashes SHA-256 válidos.") from None

# Los procesos se inician mediante comandos explícitos, nunca desde ASGI.
CAPTURE_COMMAND_INTERVAL_SECONDS = positive_int("CAPTURE_COMMAND_INTERVAL_SECONDS", 1)
CAPTURE_COORDINATOR_INTERVAL_SECONDS = positive_int("CAPTURE_COORDINATOR_INTERVAL_SECONDS", 5)
CAPTURE_HEARTBEAT_SECONDS = positive_int("CAPTURE_HEARTBEAT_SECONDS", 30)
CAPTURE_START_TIMEOUT_SECONDS = positive_int("CAPTURE_START_TIMEOUT_SECONDS", 120)
CAPTURE_INACTIVITY_TIMEOUT_SECONDS = positive_int("CAPTURE_INACTIVITY_TIMEOUT_SECONDS", 120)
CAPTURE_FINALIZATION_TIMEOUT_SECONDS = positive_int("CAPTURE_FINALIZATION_TIMEOUT_SECONDS", 300)

# Colectores designados por el servidor; sin elección entre PCs.
try:
    CAPTURE_AGENDA_SOURCES = json.loads(os.getenv("CAPTURE_AGENDA_SOURCES", "{}"))
    agenda_boxes = set()
    if not isinstance(CAPTURE_AGENDA_SOURCES, dict):
        raise ValueError()
    for source, scope in CAPTURE_AGENDA_SOURCES.items():
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source) or not isinstance(scope, dict)
                or set(scope) != {"collector_id", "boxes"} or scope["collector_id"] not in CAPTURE_AGENTS
                or not isinstance(scope["boxes"], list) or not scope["boxes"]
                or len(set(scope["boxes"])) != len(scope["boxes"])
                or set(scope["boxes"]) - {f"box-{n}" for n in range(3, 8)}
                or agenda_boxes.intersection(scope["boxes"])):
            raise ValueError()
        agenda_boxes.update(scope["boxes"])
except (TypeError, ValueError):
    raise ImproperlyConfigured("CAPTURE_AGENDA_SOURCES inválido o con fuentes superpuestas.") from None
