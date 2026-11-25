import json
import smtplib
import sys


def main():
    from django.conf import settings
    from django.core.mail import send_mail

    payload = json.load(sys.stdin)
    settings.configure(**payload['config'])
    try:
        return 0 if send_mail(**payload['mail']) == 1 else 4
    except TimeoutError:
        return 2
    except smtplib.SMTPException:
        return 4
    except OSError:
        return 3


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        code = 1
    sys.exit(code)
