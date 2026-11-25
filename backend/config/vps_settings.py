from .settings import *
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SILENCED_SYSTEM_CHECKS = ["security.W021"]
if not SENSITIVE_STORAGE_EXTRA_ROOTS:
    SENSITIVE_STORAGE_EXTRA_ROOTS = ["/var/lib/mongodb", "/srv/psycode/backups"]
