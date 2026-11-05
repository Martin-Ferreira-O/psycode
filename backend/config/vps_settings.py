"""Production configuration for the loopback-only ASGI server behind Nginx."""
from .settings import *  # noqa: F403

# Nginx replaces this header and ASGI only listens on 127.0.0.1.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Browser HSTS preload lists accept DNS names; this temporary endpoint is an IP.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# El VPS aloja Mongo y respaldos locales además del material de procesamiento.
if not SENSITIVE_STORAGE_EXTRA_ROOTS:
    SENSITIVE_STORAGE_EXTRA_ROOTS = ["/var/lib/mongodb", "/srv/psycode/backups"]
