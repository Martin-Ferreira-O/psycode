"""Configuración compartida. El modo local debe habilitarse explícitamente."""
import os
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
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
origin = urlsplit(FRONTEND_ORIGIN)
if (origin.scheme not in {"http", "https"} or not origin.netloc or origin.path
        or origin.query or origin.fragment or origin.username or origin.password):
    raise ImproperlyConfigured("FRONTEND_ORIGIN debe ser un origen HTTP(S), sin ruta ni credenciales.")
if not DEBUG and origin.scheme != "https":
    raise ImproperlyConfigured("FRONTEND_ORIGIN debe usar HTTPS fuera de desarrollo.")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "corsheaders",
    "rest_framework",
    "backend.apps.accounts.apps.AccountsConfig",
    "backend.apps.alerts.apps.AlertsConfig",
    "backend.apps.dashboard.apps.DashboardConfig",
    "backend.apps.notifications.apps.NotificationsConfig",
    "django.contrib.staticfiles",
    "backend.apps.web.apps.WebConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
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

STATIC_URL = "static/"
ROOT_URLCONF = "backend.config.urls"
WSGI_APPLICATION = "backend.config.wsgi.application"
ASGI_APPLICATION = "backend.config.asgi.application"
APPEND_SLASH = False
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": local_path("SQLITE_PATH", ".local/db.sqlite3"),
    "OPTIONS": {
        "timeout": 30,
        "transaction_mode": "DEFERRED",
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout = 30000;",
    },
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
EMAIL_DELIVERY_TIMEOUT = 10
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.filebased.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend")
EMAIL_FILE_PATH = local_path("EMAIL_FILE_PATH", ".local/emails")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = EMAIL_DELIVERY_TIMEOUT
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "psycode@example.test")
CORS_ALLOWED_ORIGINS = [FRONTEND_ORIGIN]
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
