from django.db import OperationalError, InterfaceError
from django.http import JsonResponse
from rest_framework import exceptions
from rest_framework.response import Response

from .audit import AuditWriter
from .responses import timestamp


class ServiceError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details = details or {}


class PersistenceUnavailable(ServiceError):
    def __init__(self):
        super().__init__("PERSISTENCE_UNAVAILABLE", "Persistencia no disponible", 503)


def error_body(code, message, details=None):
    return {"success": False, "error": {"code": code, "message": message, "details": details or {}}, "timestamp": timestamp()}


def exception_handler(exc, context):
    from rest_framework.views import exception_handler as drf_exception_handler

    headers = {}
    if isinstance(exc, ServiceError):
        status, code, message, details = exc.status, exc.code, exc.message, exc.details
    elif isinstance(exc, (OperationalError, InterfaceError)):
        status, code, message, details = 503, "PERSISTENCE_UNAVAILABLE", "Persistencia no disponible", {}
    else:
        response = drf_exception_handler(exc, context)
        if response is None:
            AuditWriter.record("api.error", "failure", error_code="INTERNAL_ERROR")
            status, code, message, details = 500, "INTERNAL_ERROR", "Error interno del servidor", {}
        else:
            status = response.status_code
            headers = dict(response.items())
            mapping = {
                400: ("VALIDATION_ERROR", "Datos de entrada inválidos"),
                401: ("AUTH_REQUIRED" if isinstance(exc, exceptions.NotAuthenticated) else "AUTH_INVALID_TOKEN", "Autenticación requerida o inválida"),
                403: ("AUTH_FORBIDDEN", "Operación no permitida"),
                404: ("RESOURCE_NOT_FOUND", "Recurso no encontrado"),
                405: ("METHOD_NOT_ALLOWED", "Método no permitido"),
                415: ("UNSUPPORTED_MEDIA_TYPE", "Se requiere application/json"),
            }
            code, message = mapping.get(status, ("INTERNAL_ERROR", "Error interno del servidor"))
            details = {"fields": response.data} if isinstance(exc, exceptions.ValidationError) else {}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return Response(error_body(code, message, details), status=status, headers=headers)


def not_found(request, exception=None):
    return JsonResponse(error_body("RESOURCE_NOT_FOUND", "Ruta no encontrada"), status=404)


def bad_request(request, exception=None):
    return JsonResponse(error_body("VALIDATION_ERROR", "Solicitud inválida"), status=400)


def server_error(request):
    return JsonResponse(error_body("INTERNAL_ERROR", "Error interno del servidor"), status=500)
