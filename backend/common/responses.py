from django.utils import timezone
from rest_framework.response import Response


def timestamp():
    return timezone.now().isoformat().replace("+00:00", "Z")


def success_response(data, message, status=200):
    if status == 204:
        return Response(status=204)
    return Response({"success": True, "data": data, "message": message, "timestamp": timestamp()}, status=status)
