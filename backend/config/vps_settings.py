"""Production configuration for the loopback-only ASGI server behind Nginx."""
from .settings import *  # noqa: F403

# Nginx replaces this header and ASGI only listens on 127.0.0.1.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Browser HSTS preload lists accept DNS names; this temporary endpoint is an IP.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
