"""Tests aislados de credenciales reales y sin correos de red."""
import os

os.environ["DJANGO_DEBUG"] = "true"
os.environ["DJANGO_SECRET_KEY"] = "test-only-not-for-deployment-" * 3
os.environ["FRONTEND_ORIGIN"] = "http://localhost:5173"

from .settings import *  # noqa: E402,F403

DEBUG = False
SECURE_SSL_REDIRECT = False
MONGODB_URI = os.getenv("PSYCODE_TEST_MONGODB_URI", "").strip()
MONGODB_DATABASE = "psycode_test"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES["default"] = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / ".local/test-auth.sqlite3",
    "OPTIONS": {
        "timeout": 30,
        "transaction_mode": "DEFERRED",
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout = 30000;",
    },
    "TEST": {"NAME": BASE_DIR / ".local/test-auth.sqlite3"},
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "handlers": {"null": {"class": "logging.NullHandler"}},
           "loggers": {"psycode.audit": {"handlers": ["null"], "propagate": False}}}
