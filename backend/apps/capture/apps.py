from django.apps import AppConfig


class CaptureConfig(AppConfig):
    name = "backend.apps.capture"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks  # noqa: F401
