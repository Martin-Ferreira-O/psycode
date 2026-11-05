from django.conf import settings
from django.core.checks import Error, Tags, register
from .encryption import encryption_status


@register(Tags.security, deploy=True)
def encrypted_sensitive_storage(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    if not settings.SENSITIVE_STORAGE_ENCRYPTION_REQUIRED:
        return [Error("El cifrado del almacenamiento sensible es obligatorio en producción.", id="capture.E010")]
    if not encryption_status()["verified"]:
        return [Error("Verifique volúmenes cifrados y protección de claves con verify_sensitive_storage.", id="capture.E011")]
    return []
