import json
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.core.mail import send_mail

    payload = json.load(sys.stdin)
    if settings.EMAIL_BACKEND.endswith("filebased.EmailBackend"):
        os.umask(0o077)
        settings.EMAIL_FILE_PATH.mkdir(parents=True, mode=0o700, exist_ok=True)
    sent = send_mail(
        "Recuperación de contraseña — Psycode",
        "Para restablecer tu contraseña, abre el siguiente enlace. Vence en una hora y solo puede usarse una vez.\n\n"
        + payload["link"] + "\n\nSi no lo solicitaste, ignora este mensaje.",
        settings.DEFAULT_FROM_EMAIL,
        [payload["email"]],
        fail_silently=False,
    )
    return 0 if sent == 1 else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        exit_code = 1
    sys.exit(exit_code)
