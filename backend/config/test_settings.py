import os
from unittest.mock import patch

from django.conf import global_settings

os.environ["DJANGO_DEBUG"] = "true"
os.environ["DJANGO_SECRET_KEY"] = "test-only-not-for-deployment-" * 3
os.environ["FRONTEND_ORIGIN"] = "http://localhost:5173"
os.environ["FRONTEND_BASE_URL"] = "http://localhost:5173"

with patch("dotenv.load_dotenv"):
    from .settings import *

DEBUG = False
SECURE_SSL_REDIRECT = False
MONGODB_URI = os.getenv("PSYCODE_TEST_MONGODB_URI", "").strip()
MONGODB_DATABASE = "psycode_test"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES["default"]["TEST"] = {"NAME": os.getenv("PSYCODE_TEST_SQLITE_PATH", str(BASE_DIR / ".local/test-auth.sqlite3"))}
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    *global_settings.PASSWORD_HASHERS,
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "handlers": {"null": {"class": "logging.NullHandler"}},
           "loggers": {"psycode.audit": {"handlers": ["null"], "propagate": False}}}

NOTIFICATIONS_ENABLED = False
SMILE_USERNAME = ""
SMILE_PASSWORD = ""
SMILE_DEFAULT_URL = ""
NOTIFICATION_EMAIL_TO = "primary@example.test"
NOTIFICATION_EMAIL_BACKUP_TO = "backup@example.test"

SENSITIVE_STORAGE_ENCRYPTION_REQUIRED = False
SENSITIVE_STORAGE_EXTRA_ROOTS = []
SENSITIVE_STORAGE_KEY_FILES = []
